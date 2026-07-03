"""Configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class Config:
    # Directory where Reolink cameras upload files via FTP
    watch_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("WATCH_DIR", "/watch"))
    )

    # RTSP output URL (where MediaMTX expects the stream to be pushed)
    rtsp_output_url: str = field(
        default_factory=lambda: os.environ.get(
            "RTSP_OUTPUT_URL", "rtsp://localhost:8554/camera"
        )
    )

    # Stream resolution — should match your Reolink camera output
    stream_width: int = field(default_factory=lambda: _env_int("STREAM_WIDTH", 2560))
    stream_height: int = field(default_factory=lambda: _env_int("STREAM_HEIGHT", 1440))
    stream_fps: int = field(default_factory=lambda: _env_int("STREAM_FPS", 20))

    # How many seconds a file's size must hold steady before it is
    # considered fully uploaded and queued for streaming
    settle_seconds: float = field(
        default_factory=lambda: _env_float("SETTLE_SECONDS", 2.0)
    )

    # Video file extensions to watch for
    video_extensions: tuple[str, ...] = (".mp4", ".avi", ".mkv", ".flv")

    # Whether to delete files after they have been streamed
    delete_after_stream: bool = field(
        default_factory=lambda: _env_bool("DELETE_AFTER_STREAM", False)
    )

    # Experimental: queue files after a short fixed delay instead of waiting for
    # the full upload to finish. FFmpeg may hit EOF early for standard MP4s
    # (moov atom is typically at EOF; fragmented/FLV formats work best).
    realtime_streaming: bool = field(
        default_factory=lambda: _env_bool("REALTIME_STREAMING", False)
    )

    # Seconds to wait after file creation before queueing in realtime mode.
    realtime_delay_seconds: float = field(
        default_factory=lambda: _env_float("REALTIME_DELAY_SECONDS", 5.0)
    )

    # Where web-UI tuned parameters are persisted across restarts
    params_file: Path = field(
        default_factory=lambda: Path(os.environ.get("PARAMS_FILE", "/data/params.json"))
    )

    def __post_init__(self) -> None:
        if self.stream_width <= 0 or self.stream_height <= 0:
            raise ValueError(
                f"STREAM_WIDTH/STREAM_HEIGHT must be positive, "
                f"got {self.stream_width}x{self.stream_height}"
            )
        if self.stream_width % 2 or self.stream_height % 2:
            raise ValueError(
                f"STREAM_WIDTH and STREAM_HEIGHT must be even (YUV420P requirement), "
                f"got {self.stream_width}x{self.stream_height}"
            )
        if self.stream_fps <= 0:
            raise ValueError(f"STREAM_FPS must be positive, got {self.stream_fps}")
        if self.settle_seconds < 0:
            raise ValueError(
                f"SETTLE_SECONDS must not be negative, got {self.settle_seconds}"
            )
        if self.realtime_delay_seconds < 0:
            raise ValueError(
                f"REALTIME_DELAY_SECONDS must not be negative, "
                f"got {self.realtime_delay_seconds}"
            )
