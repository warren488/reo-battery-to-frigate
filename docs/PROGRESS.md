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

### What's next

- [ ] **Phase 3: Testing** — Test end-to-end with real Reolink camera uploads, verify Frigate integration
- [ ] **Phase 4: Multi-camera support** — Support multiple Reolink cameras with separate streams
- [ ] **Phase 5: Hardening** — Error recovery, logging improvements, health checks
