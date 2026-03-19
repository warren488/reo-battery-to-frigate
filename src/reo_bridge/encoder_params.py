"""Thread-safe mutable encoder parameters for the output FFmpeg pipeline.

These can be changed at runtime via the web UI. When updated, the
StreamManager detects the change and restarts the encoder with the
new settings.
"""

import threading
from dataclasses import dataclass, field


# Valid x264 presets (fastest → slowest)
PRESETS = [
    "ultrafast", "superfast", "veryfast", "faster",
    "fast", "medium", "slow", "slower", "veryslow",
]

# Valid x264 tunes
TUNES = ["zerolatency", "film", "animation", "grain", "stillimage", "psnr", "ssim"]

# Rate-control modes
RATE_MODES = ["cbr", "crf"]


@dataclass
class EncoderParams:
    """Mutable encoder settings shared between the web UI and stream manager."""

    # Rate control
    rate_mode: str = "cbr"       # "cbr" or "crf"
    bitrate_kbps: int = 1500     # used when rate_mode == "cbr"
    crf: int = 23                # used when rate_mode == "crf" (0=lossless, 51=worst)

    # x264 settings
    preset: str = "ultrafast"
    tune: str = "zerolatency"
    gop_frames: int = 40         # keyframe interval in frames (default: fps*2)

    # Audio
    audio_bitrate_kbps: int = 64

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._version = 0  # bumped on every change

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def update(self, **kwargs) -> None:
        """Update one or more parameters atomically. Bumps version."""
        with self._lock:
            for key, value in kwargs.items():
                if not hasattr(self, key) or key.startswith("_"):
                    raise ValueError(f"Unknown encoder param: {key}")
                setattr(self, key, value)
            self._version += 1

    def snapshot(self) -> dict:
        """Return a plain dict of current values (for JSON serialization)."""
        with self._lock:
            return {
                "rate_mode": self.rate_mode,
                "bitrate_kbps": self.bitrate_kbps,
                "crf": self.crf,
                "preset": self.preset,
                "tune": self.tune,
                "gop_frames": self.gop_frames,
                "audio_bitrate_kbps": self.audio_bitrate_kbps,
                "version": self._version,
            }

    def ffmpeg_args(self) -> list[str]:
        """Return the FFmpeg encoding flags for the current settings."""
        with self._lock:
            args = [
                "-c:v", "libx264",
                "-preset", self.preset,
                "-tune", self.tune,
                "-g", str(self.gop_frames),
            ]
            if self.rate_mode == "crf":
                args += ["-crf", str(self.crf)]
            else:
                args += ["-b:v", f"{self.bitrate_kbps}k"]

            args += ["-c:a", "aac", "-b:a", f"{self.audio_bitrate_kbps}k"]
            return args
