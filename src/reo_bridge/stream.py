"""Manages the persistent RTSP stream via a pipe-based architecture.

A single output FFmpeg reads raw video from a pipe and encodes to RTSP.
Idle frames (black) and clip frames are written to the same pipe,
so the RTSP stream never drops during switchovers.
"""

import fcntl
import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from .config import Config
from .encoder_params import EncoderParams
from .streaming_params import StreamingParams

log = logging.getLogger(__name__)


def _yuv420p_solid(width: int, height: int, y: int, u: int, v: int) -> bytes:
    """Generate a single solid-colour YUV420P frame."""
    y_plane = bytes([y]) * (width * height)
    u_plane = bytes([u]) * (width * height // 4)
    v_plane = bytes([v]) * (width * height // 4)
    return y_plane + u_plane + v_plane


class StreamManager:
    """Pipe-fed RTSP stream that seamlessly switches between idle and clip playback."""

    def __init__(
        self,
        config: Config,
        encoder_params: EncoderParams,
        streaming_params: StreamingParams,
        shutdown_event: threading.Event | None = None,
    ) -> None:
        self._config = config
        self._encoder_params = encoder_params
        self._streaming_params = streaming_params
        self._shutdown = shutdown_event or threading.Event()
        self._output_proc: subprocess.Popen | None = None
        self._write_fd: int | None = None
        self._encoder_version: int = -1  # track which version we're running
        self._encoder_dead: bool = False  # set when a pipe write fails
        self._next_deadline: float | None = None  # absolute idle-frame schedule

        w, h = config.stream_width, config.stream_height

        # Pre-generate idle frame (black in YUV420P: Y=0, U=128, V=128)
        self._black_frame = _yuv420p_solid(w, h, 0, 128, 128)
        self._frame_size = w * h * 3 // 2  # bytes per YUV420P frame
        self._frame_interval = 1.0 / config.stream_fps

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the persistent output FFmpeg pipeline (call once)."""
        self._start_encoder()

    def _start_encoder(self) -> None:
        """Start (or restart) the output FFmpeg with current encoder params."""
        read_fd, self._write_fd = os.pipe()

        # A raw 1440p frame is ~5.3 MiB; the default 64 KiB pipe forces ~85
        # write syscalls per frame. Enlarging it is best-effort — the limit
        # (fs.pipe-max-size) varies by host and the default still works.
        try:
            fcntl.fcntl(self._write_fd, fcntl.F_SETPIPE_SZ, 1024 * 1024)
        except OSError:
            pass

        w = self._config.stream_width
        h = self._config.stream_height
        fps = self._config.stream_fps

        encoder_args = self._encoder_params.ffmpeg_args()
        self._encoder_version = self._encoder_params.version

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            # Raw video input from pipe
            "-f", "rawvideo",
            "-pixel_format", "yuv420p",
            "-video_size", f"{w}x{h}",
            "-framerate", str(fps),
            "-i", "pipe:0",
            # Silent audio (keeps stream format consistent for Frigate)
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            # Encode (from encoder params)
            *encoder_args,
            # Output to RTSP
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            self._config.rtsp_output_url,
        ]

        log.info("Starting output pipeline → %s", self._config.rtsp_output_url)
        log.info("Encoder args: %s", " ".join(encoder_args))
        self._output_proc = subprocess.Popen(
            cmd, stdin=read_fd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        os.close(read_fd)  # only the output FFmpeg needs the read end

        # Surface encoder diagnostics — an encoder failure with a silent
        # stderr is undiagnosable. The thread exits when the process does.
        threading.Thread(
            target=self._log_encoder_stderr,
            args=(self._output_proc.stderr,),
            daemon=True,
            name="encoder-stderr",
        ).start()

        self._encoder_dead = False
        self._next_deadline = None

    @staticmethod
    def _log_encoder_stderr(pipe) -> None:
        for raw in pipe:
            log.warning("encoder: %s", raw.decode(errors="replace").rstrip())

    def _stop_encoder(self) -> None:
        """Shut down the current encoder process and close the pipe."""
        if self._output_proc is not None:
            if self._output_proc.poll() is None:
                self._output_proc.send_signal(signal.SIGINT)
                try:
                    self._output_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._output_proc.kill()
                    self._output_proc.wait()
            self._output_proc = None

        if self._write_fd is not None:
            os.close(self._write_fd)
            self._write_fd = None

    def stop(self) -> None:
        """Shut down the output pipeline."""
        self._stop_encoder()

    def restart(self) -> None:
        """Restart the encoder pipeline with current encoder params.

        Called when encoder params change via the web UI.
        Causes a brief stream interruption — acceptable for tuning.
        """
        log.info("Restarting encoder pipeline with updated parameters...")
        self._stop_encoder()
        self._start_encoder()
        log.info("Encoder pipeline restarted.")

    def needs_restart(self) -> bool:
        """Check if encoder params have changed since last start."""
        return self._encoder_params.version != self._encoder_version

    def encoder_dead(self) -> bool:
        """True if the output encoder has died (pipe broke or process exited)."""
        if self._encoder_dead:
            return True
        return self._output_proc is not None and self._output_proc.poll() is not None

    # ------------------------------------------------------------------ #
    #  Idle frames (called from the main loop)
    # ------------------------------------------------------------------ #

    def write_idle_frame(self) -> None:
        """Write one black idle frame, paced against an absolute schedule.

        Relative sleeps (interval − elapsed) never compensate for sleep
        overshoot, so the loop would run slightly under the nominal FPS and
        stream latency would grow with uptime. Advancing an absolute deadline
        keeps long-run drift bounded.
        """
        now = time.monotonic()
        # (Re)sync after startup, a clip (paced by the decoder, not us), or a
        # stall — otherwise we'd blast frames to "catch up" on a stale deadline.
        if self._next_deadline is None or now - self._next_deadline > 1.0:
            self._next_deadline = now

        self._write_to_pipe(self._black_frame)

        self._next_deadline += self._frame_interval
        delay = self._next_deadline - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    # ------------------------------------------------------------------ #
    #  Clip playback
    # ------------------------------------------------------------------ #

    def stream_file(self, path: Path) -> None:
        """Decode a clip and feed its frames into the persistent pipe."""
        log.info("Streaming file: %s", path.name)
        if self._streaming_params.realtime_streaming:
            self._stream_file_realtime(path)
        else:
            frames = self._decode_from_offset(path, 0.0)
            log.info("Finished streaming: %s (%d frames)", path.name, frames)
        # Clip pacing came from the decoder's -re, not our idle schedule
        self._next_deadline = None

    def _decode_from_offset(self, path: Path, offset_seconds: float) -> int:
        """Run the decoder from offset_seconds; return number of complete frames decoded."""
        w = self._config.stream_width
        h = self._config.stream_height
        fps = self._config.stream_fps

        seek_args = [] if offset_seconds == 0.0 else ["-ss", f"{offset_seconds:.3f}"]

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-re",
            *seek_args,
            "-i", str(path),
            "-vf", (
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                f"fps={fps},"
                f"format=yuv420p"
            ),
            "-f", "rawvideo",
            "-pixel_format", "yuv420p",
            "pipe:1",
        ]

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE
        )

        # Drain stderr concurrently: a chatty decode (corrupt/partial file)
        # fills the 64 KiB stderr pipe, which would block FFmpeg and deadlock
        # the frame-read loop below if stderr were only read after wait().
        stderr_lines: list[str] = []

        def _drain(pipe) -> None:
            for raw in pipe:
                if len(stderr_lines) < 50:  # cap memory on very chatty decodes
                    stderr_lines.append(raw.decode(errors="replace").rstrip())

        threading.Thread(
            target=_drain, args=(proc.stderr,), daemon=True, name="decoder-stderr"
        ).start()

        # Read into one preallocated buffer instead of allocating a fresh
        # ~5.3 MiB bytes object per frame. readinto() may return short reads
        # mid-stream (unlike .read(n)), so top up until the frame is complete
        # — frame alignment is what keeps the output stream uncorrupted.
        buf = bytearray(self._frame_size)
        view = memoryview(buf)

        frames = 0
        aborted = False
        while True:
            if self._shutdown.is_set() or self._encoder_dead:
                aborted = True
                break
            n = proc.stdout.readinto(view)
            while 0 < n < self._frame_size:
                more = proc.stdout.readinto(view[n:])
                if not more:
                    break
                n += more
            if n < self._frame_size:
                break  # EOF / partial frame — discard
            if not self._write_to_pipe(view):
                aborted = True
                break
            frames += 1

        if aborted:
            log.info("Aborting decode of %s (shutdown or encoder restart)", path.name)
            proc.kill()
        proc.wait()

        if proc.returncode != 0 and stderr_lines and not aborted:
            log.warning(
                "Decoder exited %d for %s: %s",
                proc.returncode, path.name, " | ".join(stderr_lines),
            )

        return frames

    def _stream_file_realtime(self, path: Path) -> None:
        """Realtime mode: decode, then resume if the file grew while decoding."""
        offset_seconds = 0.0
        size_before = 0

        while True:
            frames = self._decode_from_offset(path, offset_seconds)

            if self._shutdown.is_set() or self._encoder_dead:
                break

            try:
                size_after = path.stat().st_size
            except FileNotFoundError:
                break

            if size_after <= size_before:
                break  # file has not grown — nothing more to decode

            if frames == 0:
                # No frames yet (e.g. moov atom not written) — wait before retrying
                log.debug("Realtime: no frames decoded for %s yet, waiting for more data", path.name)
                time.sleep(0.5)
            else:
                offset_seconds += frames / self._config.stream_fps
                log.info("Realtime: file grew to %d bytes, resuming %s from %.1fs",
                         size_after, path.name, offset_seconds)

            size_before = size_after

        log.info("Finished realtime streaming: %s", path.name)

    # ------------------------------------------------------------------ #
    #  Internals
    # ------------------------------------------------------------------ #

    def _write_to_pipe(self, data: bytes | memoryview) -> bool:
        """Write all bytes to the pipe, handling partial writes.

        Returns False (and marks the encoder dead) instead of raising if the
        encoder has gone away — the main loop restarts the pipeline.
        """
        if self._encoder_dead:
            return False
        view = memoryview(data)
        offset = 0
        try:
            while offset < len(view):
                written = os.write(self._write_fd, view[offset:])
                offset += written
        except (BrokenPipeError, OSError) as e:
            log.error("Pipe write failed (%s) — output encoder appears dead", e)
            self._encoder_dead = True
            return False
        return True
