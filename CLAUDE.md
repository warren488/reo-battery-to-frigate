# CLAUDE.md

## Project Overview

A bridge between Reolink battery cameras and Frigate NVR. Battery cameras upload motion clips via FTP to a watched folder. This app presents those clips as a continuous RTSP stream that Frigate can consume. When idle, the stream shows solid black frames; when a clip arrives, it seamlessly plays through the same stream.

## Architecture

Single persistent FFmpeg reads raw YUV420P frames from an OS pipe and encodes to H264 RTSP. Two sources write to the pipe:
- **Idle**: Python writes pre-generated solid colour frames at target FPS
- **Clip**: A temporary decoder FFmpeg outputs raw frames → Python reads frame-sized chunks → writes to pipe

The RTSP connection never drops during transitions. See `docs/ARCHITECTURE.md` for full details.

## Tech Stack

- **Python 3.12** — orchestration (file watching, frame writing, subprocess management)
- **FFmpeg** — video decoding/encoding (runs inside Docker container)
- **MediaMTX** — lightweight RTSP server (separate Docker container)
- **watchdog** — filesystem monitoring (inotify)
- **Pure-FTPd** — FTP server for camera uploads (separate Docker container)
- **Docker Compose** — deployment (three services: `ftp` + `mediamtx` + `reo-bridge`)

## Project Structure

```
src/reo_bridge/
├── config.py            # All settings via env vars (Config dataclass)
├── encoder_params.py    # Thread-safe mutable encoder settings (tuned via web UI)
├── streaming_params.py  # Thread-safe mutable streaming settings (realtime mode)
├── main.py              # Entry point + main event loop
├── stream.py            # Pipe-based FFmpeg pipeline (StreamManager)
├── watcher.py           # Folder monitoring (FolderWatcher)
└── web.py               # Flask web UI + JSON API for live tuning
scripts/
└── test-upload.sh  # Generates a test clip and uploads it via FTP
docs/
├── ARCHITECTURE.md          # Detailed architecture with diagrams
├── PROGRESS.md              # Phase-by-phase progress tracker
├── SETUP.md                 # End-user setup instructions
├── EFFICIENCY_REPORT.md     # 2026-06-11 efficiency/quality review
├── REMEDIATION_PLAN.md      # Step-by-step fixes for the review findings
└── OSS_READINESS_AUDIT.md   # 2026-07-03 pre-publication audit
```

## Key Files

- `src/reo_bridge/stream.py` — The core. Manages the persistent output FFmpeg, idle frame generation, and clip decoding. Changes here affect stream stability.
- `src/reo_bridge/config.py` — Frozen dataclass, all values from env vars. Add new settings here.
- `docker-compose.yml` — Defines all three services. Environment variables here are the user-facing config.
- `.env` / `.env.example` — FTP credentials and public host IP. Copied from `.env.example` on first setup.

## Commands

```bash
# Build and run
docker compose up -d --build

# View logs
docker compose logs -f reo-bridge

# Test with a sample clip
./scripts/test-upload.sh

# Stop everything
docker compose down
```

## Development Notes

- **Stream continuity is critical.** The output FFmpeg process must never restart during normal operation. All idle↔clip transitions happen by switching what gets written to the pipe.
- **Frame alignment matters.** Raw YUV420P frames are written in exact `width * height * 1.5` byte chunks. Partial frames corrupt the stream. Clip frames are read from the decoder in frame-sized reads; short reads (EOF) are discarded.
- **Resolution consistency.** All frames (idle + clips) must match `STREAM_WIDTH x STREAM_HEIGHT`. Clips are scaled and padded to match.
- **FTP settle time.** Files are not queued until their size stops changing (controlled by `SETTLE_SECONDS`). This prevents reading partially uploaded files.
- **No audio passthrough currently.** The output FFmpeg generates silent audio via `anullsrc`. Clip audio is decoded but not piped through.
- **Always update `docs/PROGRESS.md`** when completing significant work.
