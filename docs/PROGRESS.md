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
- [x] Idle mode: Python writes a pre-generated solid black frame directly to the pipe at target FPS
- [x] Clip mode: temporary decoder FFmpeg outputs raw frames → Python reads exact frame-sized chunks → writes to pipe
- [x] No stream interruption during idle↔clip transitions
- [x] Updated `main.py` to a tight event loop (check for file → write idle frame → repeat)
- [x] Updated architecture documentation

## Phase 2: Integrated FTP Server — COMPLETE

**Date:** 2026-03-15

### What was done

- [x] Added **Pure-FTPd** container to `docker-compose.yml`
- [x] FTP server and reo-bridge share the `./watch_dir` bind mount — uploads land directly in the watched directory
- [x] FTP credentials configurable via `.env` file (`FTP_USER`, `FTP_PASS`, `FTP_PUBLIC_HOST`)
- [x] Passive mode ports exposed (30000-30009) for NAT/firewall compatibility
- [x] Created `.env.example` with documented defaults
- [x] Updated `docs/SETUP.md` with Reolink camera FTP configuration instructions

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

## Review: Efficiency & Artifacting Report — COMPLETE

**Date:** 2026-06-11

Full-project efficiency review plus diagnosis of the bottom-of-frame motion artifacting.
See `docs/EFFICIENCY_REPORT.md`. Headline findings:

- Artifacting root cause: default 1500 kbps "CBR" (actually ABR — no VBV) at 1440p20
  with `ultrafast` + `zerolatency` starves the encoder during motion; bottom rows get
  crushed quantization. Recommended: 4000–6000 kbps, add `-maxrate`/`-bufsize`, drop
  `zerolatency`.
- Robustness: decoder stderr can deadlock the bridge; encoder death is invisible and
  crashes the main loop; idle pacing drifts (latency grows with uptime).
- No code changes made yet — report only.
- Follow-up: full remediation plan written at `docs/REMEDIATION_PLAN.md` (4 phases:
  stream quality → robustness → performance → housekeeping, with verification gates).

## Review: OSS Readiness Audit — COMPLETE

**Date:** 2026-07-03

Full-repo audit ahead of publishing publicly, covering everything the 2026-06-11
efficiency review didn't: licensing, naming, security posture, Docker/build hygiene,
code quality, testing/CI, documentation accuracy, and web UI/UX. See
`docs/OSS_READINESS_AUDIT.md`. Headline findings:

- **Publish blockers:** no LICENSE file; "batter" typo in the repo/package name; real
  LAN IP committed in `.env.example`; no `.dockerignore` (695 MB of personal footage
  in every build context); encoder defaults still produce artifacting (June Phase 1
  unapplied).
- **All findings from the 2026-06-11 efficiency report verified still open** — no
  remediation has landed yet.
- New findings: SETUP.md points Frigate at the wrong port (8554 vs 8654), `Config`
  reads env at import time (blocks testability), `.jpg` uploads never cleaned up,
  shutdown blocks on in-flight clips, unpinned Docker images, unauthenticated web UI
  published on all interfaces, zero tests/CI.
- UI recommendations: `/api/status` + status card, embed MediaMTX's built-in live
  player (port 8889) for closed-loop tuning, persistence warning.
- No code changes made — audit only. Prioritized launch checklist at the end of the
  audit doc.

## Phase 3: OSS Launch Prep — Checkpoint 1: Publish Blockers & Doc Truth — COMPLETE

**Date:** 2026-07-03

First of six pre-publication checkpoints (plan in `docs/OSS_READINESS_AUDIT.md`):

- [x] Added MIT `LICENSE`; completed `pyproject.toml` metadata (license, readme,
  authors, keywords, classifiers, urls); package renamed to
  `reolink-battery-frigate-bridge` (GitHub repo rename pending — owner action)
- [x] Added `.dockerignore` — camera footage, `.git`, `.env`, and docs no longer enter
  the Docker build context
- [x] `.env.example`: real LAN IP replaced with placeholder; credential warning added
- [x] Fixed `docs/SETUP.md` directing Frigate/VLC to the wrong RTSP port (8554 → 8654)
- [x] Synced all docs with code: black idle frames, `./watch_dir` bind mount, complete
  module listings, chronological ordering of this file

## Phase 3 — Checkpoint 2: Stream Quality (Artifacting Fix) — COMPLETE

**Date:** 2026-07-03

Implements `docs/REMEDIATION_PLAN.md` Phase 1 (root cause of the bottom-of-frame
blocking during motion — see `docs/EFFICIENCY_REPORT.md` Part 1):

- [x] Default bitrate 1500 → **4500 kbps** (`encoder_params.py`)
- [x] **VBV constraints in both rate modes** (`-maxrate`/`-bufsize 2×`): CBR is now
  true CBR instead of unconstrained ABR; CRF is capped CRF with `bitrate_kbps` as the
  ceiling. This smooths in-frame bit allocation — the direct fix for bottom-rows
  quantization collapse.
