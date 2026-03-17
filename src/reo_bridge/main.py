"""Entry point — ties the folder watcher and stream manager together."""

import logging
import signal

from .config import Config
from .stream import StreamManager
from .watcher import FolderWatcher

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = Config()
    log.info("Config: watch_dir=%s  rtsp=%s  resolution=%dx%d@%dfps",
             config.watch_dir, config.rtsp_output_url,
             config.stream_width, config.stream_height, config.stream_fps)

    watcher = FolderWatcher(config)
    streamer = StreamManager(config)

    # Graceful shutdown on SIGINT / SIGTERM
    shutdown = False

    def _handle_signal(signum, _frame):
        nonlocal shutdown
        log.info("Received signal %s — shutting down", signal.Signals(signum).name)
        shutdown = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Start the persistent pipeline and folder watcher
    watcher.start()
    streamer.start()

    log.info("Bridge is running. Waiting for video files in %s ...", config.watch_dir)

    try:
        while not shutdown:
            # Check for a new file (non-blocking)
            path = watcher.next_file(timeout=0)

            if path is not None:
                # Play the clip through the persistent stream
                streamer.stream_file(path)

                if config.delete_after_stream:
                    log.info("Deleting streamed file: %s", path.name)
                    path.unlink(missing_ok=True)
            else:
                # No clip — write one idle frame (includes rate-limiting sleep)
                streamer.write_idle_frame()
    finally:
        log.info("Cleaning up ...")
        watcher.stop()
        streamer.stop()
        log.info("Goodbye.")


if __name__ == "__main__":
    main()
