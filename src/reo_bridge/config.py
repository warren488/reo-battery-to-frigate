"""Configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    # Directory where Reolink cameras upload files via FTP
    watch_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("WATCH_DIR", "/watch"))
    )

    # RTSP output URL (where MediaMTX expects the stream to be pushed)
    rtsp_output_url: str = os.environ.get(
        "RTSP_OUTPUT_URL", "rtsp://localhost:8554/camera"
    )

    # Stream resolution — should match your Reolink camera output
    stream_width: int = int(os.environ.get("STREAM_WIDTH", "2560"))
    stream_height: int = int(os.environ.get("STREAM_HEIGHT", "1440"))
    stream_fps: int = int(os.environ.get("STREAM_FPS", "20"))

    # How many seconds of black to hold after a clip ends before checking
    # for the next file (gives FTP time to finish writing)
    settle_seconds: float = float(os.environ.get("SETTLE_SECONDS", "2.0"))

    # Video file extensions to watch for
    video_extensions: tuple[str, ...] = (".mp4", ".avi", ".mkv", ".flv")

    # Whether to delete files after they have been streamed
    delete_after_stream: bool = os.environ.get(
        "DELETE_AFTER_STREAM", "false"
    ).lower() in ("true", "1", "yes")
