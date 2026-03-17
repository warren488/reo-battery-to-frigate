# Setup Guide

## Prerequisites

- Docker and Docker Compose
- A Reolink battery camera with FTP upload enabled
- Frigate NVR (running separately or in the same Docker Compose stack)

## Quick Start

### 1. Configure the FTP server

Copy the example env file and edit it:

```bash
cp .env.example .env
```

Edit `.env` and set `FTP_PUBLIC_HOST` to the IP address of this machine on your local network (the IP your cameras can reach):

```
FTP_PUBLIC_HOST=192.168.1.100
FTP_USER=reolink
FTP_PASS=reolink
```

### 2. Configure stream settings (optional)

Edit the `environment` section under `reo-bridge` in `docker-compose.yml` to match your camera:

| Variable | Default | Description |
|---|---|---|
| `WATCH_DIR` | `/watch` | Path inside the container (mapped via shared volume) |
| `RTSP_OUTPUT_URL` | `rtsp://mediamtx:8554/camera` | Where to push the RTSP stream |
| `STREAM_WIDTH` | `2560` | Output stream width in pixels |
| `STREAM_HEIGHT` | `1440` | Output stream height in pixels |
| `STREAM_FPS` | `20` | Output stream frame rate |
| `SETTLE_SECONDS` | `2.0` | Wait time for file write completion |
| `DELETE_AFTER_STREAM` | `false` | Delete video files after streaming |

### 3. Start the stack

```bash
docker compose up -d --build
```

This starts three services:
- **ftp** — FTP server on port 21 (receives uploads from cameras)
- **mediamtx** — RTSP server on port 8554 (serves the stream to Frigate)
- **reo-bridge** — the bridge (watches for uploads, feeds the stream)

### 4. Configure your Reolink camera

In the Reolink app or web UI, go to **Settings → Surveillance → FTP**:

| Setting | Value |
|---|---|
| FTP Server | IP address of this machine (same as `FTP_PUBLIC_HOST`) |
| Port | `21` |
| Username | `reolink` (or whatever you set in `.env`) |
| Password | `reolink` (or whatever you set in `.env`) |

Enable FTP upload for motion events.

### 5. Configure Frigate

Add the camera to your Frigate config:

```yaml
cameras:
  reolink_battery:
    ffmpeg:
      inputs:
        - path: rtsp://<bridge-host>:8554/camera
          roles:
            - detect
            - record
    detect:
      width: 2560
      height: 1440
      fps: 20
```

Replace `<bridge-host>` with the IP/hostname of the machine running this bridge.

## Verifying it works

### Check the stream with VLC

Open VLC and play: `rtsp://<bridge-host>:8554/camera`

You should see alternating blue/red frames. Drop a `.mp4` file into the FTP server (or use the test script) and it should play through the stream.

### Test with a sample clip

```bash
./scripts/test-upload.sh
```

This generates a 5-second yellow test clip and places it in the watch volume.

### Check logs

```bash
docker compose logs -f reo-bridge
```

You should see messages like:
```
Bridge is running. Waiting for video files in /watch ...
Detected new file: clip_001.mp4 — waiting for write to settle
File ready: clip_001.mp4 (5242880 bytes)
Streaming file: clip_001.mp4
Finished streaming: clip_001.mp4
```

### Test FTP upload manually

```bash
# Upload a file via FTP to verify the server is working
curl -T some_video.mp4 ftp://reolink:reolink@localhost/
```
