"""Manages the persistent RTSP stream via a pipe-based architecture.

A single output FFmpeg reads raw video from a pipe and encodes to RTSP.
Idle frames (black) and clip frames are written to the same pipe,
so the RTSP stream never drops during switchovers.
"""

import logging
import os
import signal
import subprocess
import time
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)


def _yuv420p_solid(width: int, height: int, y: int, u: int, v: int) -> bytes:
    """Generate a single solid-colour YUV420P frame."""
    y_plane = bytes([y]) * (width * height)
    u_plane = bytes([u]) * (width * height // 4)
    v_plane = bytes([v]) * (width * height // 4)
    return y_plane + u_plane + v_plane


class StreamManager:
    """Pipe-fed RTSP stream that seamlessly switches between idle and clip playback."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._output_proc: subprocess.Popen | None = None
        self._write_fd: int | None = None

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
        read_fd, self._write_fd = os.pipe()

        w = self._config.stream_width
        h = self._config.stream_height
        fps = self._config.stream_fps

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
            # Encode
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-b:v", "1500k",
            "-g", str(fps * 2),
            "-c:a", "aac",
            "-b:a", "64k",
            # Output to RTSP
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            self._config.rtsp_output_url,
        ]

        log.info("Starting output pipeline → %s", self._config.rtsp_output_url)
        self._output_proc = subprocess.Popen(
            cmd, stdin=read_fd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        os.close(read_fd)  # only the output FFmpeg needs the read end

    def stop(self) -> None:
        """Shut down the output pipeline."""
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

    # ------------------------------------------------------------------ #
    #  Idle frames (called from the main loop)
    # ------------------------------------------------------------------ #

    def write_idle_frame(self) -> None:
        """Write one black idle frame and sleep for one frame interval."""
        start = time.monotonic()
        self._write_to_pipe(self._black_frame)

        # Rate-limit to target FPS
        elapsed = time.monotonic() - start
        sleep_time = self._frame_interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    # ------------------------------------------------------------------ #
    #  Clip playback
    # ------------------------------------------------------------------ #

    def stream_file(self, path: Path) -> None:
        """Decode a clip and feed its frames into the persistent pipe."""
        w = self._config.stream_width
        h = self._config.stream_height
        fps = self._config.stream_fps

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-re",  # play at native speed
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

        log.info("Streaming file: %s", path.name)
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE
        )

        # Read complete frames from the decoder and write them to the pipe
        while True:
            data = proc.stdout.read(self._frame_size)
            if len(data) < self._frame_size:
                break  # EOF or partial frame at the end — discard
            self._write_to_pipe(data)

        proc.wait()

        stderr_out = proc.stderr.read().decode(errors="replace").strip()
        if proc.returncode != 0 and stderr_out:
            log.error("FFmpeg exited %d for %s: %s", proc.returncode, path.name, stderr_out)
        else:
            log.info("Finished streaming: %s", path.name)

    # ------------------------------------------------------------------ #
    #  Internals
    # ------------------------------------------------------------------ #

    def _write_to_pipe(self, data: bytes) -> None:
        """Write all bytes to the pipe, handling partial writes."""
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            written = os.write(self._write_fd, view[offset:])
            offset += written
