# Remediation Plan

**Date:** 2026-06-11
**Companion to:** `docs/EFFICIENCY_REPORT.md` — every finding from the report is covered
here with a concrete change, the files it touches, how to verify it, and its risk.

Work is organized into four phases in priority order. Each phase is independently
shippable; nothing in a later phase blocks an earlier one.

| Phase | Theme | Effort | Outcome |
|---|---|---|---|
| 1 | Stream quality (artifacting) | ~1–2 h | Clean motion video, settings survive restarts |
| 2 | Robustness | ~2–3 h | No silent hangs, self-healing encoder, no latency creep |
| 3 | Performance | ~1 h | ~16× fewer pipe syscalls, less allocation churn |
| 4 | Housekeeping | ~1–2 h | Docs match code, faster builds, tidy disk |

---

## Phase 0 — Confirm the diagnosis before changing code (~10 min)

The web UI makes the artifacting fix testable with zero code changes. Do this first so
Phase 1 is a confirmation, not a guess:

- [ ] Open the tuner UI (`http://<host>:5001`), set **Bitrate = 4500 kbps**, Apply.
- [ ] Run `./scripts/test-upload.sh` (or trigger a real camera clip with motion) and
      watch the stream in VLC (`rtsp://<host>:8654/camera`).
- [ ] If bottom-of-frame blocking is gone or drastically reduced → diagnosis confirmed,
      proceed. If not, stop and re-investigate before Phase 1 (check Frigate's
      `input_args` include `-rtsp_transport tcp`, and capture encoder stderr — see 2.2).

---

## Phase 1 — Stream quality (the artifacting fix)

### 1.1 Raise default bitrate and add VBV (true CBR)

**Files:** `src/reo_bridge/encoder_params.py`

- Change `bitrate_kbps: int = 1500` → `4500` (`encoder_params.py:31`).
- In `ffmpeg_args()`, add VBV constraints in **both** rate modes:

```python
if self.rate_mode == "crf":
    args += ["-crf", str(self.crf)]
args += [
    "-b:v" if self.rate_mode == "cbr" else "-maxrate", ...,
]
```

Concretely:

```python
if self.rate_mode == "crf":
    # Capped CRF: constant quality, bitrate_kbps acts as the ceiling
    args += ["-crf", str(self.crf),
             "-maxrate", f"{self.bitrate_kbps}k",
             "-bufsize", f"{self.bitrate_kbps * 2}k"]
else:
    # True CBR: VBV smooths in-frame bit allocation (the bottom-of-frame fix)
    args += ["-b:v", f"{self.bitrate_kbps}k",
             "-maxrate", f"{self.bitrate_kbps}k",
             "-bufsize", f"{self.bitrate_kbps * 2}k"]
```

**Web UI follow-up** (`web.py`): in CRF mode the bitrate slider is currently hidden
(`field-bitrate` toggling in `setRateMode()`). Since `bitrate_kbps` now doubles as the
CRF ceiling, show the slider in both modes and relabel it "Max bitrate" when CRF is
active. Update the help text accordingly.

**Verify:** stream a motion clip; confirm no blocking at the bottom of the frame.
`ffprobe` the MediaMTX output and confirm bitrate is near target during motion.
**Risk:** low. Higher bitrate = more LAN bandwidth (~4.5 Mbps/camera) and slightly more
Frigate decode work — negligible on a LAN.

### 1.2 Stop defaulting to `tune=zerolatency`

**Files:** `src/reo_bridge/encoder_params.py`, `src/reo_bridge/web.py`

- Add `"none"` as the first entry in `TUNES` (`encoder_params.py:19`).
- Change default `tune: str = "zerolatency"` → `"none"` (`encoder_params.py:36`).
- In `ffmpeg_args()`, emit `-tune` only when `self.tune != "none"`.
- Web UI: the tune dropdown is populated from `/api/options`, so `"none"` appears
  automatically; update the tune help text (`web.py` `_INDEX_HTML`) to say the stream
  is inherently delayed footage so zerolatency buys nothing, and that `none` is the
  recommended default.

