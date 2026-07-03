# Architecture

## The Problem

Frigate NVR expects cameras to provide a **continuous RTSP video stream**. Reolink battery cameras cannot do this — they sleep to save battery and only wake to record motion events. They can, however, **upload recorded clips via FTP**.

## The Solution

This project bridges the gap with three components:

```
┌──────────────┐    FTP upload     ┌──────────────┐
│   Reolink    │ ───────────────→  │  Watch Dir   │
│ Battery Cam  │   (video files)   │  (/watch)    │
└──────────────┘                   └──────┬───────┘
                                          │ inotify (file watcher)
                                          ▼
                                   ┌──────────────┐
                                   │  reo-bridge  │
                                   │  (Python)    │
                                   └──────┬───────┘
                                          │ FFmpeg → RTSP push
                                          ▼
                                   ┌──────────────┐
                                   │   MediaMTX   │
                                   │ (RTSP server)│
                                   └──────┬───────┘
                                          │ RTSP pull
                                          ▼
                                   ┌──────────────┐
                                   │   Frigate    │
                                   │    NVR       │
                                   └──────────────┘
```

### 1. Watch Directory (`/watch`)

A folder on disk that your FTP server points Reolink cameras at. When a camera detects motion, it records a clip and uploads the `.mp4` file here.

### 2. reo-bridge (Python application)

The core of this project. It does three things:

- **Watches** the `/watch` directory for new video files using `watchdog` (Linux inotify)
- **Waits** for each file to finish writing (FTP uploads aren't instant)
- **Feeds a persistent FFmpeg pipeline** via a raw video pipe

### 3. MediaMTX (RTSP server)

A lightweight, zero-config RTSP/RTMP/HLS server. It receives the stream pushed by FFmpeg and serves it to any client that connects — in our case, Frigate.

## Pipe-Based Stream Architecture

The critical design challenge: switching between idle and clip playback **must not interrupt the RTSP stream**, or clients (VLC, Frigate) will disconnect.

The solution is a **single persistent FFmpeg process** that never restarts:

```
                    ┌─────────────────────────────────────────────┐
                    │              OS Pipe (raw YUV420P)          │
                    │                                             │
  Python idle       │                                             │
  frame writer  ──write──→  pipe  ──read──→  Output FFmpeg ──→ RTSP
                    │          ↑                (persistent)      │
  Clip decoder  ──write──┘    │                                   │
  FFmpeg (temp)               │                                   │
                    └─────────────────────────────────────────────┘
```

### How the pipe works

1. **On startup**, an OS pipe is created. One persistent FFmpeg reads raw video from the read end and encodes H264 + silent AAC to RTSP. This process runs for the entire lifetime of the bridge.

2. **When idle**, the Python main loop writes a pre-generated solid black YUV420P frame directly to the pipe's write end at the target FPS.

3. **When a clip arrives**, the main loop stops writing idle frames and spawns a temporary FFmpeg to decode the clip to raw YUV420P. Python reads complete frames from the decoder's stdout and writes them to the pipe. The output FFmpeg sees a seamless stream of frames — it has no idea the source changed.

4. **When the clip finishes**, the main loop resumes writing idle frames.

### Why this works

- The output FFmpeg **never restarts**, so the RTSP connection to MediaMTX stays up permanently.
- Both idle and clip frames are **raw YUV420P at a consistent resolution**, so the encoder never sees format changes.
- Python reads clip frames in **exact frame-sized chunks**, guaranteeing no partial frames corrupt the stream.
- The pipe provides natural **back-pressure** — if the encoder falls behind, writes block until it catches up.

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Persistent pipe-fed FFmpeg** | Prevents RTSP stream drops during idle↔clip transitions. Clients stay connected. |
| **Python-generated idle frames** | Avoids needing a second long-running FFmpeg process. The black frame is pre-computed once. |
| **Raw YUV420P through pipe** | Simple, no container format needed. Frame boundaries are implicit (fixed size). |
| **Python as frame middleman for clips** | Ensures only complete frames reach the pipe. Partial frames from clip EOF are discarded. |
| **File settle detection** | FTP uploads take time. We poll file size and only process once it stops growing. |
| **Docker Compose** | Matches how most people run Frigate. Easy to add to an existing stack. |

## Data Flow (Timeline)

```
Time ──────────────────────────────────────────────────────→

Reolink:   [sleeping]     [MOTION!] ──record──→ [FTP upload] ──→ [sleeping]
Watch Dir:                                       [file appears, grows, done]
Pipe:      [idle frames]  ────────────────────→  [clip frames] → [idle frames]
RTSP:      [connected, black]      ────────────→ [sees clip!]  → [black]
```

## File Structure

```
src/reo_bridge/
├── __init__.py
├── config.py            # Environment variable configuration
├── encoder_params.py    # Thread-safe mutable encoder settings (tuned via web UI)
├── streaming_params.py  # Thread-safe mutable streaming settings (realtime mode)
├── main.py              # Entry point — main loop writes idle frames or plays clips
├── stream.py            # Pipe-based FFmpeg pipeline (persistent output + clip decoder)
├── watcher.py           # Folder monitoring with watchdog
└── web.py               # Flask web UI + JSON API for live encoder tuning
```
