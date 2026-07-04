# Reo Bridge — Battery Camera to Frigate

[![CI](https://github.com/warren488/reolink-battery-to-frigate/actions/workflows/ci.yml/badge.svg)](https://github.com/warren488/reolink-battery-to-frigate/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A bridge that turns Reolink battery camera motion clips into a continuous RTSP stream for [Frigate NVR](https://frigate.video/).

**The problem:** Frigate expects always-on RTSP streams. Battery cameras can't do that — they sleep to save power and only wake on motion, uploading short clips via FTP.

**The solution:** This bridge watches for uploaded clips and plays them through a single, persistent RTSP stream. When no clips are arriving, the stream stays live with idle frames so Frigate never disconnects.

## How It Works

```
Reolink Camera ──FTP──▶ Watch Dir ──inotify──▶ reo-bridge ──raw YUV──▶ FFmpeg ──RTSP──▶ MediaMTX
                                                                                           │
                                                                                        Frigate
```

A single output FFmpeg process reads raw video from an OS pipe and encodes it to H264 RTSP. Two sources write to the pipe:

- **Idle** — Python writes pre-generated solid-colour frames at the target FPS
- **Clip** — A temporary decoder FFmpeg outputs raw frames which Python reads and forwards

The output FFmpeg never restarts, so the RTSP connection stays up through all transitions.

<!-- Screenshot placeholder: add docs/images/web-ui.png (the Stream Tuner page) and
     uncomment before publishing:
![Stream Tuner web UI](docs/images/web-ui.png)
-->

## Limitations — read this first

- **Footage is delayed, not live.** A clip must be recorded, uploaded via FTP, and
  settle before it plays — everything you see is typically 30 seconds to a few
  minutes old. Frigate will detect and record events fine, but its **timestamps
  reflect playback time, not when the event actually happened**. This is a review
  pipeline, not live monitoring.
- **Standard MP4 uploads can't stream mid-upload.** The MP4 index (`moov`) is
  written last, so the experimental realtime mode only helps cameras that upload
  fragmented MP4 or FLV.
- **No camera audio.** The stream carries a silent audio track; clip audio is not
  passed through (planned idea, non-trivial).
- **Clips play at 1× speed.** If many events arrive at once, the queue drains in
  real time and the stream falls further behind reality (the web UI shows queue
  depth).

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/warren488/reolink-battery-to-frigate.git
cd reolink-battery-to-frigate

cp .env.example .env
```

Edit `.env` and set `FTP_PUBLIC_HOST` to this machine's LAN IP:

```env
FTP_PUBLIC_HOST=192.168.1.100
FTP_USER=reolink
FTP_PASS=reolink
```

### 2. Start the stack

```bash
docker compose up -d --build
```

This launches three containers:

| Service | Purpose | Host Port |
|---------|---------|-----------|
| **mediamtx** | RTSP server | `8654` (RTSP), `1945` (RTMP), `8889` (HLS/WebRTC) |
| **reo-bridge** | Clip watcher + stream encoder | `5001` (Web UI) |
| **ftp** | Receives uploads from cameras | `21`, `30000-30009` (passive) |

### 3. Configure your Reolink camera

In the Reolink app or web UI, go to **Settings → Surveillance → FTP**:

| Setting | Value |
|---------|-------|
| FTP Server | This machine's IP |
| Port | `21` |
| Username | Value of `FTP_USER` (default: `reolink`) |
| Password | Value of `FTP_PASS` (default: `reolink`) |

Enable **FTP upload on motion events**.

### 4. Configure Frigate

Add the camera to your Frigate config:

```yaml
cameras:
  reolink_battery:
    ffmpeg:
      inputs:
        - path: rtsp://<bridge-host>:8654/camera
          roles:
            - detect
            - record
    detect:
      width: 2560
      height: 1440
      fps: 20
```

> **Tip:** running `detect` at full 2560×1440@20 is heavy. Most setups should let
> this stream feed `record` at full resolution and give `detect` a reduced
> resolution/fps (see Frigate's docs on detect settings) — motion detection does
> not need 2K.

## Web UI — Stream Tuner

Open `http://<bridge-host>:5001` to tune encoder settings in real time. This helps you find the right balance between stream quality and CPU/bandwidth usage.

The page shows a **live status card** (idle/streaming, current clip, queue depth, encoder health, uptime — via `GET /api/status`) and an on-demand **live preview** of the output stream using MediaMTX's built-in HLS player, so you can see the effect of encoder changes without leaving the page.

Adjustable parameters:

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| Rate mode | CBR / CRF | CBR | Constant bitrate vs. constant quality |
| Bitrate | 200–10,000 kbps | 4500 kbps | Target bitrate (CBR) or max-bitrate cap (CRF) |
| CRF | 0–51 | 23 | Quality level (CRF mode, lower = better) |
| Preset | ultrafast → veryslow | ultrafast | Encoding speed vs. compression tradeoff |
| Tune | none, zerolatency, etc. | none | Content-type optimization (`none` = best quality per bit) |
| GOP | 1–300 frames | 40 | Keyframe interval |
| Audio bitrate | 32–320 kbps | 64 kbps | AAC audio quality |

Clicking **Apply** restarts the encoder with the new settings (~1-2 second stream interruption). Applied settings are saved to `./data/params.json` and survive container restarts.

## Configuration

All settings are controlled via environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `STREAM_WIDTH` | `2560` | Output stream width (should match your camera) |
| `STREAM_HEIGHT` | `1440` | Output stream height |
| `STREAM_FPS` | `20` | Output stream frame rate |
| `SETTLE_SECONDS` | `2.0` | Seconds to wait for a file to stop growing before streaming |
| `DELETE_AFTER_STREAM` | `false` | After playing a clip: delete it, delete camera snapshot (`.jpg`) files in the same folder, and prune empty date folders |
| `RTSP_OUTPUT_URL` | `rtsp://mediamtx:8554/camera`¹ | Internal RTSP push target |
| `WEB_PORT` | `5001` | Web UI port |
| `PARAMS_FILE` | `/data/params.json` | Where web-UI tuned settings are persisted |

¹ Value set in `docker-compose.yml`. The application's built-in default is `rtsp://localhost:8554/camera` (for running outside Docker).

FTP settings are in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `FTP_PUBLIC_HOST` | `localhost` | This machine's LAN IP (for passive FTP) |
| `FTP_USER` | `reolink` | FTP username |
| `FTP_PASS` | `reolink` | FTP password |

## Security Notes

This stack is designed for a **trusted home LAN**. Before deploying, know what's exposed:

- **FTP is cleartext.** Reolink battery cameras only speak plain FTP, so credentials
  and footage cross your network unencrypted. Change `FTP_USER`/`FTP_PASS` from the
  defaults, and ideally put cameras on their own VLAN.
- **The web UI (port 5001) has no authentication.** Anyone who can reach the host can
  change encoder settings. Docker publishes it on all interfaces and **bypasses
  ufw/firewalld**. To restrict it to the local machine, change the port mapping to
  `127.0.0.1:5001:5001` in `docker-compose.yml`.
- **MediaMTX accepts any publisher/reader by default.** On a hostile LAN someone could
  read the stream or publish over it. Restrict it with a custom `mediamtx.yml`
  (publisher IP allowlist or credentials) if that matters in your environment.
- **Never port-forward any of these to the internet.** If you need remote access, use
  a VPN (WireGuard/Tailscale).

## Verifying It Works

**Check the stream in VLC:**
```
vlc rtsp://<bridge-host>:8654/camera
```

**Send a test clip** (generates a 5-second synthetic video and uploads it via FTP):
```bash
./scripts/test-upload.sh
```

**Watch the logs:**
```bash
docker compose logs -f reo-bridge
```

**Test FTP manually:**
```bash
curl -T video.mp4 ftp://reolink:reolink@localhost/
```

## Project Structure

```
src/reo_bridge/
├── config.py          # Settings via environment variables
├── encoder_params.py  # Mutable encoder settings (for web UI)
├── streaming_params.py # Mutable streaming settings (realtime mode)
├── main.py            # Entry point + main event loop
├── stream.py          # Pipe-based FFmpeg pipeline
├── watcher.py         # Folder monitoring (inotify)
└── web.py             # Web UI (Flask)
scripts/
└── test-upload.sh     # Test clip generator
docs/
├── ARCHITECTURE.md    # Detailed architecture and design decisions
├── PROGRESS.md        # Development progress tracker
└── SETUP.md           # Detailed setup instructions
```

## Commands

```bash
docker compose up -d --build    # Build and start
docker compose logs -f reo-bridge  # View bridge logs
docker compose down             # Stop everything
./scripts/test-upload.sh        # Test with a synthetic clip
```
