"""Entry point — ties the folder watcher and stream manager together."""

import logging
import os
import signal

from .config import Config
from .encoder_params import EncoderParams
from .persistence import load_params
from .stream import StreamManager
from .streaming_params import StreamingParams
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
    streaming_params = StreamingParams(
        realtime_streaming=config.realtime_streaming,
        realtime_delay_seconds=config.realtime_delay_seconds,
    )

    # Restore parameters tuned via the web UI in a previous run (fail-soft:
    # a stale or corrupt file must never prevent startup)
    saved = load_params(config.params_file)
    if saved:
        try:
            enc = {k: v for k, v in saved.get("encoder", {}).items() if k != "version"}
            if enc:
                encoder_params.update(**enc)
            if saved.get("streaming"):
                streaming_params.update(**saved["streaming"])
            log.info("Restored saved params from %s", config.params_file)
        except (ValueError, TypeError) as e:
            log.warning("Ignoring invalid saved params in %s: %s", config.params_file, e)

    log.info("Config: watch_dir=%s  rtsp=%s  resolution=%dx%d@%dfps",
             config.watch_dir, config.rtsp_output_url,
             config.stream_width, config.stream_height, config.stream_fps)

    watcher = FolderWatcher(config, streaming_params)
    streamer = StreamManager(config, encoder_params, streaming_params)

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
    start_in_background(config, encoder_params, streaming_params, port=web_port)

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