**Rationale:** removes sliced-threads (the banding pattern) and re-enables lookahead —
roughly 20% better quality per bit for free. The footage is already minutes old; one
second of encoder latency is immaterial.
**Verify:** encoder restarts cleanly with no `-tune` flag (check the "Encoder args" log
line); motion clip looks cleaner at the same bitrate.
**Risk:** low. Slightly higher CPU (lookahead); measure with `docker stats`.

### 1.3 Persist tuned encoder settings across restarts

**Problem being fixed:** everything tuned in the web UI is lost when the container
restarts — the user's "restarted and it worked for a while, then back to the same"
experience is exactly what un-persisted tuning produces if defaults are bad.

**Files:** `src/reo_bridge/config.py`, `src/reo_bridge/encoder_params.py`,
`src/reo_bridge/main.py`, `docker-compose.yml`

- New config value `params_file: Path` (env `PARAMS_FILE`, default `/data/params.json`).
- `main.py`: on startup, if the file exists, load it and apply via
  `encoder_params.update(**saved)` / `streaming_params.update(**saved)` before
  `streamer.start()`.
- `encoder_params.py` / `streaming_params.py`: after a successful `update()`, write the
  combined snapshot to the params file (atomic write: temp file + `os.replace`).
  Simplest wiring: a small `persistence.py` helper called from the web endpoints, so
  the dataclasses stay storage-agnostic.
- `docker-compose.yml`: add `- ./data:/data` volume to `reo-bridge`.

**Verify:** change bitrate via UI → `docker compose restart reo-bridge` → `GET
/api/encoder` returns the tuned value.
**Risk:** low. Corrupt/invalid JSON must fail soft (log a warning, fall back to
defaults) — never crash on startup.

### 1.4 Optional preset bump

After 1.1–1.2 land, check `docker stats`. If the container sits well under one core,
change the default preset `ultrafast` → `superfast` (one word in
`encoder_params.py:35`). Each preset step is a meaningful efficiency gain. Keep
`ultrafast` if CPU is tight — bitrate is the bigger lever.

### 1.5 Frigate-side check (user action, no code)

- [ ] Confirm the Frigate camera config for this stream has no custom `input_args`
      overriding the default `-rtsp_transport tcp`.
- [ ] While at it, set `audio: false` for this camera in Frigate if not needed.

---

## Phase 2 — Robustness

### 2.1 Eliminate the decoder-stderr deadlock

**Files:** `src/reo_bridge/stream.py` (`_decode_from_offset`, `stream.py:184-198`)

Replace the read-stderr-after-wait pattern with a drain thread started immediately
after `Popen`:

```python
stderr_lines: list[str] = []
def _drain(pipe):
    for raw in pipe:
        line = raw.decode(errors="replace").rstrip()
        if len(stderr_lines) < 50:        # cap memory on chatty decodes
            stderr_lines.append(line)
threading.Thread(target=_drain, args=(proc.stderr,), daemon=True).start()
```

The frame-read loop is unchanged; after `proc.wait()`, log the captured lines on
non-zero exit as today.

**Verify:** feed a deliberately truncated MP4 (`head -c 100000 clip.mp4 > broken.mp4`
into the watch dir) — bridge must log the decoder error and return to idle frames, not
hang. This is the regression that realtime mode makes likely, so test with realtime on
too.
**Risk:** low; pure plumbing.

### 2.2 Supervise the output encoder and surface its stderr

**Files:** `src/reo_bridge/stream.py`, `src/reo_bridge/main.py`

Three coordinated changes:

1. **Capture encoder stderr** (`stream.py:90-91`): `stderr=subprocess.PIPE` plus a
   daemon drain thread forwarding each line to `log.warning("encoder: %s", line)`.
   This makes every future encoder problem diagnosable.
2. **Survive `BrokenPipeError`** (`_write_to_pipe`, `stream.py:237-243`): catch
   `BrokenPipeError`/`OSError`, log once, and set a `self._encoder_dead = True` flag
   instead of crashing the caller. `write_idle_frame()` and the clip read-loop check
   the flag and bail out of the current clip.
