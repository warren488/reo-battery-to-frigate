"""Entry point — ties the folder watcher and stream manager together."""

import logging
import os
import signal

from .config import Config
from .encoder_params import EncoderParams
from .stream import StreamManager
from .watcher import FolderWatcher
from .web import start_in_background

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = Config()
    encoder_params = EncoderParams(
        gop_frames=config.stream_fps * 2,  # default GOP = 2 seconds
    )

    log.info("Config: watch_dir=%s  rtsp=%s  resolution=%dx%d@%dfps",
             config.watch_dir, config.rtsp_output_url,
             config.stream_width, config.stream_height, config.stream_fps)

    watcher = FolderWatcher(config)
    streamer = StreamManager(config, encoder_params)

    # Graceful shutdown on SIGINT / SIGTERM
    shutdown = False

    def _handle_signal(signum, _frame):
        nonlocal shutdown
        log.info("Received signal %s — shutting down", signal.Signals(signum).name)
        shutdown = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Start the web UI
    web_port = int(os.environ.get("WEB_PORT", "5000"))
    start_in_background(config, encoder_params, port=web_port)

    # Start the persistent pipeline and folder watcher
    watcher.start()
    streamer.start()

    log.info("Bridge is running. Waiting for video files in %s ...", config.watch_dir)

    try:
        while not shutdown:
            # Check if encoder params were changed via the web UI
            if streamer.needs_restart():
                streamer.restart()

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
