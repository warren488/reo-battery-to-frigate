"""Integration: the clip decoder must emit exact frame-sized chunks.

The whole pipe architecture rests on one invariant: only complete
width*height*1.5-byte frames ever reach the output pipe. This test runs the
real decoder FFmpeg against a generated clip and byte-counts the result.

Requires ffmpeg on PATH (skipped otherwise).
"""

import os
import shutil
import subprocess
import threading

import pytest

from reo_bridge.config import Config
from reo_bridge.encoder_params import EncoderParams
from reo_bridge.stream import StreamManager
from reo_bridge.streaming_params import StreamingParams

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)

WIDTH, HEIGHT, FPS = 64, 48, 10
FRAME_SIZE = WIDTH * HEIGHT * 3 // 2


@pytest.fixture
def small_config(monkeypatch):
    monkeypatch.setenv("STREAM_WIDTH", str(WIDTH))
    monkeypatch.setenv("STREAM_HEIGHT", str(HEIGHT))
    monkeypatch.setenv("STREAM_FPS", str(FPS))
    return Config()


def _make_clip(path, seconds=1):
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=128x96:rate={FPS}:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-y", str(path),
        ],
        check=True,
    )


def test_decode_emits_whole_frames_only(small_config, tmp_path):
    clip = tmp_path / "clip.mp4"
    _make_clip(clip)

    manager = StreamManager(small_config, EncoderParams(), StreamingParams())

    # White-box: give the manager a pipe we control instead of an encoder
    read_fd, write_fd = os.pipe()
    manager._write_fd = write_fd

    received = bytearray()

    def _drain():
        while True:
            chunk = os.read(read_fd, 65536)
            if not chunk:
                break
            received.extend(chunk)

    reader = threading.Thread(target=_drain)
    reader.start()

    frames = manager._decode_from_offset(clip, 0.0)

    os.close(write_fd)
    reader.join(timeout=10)
    os.close(read_fd)

    # 1 second at 10 fps → 10 frames (allow ±1 for fps-filter edge rounding)
    assert 9 <= frames <= 11
    # The invariant: the pipe saw exactly whole frames, nothing partial
    assert len(received) == frames * FRAME_SIZE


def test_decode_of_garbage_returns_zero_frames(small_config, tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"this is not a video" * 1000)

    manager = StreamManager(small_config, EncoderParams(), StreamingParams())
    read_fd, write_fd = os.pipe()
    manager._write_fd = write_fd

    frames = manager._decode_from_offset(junk, 0.0)

    os.close(write_fd)
    os.close(read_fd)
    assert frames == 0