- [x] Default tune `zerolatency` → **`none`** (no `-tune` flag emitted) — re-enables
  lookahead and normal frame threading; removes sliced-thread banding
- [x] Web UI: bitrate slider now visible in CRF mode as "Max Bitrate"; help text
  updated (bitrate guidance, tune recommendation, persistence note)
- [x] **Settings persistence**: new `persistence.py` (atomic JSON write, fail-soft
  load), `PARAMS_FILE` config (default `/data/params.json`), saved on every web-UI
  apply, restored at startup; `./data:/data` volume added to compose
- [x] README parameter tables re-synced (defaults, persistence, `PARAMS_FILE`)

## Phase 3 — Checkpoint 3: Robustness — COMPLETE

**Date:** 2026-07-03

Implements `docs/REMEDIATION_PLAN.md` Phase 2 plus new audit findings §6.1–6.3:

- [x] **Decoder stderr deadlock fixed** (`stream.py`): stderr drained on a background
  thread (capped at 50 lines) instead of read-after-wait — a chatty decode of a
  corrupt/partial file can no longer stall the whole bridge
- [x] **Encoder supervision**: output FFmpeg stderr now logged (`encoder:` prefix);
  `_write_to_pipe` survives `BrokenPipeError` and flags the encoder dead instead of
  crashing the main loop; main loop self-heals with a 5-second restart backoff
- [x] **Idle pacing drift fixed**: absolute-deadline scheduling with a resync guard
  after startup/clips/stalls — stream latency no longer grows with uptime
- [x] **Watcher handles renames** (`on_moved`): uploads that arrive as
  temp-name-then-rename are no longer silently ignored; 60-second dedupe guard
  prevents double-queueing on create-then-rename sequences
- [x] **Graceful shutdown mid-clip**: SIGTERM/SIGINT now aborts an in-flight decode
  promptly (shared shutdown event), so `docker stop` completes within its grace period
- [x] **Config validation** (`config.py`): env vars read at construction time (was
  import time — testability), errors name the offending variable, dimensions must be
  even (YUV420P), FPS positive
- [x] Verified via failure drills: truncated MP4, encoder process kill, MediaMTX
  restart mid-stream, `mv` into watch dir, `docker stop` during clip, invalid config

## Phase 3 — Checkpoint 4: Performance & Deployment — COMPLETE

**Date:** 2026-07-03

Implements `docs/REMEDIATION_PLAN.md` Phase 3 plus audit §5:

- [x] **Pipe enlarged to 1 MiB** (`F_SETPIPE_SZ`, best-effort): ~16× fewer write
  syscalls per 5.3 MiB frame
- [x] **Frame buffer reuse in the decode loop**: `readinto()` a preallocated
  `bytearray` with a short-read top-up loop (preserves the frame-alignment
  invariant) instead of allocating a fresh ~5.3 MiB `bytes` per frame
- [x] **Dockerfile**: dependency layer split from source layer (source edits no
  longer reinstall Flask/watchdog), `PYTHONUNBUFFERED=1` (logs stream in real time),
  `HEALTHCHECK` against the web API (respects `WEB_PORT`)
- [x] **Images pinned**: `bluenviron/mediamtx:1.16.3`, `stilliard/pure-ftpd` by digest
  (publishes no version tags)
- [x] CPU before/after measured with `docker stats` (idle + during clip); clip
  playback re-verified frame-exact after the buffer change

## Phase 3 — Checkpoint 5: Tests & CI — COMPLETE

**Date:** 2026-07-03

First test suite and continuous integration for the project:

- [x] **45 tests** across six files in `tests/`:
  - `test_config.py` — env parsing, validation (named-variable errors, even
    dimensions, positive fps)
  - `test_encoder_params.py` — FFmpeg args per rate mode (VBV always present, no
    `-tune` for "none"), version bumping, unknown-key rejection
  - `test_persistence.py` — round-trip, corrupt/missing/unwritable files fail soft,
    atomic writes leave no temp files
  - `test_web.py` — all API endpoints via Flask test client: reads, updates,
    validation rejections, persistence wiring
  - `test_watcher.py` — settle detection (incl. a still-growing file), suffix
    filtering, create+rename dedupe, vanished files
  - `test_stream_decode.py` — integration (needs ffmpeg): real decoder run must
    deliver byte-exact whole frames to the pipe — the architecture's core invariant;
    garbage input must yield 0 frames
- [x] **ruff** configured in `pyproject.toml` (defaults + import sorting, bugbear,
  pyupgrade); existing violations fixed
- [x] `dev` extra (`pip install -e ".[dev]"`) with pytest + ruff
- [x] **GitHub Actions** (`.github/workflows/ci.yml`): lint, pytest on 3.11 + 3.12
  (with ffmpeg for integration tests), docker build
- [x] CI + license badges in README
- [x] Full suite verified green both on the host venv and inside the built container
