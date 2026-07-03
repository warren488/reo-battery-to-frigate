# Efficiency & Stream-Quality Report

**Date:** 2026-06-11
**Scope:** Full review of the bridge for inefficiencies, plus a focused diagnosis of the
reported artifacting (heavy blocking in the bottom portion of the frame during motion,
temporarily improved by a restart).

---

## Part 1 — Focused issue: bottom-of-frame artifacting during motion

### Diagnosis: bitrate starvation, amplified by the encoder configuration

The default encoder settings (`encoder_params.py`) are:

| Setting | Default | Problem |
|---|---|---|
| Rate control | "CBR" 1500 kbps | Far too low for 2560×1440 @ 20 fps |
| Preset | `ultrafast` | The least bit-efficient x264 preset — needs *more* bitrate than other presets, not less |
| Tune | `zerolatency` | Disables lookahead and B-frames, enables sliced threads — further reduces quality per bit |
| VBV | none | `-b:v` alone is average bitrate (ABR), not true CBR — no `-maxrate`/`-bufsize` is set |

1440p20 with `ultrafast` + `zerolatency` realistically needs **4000–8000 kbps** to look
clean during motion. The web UI's own help text says *"Below 1000 kbps at 2K you'll see
heavy blocking artifacts"* and recommends 2000–4000 — yet the coded default is 1500
(`encoder_params.py:31`).

### Why the *bottom* of the frame specifically

This symptom is a signature of per-frame bit-budget exhaustion:

- x264 encodes macroblock rows **top to bottom** and adapts the quantizer mid-frame to
  hit the frame's bit budget. When the budget runs out partway down (which happens
  exactly when motion makes the frame expensive), the bottom rows get crushed with very
  coarse quantization → blocking concentrated in the lower portion.
- `tune=zerolatency` additionally enables **sliced threads**: the frame is split into
  horizontal bands encoded independently, each with its own slice of the budget. Band
  boundaries and the lower bands are where starvation shows first.

### Why it only appears during motion

Idle frames are solid black — they compress to almost nothing, so the stream looks fine
when idle. Real footage with motion needs orders of magnitude more bits than 1500 kbps
provides at this resolution, so quality collapses precisely when something interesting
is happening (the worst possible failure mode for an NVR feed).

### Why restarting seemed to help temporarily

Three plausible mechanisms; any or all may have contributed:

1. **Fresh rate-control state.** Without VBV constraints, x264's ABR controller tracks
   cumulative over/under-spend. After hours of near-zero-cost idle frames the controller
   is in an unusual state when a clip suddenly arrives; a restart resets it.
2. **Accumulated timing drift reset.** Idle pacing uses relative sleeps that never
   compensate for overshoot (`stream.py:134-143`), so effective fps runs slightly under
   nominal and stream latency grows the longer the bridge runs. A restart zeroes this
   (see finding 3 below).
3. **Coincidence.** Clips right after the restart may simply have contained less motion.

Either way, the fix is to address the root cause rather than restart-as-medicine.

### Recommended fixes (in order)

1. **Raise the default bitrate** to 4000–6000 kbps (`encoder_params.py:31`). The UI
   slider already allows up to 10,000.
2. **Add VBV for real CBR** in `EncoderParams.ffmpeg_args()`:
   `-maxrate {bitrate}k -bufsize {2×bitrate}k`. This smooths in-frame bit allocation
   (directly mitigating the bottom-of-frame collapse) and makes "CBR" mean what it says.
3. **Drop `tune=zerolatency`** (use no tune, or `film`). The footage in this stream is
   inherently minutes old (record → FTP upload → settle → replay); saving one second of
   encoder latency buys nothing here. Removing it re-enables lookahead and normal frame
   threading, eliminating the sliced-thread banding and improving quality per bit
   noticeably.
4. **Try a slower preset** (`superfast` or `veryfast`) if `docker stats` shows CPU
   headroom — each step down from `ultrafast` is a significant efficiency gain.
5. **Alternative: capped CRF.** On a LAN where bandwidth isn't scarce, CRF 23 with a
   `-maxrate`/`-bufsize` cap gives constant visual quality and only spends bits when
   motion needs them. (Today CRF mode also has no cap — same one-line fix as #2.)
6. **Check the Frigate side**: confirm Frigate's ffmpeg input args include
   `-rtsp_transport tcp` (its modern defaults do, but custom `input_args` override
   this). The bridge already pushes over TCP, but a UDP *pull* would add packet-loss
   smearing on top of the encoder artifacts.

---

## Part 2 — General inefficiencies and robustness findings

### High impact

**1. Decoder stderr can deadlock the whole bridge — `stream.py:184-198`**
The clip decoder is started with `stderr=subprocess.PIPE`, but stderr is only read
*after* `proc.wait()`. If FFmpeg writes more than ~64 KB of warnings (easy with a
corrupt or partially-uploaded file — exactly what realtime mode feeds it), the decoder
blocks writing stderr, stops producing stdout, and the frame-read loop blocks forever.
The bridge then hangs silently: idle frames stop, the stream stalls, no log output.
*Fix:* drain stderr on a background thread, or pass `stderr=subprocess.DEVNULL` and
only enable the pipe when debugging.

**2. Output-encoder death is invisible and unhandled — `stream.py:90-91, 237-243`**
The persistent encoder's stderr goes to `DEVNULL`, so if it dies (RTSP disconnect,
encode error) there is no diagnostic. The next `os.write()` to the pipe raises
`BrokenPipeError`, which crashes the main loop; Docker's `restart: unless-stopped`
papers over it, but the file queue and any in-flight settle threads are lost, and the
root cause is never logged.
*Fix:* poll `self._output_proc.poll()` in the main loop and call the existing
`restart()`; capture encoder stderr (a small drain thread that forwards to `log`).

