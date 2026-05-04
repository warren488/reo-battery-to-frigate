"""Thread-safe mutable streaming parameters, adjustable at runtime via the web UI."""

import threading
from dataclasses import dataclass


@dataclass
class StreamingParams:
    """Mutable streaming settings shared between the web UI, watcher, and stream manager."""

    # Experimental: queue files after a short fixed delay instead of waiting for
    # the full upload to finish. Works best with fragmented MP4 or FLV; standard
    # MP4 (moov at EOF) won't decode early regardless.
    realtime_streaming: bool = False
    realtime_delay_seconds: float = 5.0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def update(self, **kwargs) -> None:
        """Update one or more parameters atomically."""
        with self._lock:
            for key, value in kwargs.items():
                if not hasattr(self, key) or key.startswith("_"):
                    raise ValueError(f"Unknown streaming param: {key}")
                setattr(self, key, value)

    def snapshot(self) -> dict:
        """Return a plain dict of current values (for JSON serialization)."""
        with self._lock:
            return {
                "realtime_streaming": self.realtime_streaming,
                "realtime_delay_seconds": self.realtime_delay_seconds,
            }
