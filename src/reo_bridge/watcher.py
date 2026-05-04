"""Watches the FTP upload directory for new video files."""

import logging
import queue
import threading
import time
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import Config
from .streaming_params import StreamingParams

log = logging.getLogger(__name__)


class _VideoFileHandler(FileSystemEventHandler):
    """Enqueues newly created video files after they finish writing."""

    def __init__(self, config: Config, file_queue: queue.Queue[Path], streaming_params: StreamingParams) -> None:
        self._config = config
        self._queue = file_queue
        self._streaming_params = streaming_params

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix.lower() not in self._config.video_extensions:
            return

        if self._streaming_params.realtime_streaming:
            log.info("Detected new file: %s — realtime mode, queueing after %.1fs delay",
                     path.name, self._streaming_params.realtime_delay_seconds)
            threading.Thread(
                target=self._wait_delay_and_enqueue, args=(path,), daemon=True
            ).start()
        else:
            log.info("Detected new file: %s — waiting for write to settle", path.name)
            threading.Thread(
                target=self._wait_and_enqueue, args=(path,), daemon=True
            ).start()

    def _wait_and_enqueue(self, path: Path) -> None:
        """Poll file size until it stabilises, then add to queue."""
        prev_size = -1
        while True:
            try:
                current_size = path.stat().st_size
            except FileNotFoundError:
                log.warning("File disappeared before it could be queued: %s", path.name)
                return

            if current_size == prev_size and current_size > 0:
                break
            prev_size = current_size
            time.sleep(self._config.settle_seconds)

        log.info("File ready: %s (%d bytes)", path.name, prev_size)
        self._queue.put(path)

    def _wait_delay_and_enqueue(self, path: Path) -> None:
        """Realtime mode: wait a fixed delay, then queue regardless of upload state."""
        time.sleep(self._streaming_params.realtime_delay_seconds)
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            log.warning("File disappeared before realtime queue: %s", path.name)
            return
        log.info("Realtime: queueing %s (%d bytes, upload may still be in progress)", path.name, size)
        self._queue.put(path)


class FolderWatcher:
    """Monitors a directory and yields video file paths as they arrive."""

    def __init__(self, config: Config, streaming_params: StreamingParams) -> None:
        self._config = config
        self._streaming_params = streaming_params
        self._queue: queue.Queue[Path] = queue.Queue()
        self._observer = Observer()

    def start(self) -> None:
        watch_path = self._config.watch_dir
        watch_path.mkdir(parents=True, exist_ok=True)
        handler = _VideoFileHandler(self._config, self._queue, self._streaming_params)
        self._observer.schedule(handler, str(watch_path), recursive=True)
        self._observer.start()
        log.info("Watching %s for new video files", watch_path)

    def next_file(self, timeout: float = 1.0) -> Path | None:
        """Return the next queued video file, or None after *timeout* seconds."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