**3. Idle-frame pacing drifts — `stream.py:134-143`**
`write_idle_frame()` sleeps `interval − elapsed`, but sleep overshoot is never
compensated, so the loop always runs at *slightly under* the nominal fps. The encoder
stamps frames at exactly 20 fps regardless, so stream time falls behind wall clock and
latency grows unboundedly the longer the bridge runs (and resets on restart — see
Part 1). *Fix:* absolute-deadline scheduling (`next_deadline += interval; sleep until
next_deadline`).

### Medium impact

**4. Pipe write overhead — `stream.py:237-243`**
A 2560×1440 YUV420P frame is ~5.3 MiB; at 20 fps Python shuffles ~105 MiB/s through a
pipe whose default capacity is 64 KiB → roughly 85 `os.write()` syscalls per frame plus
matching reads, 24/7, even when idle. *Fix:* enlarge the pipe once at startup with
`fcntl(fd, F_SETPIPE_SZ, 1 MiB)` (~16× fewer syscalls). In the decode loop, reading
into a preallocated `bytearray` via `readinto()` would also avoid allocating a fresh
5.3 MiB `bytes` per frame.

**5. Continuous full-resolution encode while idle — by design, but worth stating**
The persistent encoder compresses 1440p20 around the clock even when showing solid
black. Solid frames are cheap for x264, so this is acceptable for one camera — but it
scales linearly with cameras and is the dominant CPU cost of the design. Recommendation
when going multi-camera: measure with `docker stats` before assuming headroom.

**6. Watcher misses renamed files — `watcher.py:26-44`**
Only `on_created` is handled. Some FTP servers/cameras upload to a temporary name and
rename into place; a rename arrives as a *moved* event and the clip is silently
ignored. *Fix:* also implement `on_moved` (treat `dest_path` like a creation).

**7. Empty directory accumulation with `DELETE_AFTER_STREAM`**
Reolink cameras create nested date folders; only the clip file is unlinked
(`main.py:74-76`), so empty `YYYY-MM-DD/` directories accumulate indefinitely.

**8. Unbounded queue with 1× playback**
Clips replay in real time (`-re`), so if uploads arrive faster than they can be played
back-to-back (multiple triggers in quick succession), the queue backlog grows and the
stream falls progressively further behind reality. No drop policy or catch-up exists.
Probably acceptable for a single battery cam; worth a max-age or queue-depth log line.

### Low impact / hygiene

**9. Documentation drift**
- `CLAUDE.md`, `docs/ARCHITECTURE.md` (and `PROGRESS.md` Phase 1.5) describe idle as
  *alternating blue/red frames*; the code writes solid **black** (`stream.py:43-44`).
- `PROGRESS.md` Phase 2 says the watch dir moved to a named volume `watch_data`;
  `docker-compose.yml:55,76` still uses the `./watch_dir` bind mount.
- The coded default bitrate (1500) contradicts the web UI's own recommendation
  (2000–4000 for 2K).

**10. Dockerfile layer ordering — `Dockerfile:11-13`**
`COPY src/ src/` happens before `pip install`, so every source change invalidates the
dependency layer and reinstalls Flask/watchdog. *Fix:* copy `pyproject.toml` alone,
install deps, then copy `src/` (or use `pip install --no-deps` for the project layer).

**11. Flask development server in production — `web.py:37`**
Fine for a LAN tuning UI, but it's single-process dev-grade; if the UI ever grows
beyond tuning, switch to waitress/gunicorn. Not urgent.

**12. Silent-audio track** — anullsrc is encoded to AAC continuously. Negligible CPU,
but it exists only to keep the stream format stable for Frigate; if Frigate is
configured with `audio: false` for this camera the track could be dropped entirely.

---

## Quick wins summary

| # | Change | Effort | Payoff |
|---|---|---|---|
| 1 | Default bitrate 1500 → 4000–6000 kbps + add `-maxrate`/`-bufsize` | ~5 lines | Fixes the artifacting |
| 2 | Drop `zerolatency` tune default | 1 line | Better quality/bit, removes slice banding |
| 3 | Drain or devnull decoder stderr | ~10 lines | Removes a silent total-hang failure mode |
| 4 | Monitor encoder process + log its stderr | ~20 lines | Self-healing stream, visible diagnostics |
| 5 | Absolute-deadline idle pacing | ~5 lines | Stops latency growing over uptime |
| 6 | Handle `on_moved` in watcher | ~5 lines | No silently dropped uploads |
