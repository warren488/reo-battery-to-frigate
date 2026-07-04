"""Thread-safe runtime status shared between the bridge and the web UI."""

import threading
import time
from collections.abc import Callable


class BridgeStatus:
    """What the bridge is doing right now, for /api/status.

    Live values that already exist elsewhere (queue depth, encoder health)
    are read through provider callables so this class holds no duplicate
    state that could go stale.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._state = "idle"
        self._current_file: str | None = None
        self._last_clip: dict | None = None
        self._queue_depth: Callable[[], int] = lambda: 0
        self._encoder_alive: Callable[[], bool] = lambda: False

    def set_providers(
        self,
        queue_depth: Callable[[], int],
        encoder_alive: Callable[[], bool],
    ) -> None:
        self._queue_depth = queue_depth
        self._encoder_alive = encoder_alive

    def clip_started(self, name: str) -> None:
        with self._lock:
            self._state = "streaming"
            self._current_file = name

    def clip_finished(self, name: str, frames: int) -> None:
        with self._lock:
            self._state = "idle"
            self._current_file = None
            self._last_clip = {
                "name": name,
                "frames": frames,
                "finished_at": time.time(),
            }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "current_file": self._current_file,
                "last_clip": self._last_clip,
                "queue_depth": self._queue_depth(),
                "encoder_alive": self._encoder_alive(),
                "uptime_seconds": round(time.time() - self._started_at, 1),
            }
