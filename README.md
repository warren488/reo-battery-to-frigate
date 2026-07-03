# Reo Bridge — Battery Camera to Frigate

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

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/warren488/reolink-battery-frigate-bridge.git
cd reolink-battery-frigate-bridge

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

## Web UI — Stream Tuner

Open `http://<bridge-host>:5001` to tune encoder settings in real time. This helps you find the right balance between stream quality and CPU/bandwidth usage.

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
| `DELETE_AFTER_STREAM` | `false` | Remove clip files after they've been played |
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