3. **Self-heal in the main loop** (`main.py:62-79`): alongside the existing
   `needs_restart()` check, add `if streamer.encoder_dead(): streamer.restart()`.
   `restart()` already exists and rebuilds the pipe + process. Add basic backoff
   (e.g. don't restart more than once per 5 s) so a persistently failing RTSP target
   doesn't busy-loop.

**Verify:** `docker compose exec reo-bridge pkill -9 -f 'ffmpeg.*rtsp'` — the bridge
must log the death, restart the encoder, and the stream must come back within seconds
without the container restarting. Also: stop the `mediamtx` container mid-stream and
restart it; bridge should reconnect on its own.
**Risk:** medium — touches the hot path. Keep the happy path identical (flag check is
one branch); test idle + clip + restart-during-clip.

### 2.3 Absolute-deadline idle pacing (stops latency creep)

**Files:** `src/reo_bridge/stream.py` (`write_idle_frame`, `stream.py:134-143`)

```python
def write_idle_frame(self) -> None:
    now = time.monotonic()
    if self._next_deadline is None or now - self._next_deadline > 1.0:
        self._next_deadline = now          # (re)sync after start or clip playback
    self._write_to_pipe(self._black_frame)
    self._next_deadline += self._frame_interval
    delay = self._next_deadline - time.monotonic()
    if delay > 0:
        time.sleep(delay)
```

The resync guard matters: after a clip plays (paced by the decoder's `-re`, not by this
loop) the old deadline is stale; without the guard the loop would blast frames to
"catch up". Initialize `self._next_deadline = None` in `__init__` and reset it to
`None` at the end of `stream_file()`.

**Verify:** soak test — run idle for several hours, compare wall-clock elapsed vs.
frames written × interval (add a debug counter); drift should be bounded (< one frame),
not growing. Watch stream latency in VLC at hour 0 vs hour 12.
**Risk:** low, but the resync edge case is the thing to test (idle → clip → idle).

### 2.4 Handle renamed/moved uploads in the watcher

**Files:** `src/reo_bridge/watcher.py` (`_VideoFileHandler`)

Add alongside `on_created`:

```python
def on_moved(self, event) -> None:
    if event.is_directory:
        return
    self._handle_new_file(Path(event.dest_path))
```

Factor the body of `on_created` into `_handle_new_file(path)` so both events share the
suffix check / settle / realtime logic. Dedupe guard: keep a small set of recently
queued paths (or rely on the settle thread's `FileNotFoundError` handling) so a
create-then-rename sequence doesn't queue the clip twice — a `dict[Path, float]` of
paths queued in the last 60 s is sufficient.

**Verify:** `mv` a clip into the watch dir from the same filesystem (inotify reports
this as a move, not a create) — it must stream. Upload via FTP still works.
**Risk:** low.

---

## Phase 3 — Performance

### 3.1 Enlarge the OS pipe

**Files:** `src/reo_bridge/stream.py` (`_start_encoder`)

```python
import fcntl
read_fd, self._write_fd = os.pipe()
try:
    fcntl.fcntl(self._write_fd, fcntl.F_SETPIPE_SZ, 1024 * 1024)
except OSError:
    pass  # exceeds fs.pipe-max-size or unprivileged — default 64 KiB still works
```

Cuts ~85 syscalls per 5.3 MiB frame to ~6. Must stay best-effort (the `try/except`),
since `fs.pipe-max-size` varies by host.

### 3.2 Reuse a frame buffer in the decode loop

**Files:** `src/reo_bridge/stream.py` (`_decode_from_offset`)

Preallocate once per clip and read into it:

```python
buf = bytearray(self._frame_size)
view = memoryview(buf)
while True:
    n = proc.stdout.readinto(buf)          # may be short — top up below
    while n and n < self._frame_size:
        more = proc.stdout.readinto(view[n:])
        if not more:
            break
        n += more
    if n < self._frame_size:
        break                              # EOF / partial frame — discard
    self._write_to_pipe(buf)
    frames += 1
```

Note `readinto` on a buffered pipe may return short reads mid-stream (unlike
`.read(n)` which loops internally), hence the top-up loop — this preserves the
frame-alignment guarantee that the architecture depends on.

**Verify (both 3.1 + 3.2):** before/after CPU comparison with `docker stats` at idle
and during a clip; clip plays bit-identically (no visual change). `strace -c -p <pid>`
optionally confirms the syscall drop.
**Risk:** medium for 3.2 only because frame alignment is sacred — the top-up loop must
be right. 3.1 is risk-free.

### 3.3 Record a CPU baseline (15 min, no code)

Capture `docker stats` numbers (idle and during clip) before and after Phases 1–3 and
note them in `PROGRESS.md`. This is the input for the multi-camera decision later —
per-camera cost × N cameras must fit the box.

---

## Phase 4 — Housekeeping

### 4.1 Clean up empty date directories with `DELETE_AFTER_STREAM`

**Files:** `src/reo_bridge/main.py` (`main.py:74-76`)

After `path.unlink()`, walk parents up to (not including) `config.watch_dir`, calling
`parent.rmdir()` and stopping at the first `OSError` (non-empty). Guard with
`parent.is_relative_to(config.watch_dir)`.

**Verify:** upload to a nested `2026-06-11/` folder with delete-after-stream on; folder
disappears after the clip streams; `watch_dir` itself is never removed.

### 4.2 Queue visibility

**Files:** `src/reo_bridge/watcher.py`

When enqueueing while the queue is non-empty, log
`"Queued %s (%d clips waiting)" % (path.name, qsize)`. Optionally add a
`MAX_CLIP_AGE_SECONDS` env (default 0 = disabled) that drops clips older than the limit
at dequeue time with a warning — leave **disabled by default**; for a security system,
late footage beats dropped footage.

### 4.3 Dockerfile layer ordering

**Files:** `Dockerfile`

```dockerfile
COPY pyproject.toml .
RUN pip install --no-cache-dir flask>=3.0 watchdog>=4.0   # deps layer, rarely changes
COPY src/ src/
RUN pip install --no-cache-dir --no-deps .
```

(Match the version pins to `pyproject.toml`; the duplication is the price of layer
caching with a src-layout package. Alternative: a `requirements.txt` generated from
`pyproject.toml`.)

**Verify:** `docker compose build`, touch a source file, rebuild — second build must
skip the dependency layer.

### 4.4 Fix documentation drift

**Files:** `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/PROGRESS.md`, `docker-compose.yml`

- "Alternating blue/red" idle frames → the code writes solid **black**
  (`stream.py:43-44`). Either fix the docs to say black, or implement the alternating
  frames (one extra pre-generated frame + a toggle in `write_idle_frame`) — *decide
  one way*; docs and code must agree. Recommendation: fix the docs; a solid color
  encodes cheaper and alternating colors add nothing.
- `PROGRESS.md` Phase 2 claims a named `watch_data` volume; compose uses the
  `./watch_dir` bind mount (`docker-compose.yml:55,76`). Correct the doc (bind mount is
  fine and easier to inspect).
- After 1.1 lands, the UI help text, the coded default, and `PROGRESS.md`'s parameter
  table all agree on the new bitrate default — update the table.

### 4.5 Deferred / not planned

- **Flask dev server → waitress**: deferred. LAN-only tuning UI, low traffic; revisit
  if the UI grows.
- **Dropping the silent audio track**: not planned in the bridge — handle on the
  Frigate side (`audio: false`). Keeping the track keeps the stream format stable for
  any client.
- **Multi-camera support**: separate piece of work (Phase 4 in `PROGRESS.md`); the
  compose-duplication approach already discussed needs no code. Do 3.3's CPU baseline
  first.

---

## Suggested sequencing & verification gates

```
Phase 0 (UI-only test) ──► confirms diagnosis
Phase 1.1 + 1.2 ─────────► one commit: "fix encoder defaults (artifacting)"
        gate: motion clip clean in VLC + Frigate
Phase 1.3 ───────────────► one commit: params persistence
        gate: settings survive `docker compose restart`
Phase 2.1, 2.2, 2.3, 2.4 ► one commit each (independent)
        gate: truncated-file test, encoder-kill test, soak test, mv-file test
Phase 3.1 + 3.2 ─────────► one commit: pipe/buffer perf
        gate: CPU before/after, clip visually identical
Phase 4 ─────────────────► one or two commits: housekeeping + docs
```

Total estimated effort: **5–8 hours** including verification. The single
highest-value 30 minutes is Phase 0 + Phase 1.1/1.2 — it resolves the user-visible
artifacting.

After each phase, update `docs/PROGRESS.md` (per `CLAUDE.md`).
