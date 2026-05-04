# Progress Tracker

## Phase 1: Initial Project Setup - COMPLETE

**Date:** 2026-03-12

### What was done

- [x] Created project structure with Python package (`src/reo_bridge/`)
- [x] Built core components:
  - `config.py` — All settings via environment variables (watch dir, resolution, RTSP URL, etc.)
  - `watcher.py` — Monitors the FTP upload folder using `watchdog` (inotify). Detects new files, waits for them to finish writing, then queues them.
  - `stream.py` — Manages FFmpeg processes. Generates a black stream when idle, plays clips when available, handles graceful process switching.
  - `main.py` — Ties it all together in an event loop with clean shutdown handling.
- [x] Created `Dockerfile` (Python 3.12 + FFmpeg)
- [x] Created `docker-compose.yml` with:
  - **MediaMTX** container (RTSP server on port 8554)
  - **reo-bridge** container (the Python app)
  - Volume mount for the watch directory
- [x] Created architecture documentation
- [x] Initialized git repository

### How it works (simplified)

1. Start with `docker compose up`
2. Bridge launches and starts pushing a black video stream to MediaMTX
3. Point Frigate at `rtsp://<host>:8554/camera`
4. When a video file appears in `./watch_dir/`, the bridge plays it through the stream
5. After the clip finishes, it goes back to black

## Phase 1.5: Pipe-Based Stream Architecture — COMPLETE

**Date:** 2026-03-12

### Problem

The original design used separate FFmpeg processes for idle and clip streaming, each pushing directly to RTSP. When switching between them, the RTSP stream dropped momentarily, causing VLC and Frigate to disconnect.

### Solution

Rewrote `stream.py` with a **pipe-based architecture**:

- [x] Single persistent output FFmpeg reads raw YUV420P from an OS pipe → encodes to H264 → pushes RTSP. Never restarts.
- [x] Idle mode: Python writes pre-generated blue/red frames directly to the pipe at target FPS
- [x] Clip mode: temporary decoder FFmpeg outputs raw frames → Python reads exact frame-sized chunks → writes to pipe
- [x] No stream interruption during idle↔clip transitions
- [x] Updated `main.py` to a tight event loop (check for file → write idle frame → repeat)
- [x] Updated architecture documentation

## Phase 2: Integrated FTP Server — COMPLETE

**Date:** 2026-03-15

### What was done

- [x] Added **Pure-FTPd** container to `docker-compose.yml`
- [x] FTP server and reo-bridge share a named Docker volume (`watch_data`) — uploads land directly in the watched directory
- [x] FTP credentials configurable via `.env` file (`FTP_USER`, `FTP_PASS`, `FTP_PUBLIC_HOST`)
- [x] Passive mode ports exposed (30000-30009) for NAT/firewall compatibility
- [x] Created `.env.example` with documented defaults
- [x] Updated `docs/SETUP.md` with Reolink camera FTP configuration instructions
- [x] Switched from bind mount (`./watch_dir`) to named Docker volume for shared data

## Phase 2.5: Web UI — Stream Tuner — COMPLETE

**Date:** 2026-03-18

### Problem

Finding the right balance between stream quality and performance required manually editing environment variables and rebuilding. No way to experiment with encoder settings in real time.

### Solution

Added a **Flask-based web UI** (port 5000) for live encoder tuning:

- [x] Created `encoder_params.py` — Thread-safe mutable encoder settings (bitrate, CRF, preset, tune, GOP, audio bitrate) with versioning to detect changes
- [x] Created `web.py` — Flask app with inline HTML/CSS/JS serving a single-page tuner UI
  - Dark-themed responsive UI with sliders and dropdowns
  - Toggle between CBR (bitrate) and CRF (quality) rate-control modes
  - Shows current stream info (resolution, FPS, RTSP URL)
  - JSON API: `GET/POST /api/encoder`, `GET /api/config`, `GET /api/options`
  - Input validation with error feedback
- [x] Updated `stream.py` — `StreamManager` now accepts `EncoderParams`, supports `restart()` and `needs_restart()` for controlled pipeline restarts when settings change
- [x] Updated `main.py` — Starts web server in a daemon thread; main loop checks for encoder param changes and triggers restarts
- [x] Added `flask>=3.0` dependency to `pyproject.toml`
- [x] Exposed port 5000 in `docker-compose.yml` with configurable `WEB_PORT` env var

### Tunable parameters

| Parameter | Range | Default | Notes |
|-----------|-------|---------|-------|
| Rate mode | CBR / CRF | CBR | Toggle between constant bitrate and constant quality |
| Bitrate | 200–10,000 kbps | 1500 kbps | Used in CBR mode |
| CRF | 0–51 | 23 | Used in CRF mode (lower = better quality) |
| Preset | ultrafast → veryslow | ultrafast | Speed/quality tradeoff |
| Tune | zerolatency, film, etc. | zerolatency | Content-type optimization |
| GOP size | 1–300 frames | fps×2 | Keyframe interval |
| Audio bitrate | 32–320 kbps | 64 kbps | AAC audio quality |

### What's next

- [ ] **Phase 3: Testing** — Test end-to-end with real Reolink camera uploads, verify Frigate integration
- [ ] **Phase 4: Multi-camera support** — Support multiple Reolink cameras with separate streams
- [ ] **Phase 5: Hardening** — Error recovery, logging improvements, health checks

## Phase 2.6: Realtime Streaming Toggle (Experimental) — COMPLETE

**Date:** 2026-05-01

### Problem

With the default settle-based flow, streaming doesn't begin until the entire FTP upload finishes plus the settle delay. For users who want to observe stream latency or experiment with partial-file decoding, there was no way to try starting the stream mid-upload.

### Solution

Added an experimental `REALTIME_STREAMING` toggle (default `false`):

- [x] `config.py` — Added `realtime_streaming: bool` and `realtime_delay_seconds: float` (default 5.0s)
- [x] `watcher.py` — When realtime mode is on, `_wait_delay_and_enqueue` queues the file after a fixed delay instead of waiting for size to stabilise
- [x] `stream.py` — Refactored `stream_file` into `_decode_from_offset(path, offset_seconds) -> int` (core decoder) and `_stream_file_realtime` (resume loop). In realtime mode, after FFmpeg exits the resume loop re-runs the decoder from the last offset if the file has grown.
- [x] `docker-compose.yml` — Documented new env vars as comments

### Known limitations

- **Standard MP4 (moov at EOF)** — FFmpeg cannot decode frames until the `moov` atom is written (at the end of the file). Realtime mode will show idle frames until the upload completes, then decode the full clip from offset 0. Cameras writing **fragmented MP4** or **FLV** clips will benefit most.
- **Keyframe alignment on resume** — The `-ss` seek used for resume aligns to the nearest keyframe, so a few frames around the resume boundary may be dropped or duplicated.
- **Busy-wait on empty decode** — If no frames are decoded (moov not yet available), the resume loop retries every 0.5s until the file stops growing.
