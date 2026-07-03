# OSS Readiness Audit

**Date:** 2026-07-03
**Scope:** Full-repo audit ahead of publishing this project publicly — code quality,
performance, security, Docker/build, documentation accuracy, web UI/UX, and video
output quality.
**Companions:** `docs/EFFICIENCY_REPORT.md` (2026-06-11) diagnosed the encoder/
robustness issues in depth and `docs/REMEDIATION_PLAN.md` gives step-by-step fixes for
them. This audit **does not repeat that material** — it verifies its status (§1) and
covers everything the June review didn't: OSS hygiene, security, build, docs drift,
and UI/UX.

---

## Executive summary

The core idea and architecture are genuinely good — the pipe-fed persistent encoder is
the right design, it's clearly documented, and it solves a real problem (Reolink
battery cams + Frigate) that people actively search for. The gap between "works for me"
and "ready for strangers" is mostly hygiene, not engineering:

**Publish blockers (do these or don't publish):**
1. **No LICENSE file.** Legally, nobody can use, fork, or contribute to the repo. This
   single file is the difference between a project and a code listing. (§2)
2. **Repo name typo:** `reo-batter-to-frigate` — "batter" for "battery" — on the repo,
   the package name, and the README clone URL. Rename before the URL spreads. (§3)
3. **Private LAN IP in `.env.example`** (`192.168.100.201`) — replace with a
   placeholder. (§4.4)
4. **No `.dockerignore`** — the build context currently ships **695 MB** of personal
   camera footage (`watch_dir/`) to the Docker daemon on every build. For anyone who
   clones fresh it's "only" slow; for you it's your own surveillance clips being
   copied around on every `docker compose build`. (§5.1)
5. **Apply Phase 1 of `docs/REMEDIATION_PLAN.md`** (bitrate default + VBV + drop
   `zerolatency`). Shipping with defaults that produce visible artifacting — which the
   UI's own help text warns against — guarantees "the video looks terrible" as the
   first GitHub issue. (§1)

**Strongly recommended before launch:** decoder-stderr deadlock fix and encoder
supervision (June report #1/#2 — these are silent total-failure modes strangers *will*
hit), pin Docker images, README security section, fix the doc drift in §8, minimal CI.

**High-leverage for traction:** a screenshot/GIF in the README, an honest
"Limitations" section, a status card + live preview in the web UI (§9).

---

## 1. Status of the 2026-06-11 review — all findings still open

Verified against the code today: **none** of the June report's fixes have been applied.

| June finding | Status today |
|---|---|
| #1 Bitrate 1500 kbps default, no VBV | Open — `encoder_params.py:31`, `ffmpeg_args()` unchanged |
| #1 `tune=zerolatency` default | Open — `encoder_params.py:36` |
| #2 Decoder stderr deadlock | Open — `stream.py:184–198` still reads stderr after `wait()` |
| #3 Encoder death invisible / crashes loop | Open — `stream.py:91` still `stderr=DEVNULL`, no poll |
| #4 Idle pacing drift | Open — `stream.py:134–143` still relative sleeps |
| #5 Pipe syscall overhead | Open — no `F_SETPIPE_SZ`, per-frame `bytes` allocation |
| #6 `on_moved` not handled | Open — `watcher.py` only handles `on_created` |
| #7 Empty date dirs with delete-after-stream | Open |
| #8 Docs drift (blue/red idle, `watch_data` volume) | Open — see §8 for the full list |
| #9 Dockerfile layer ordering | Open — `Dockerfile:11–13` |

`docs/REMEDIATION_PLAN.md` already sequences these with verification gates; nothing in
this audit changes that plan. Phase 1 (stream quality) and Phase 2.1/2.2 (the two
silent-hang failure modes) should land **before** the repo goes public — they are the
issues external users will hit first and report loudest.

Also note: `EFFICIENCY_REPORT.md` and `REMEDIATION_PLAN.md` are currently **untracked**
— commit them (they're good docs and show the project is actively maintained).

---

## 2. Licensing & legal — BLOCKER

- **No `LICENSE` file.** Without one, all rights are reserved by default: nobody may
  legally use, modify, or redistribute the code, and most companies and serious
  contributors will not touch it. GitHub also won't show a license badge, which is one
  of the first things people check.
- Recommendation: **MIT** (matches the ecosystem — Frigate and MediaMTX are MIT) or
  Apache-2.0 if you want an explicit patent grant. Add the `license` field to
  `pyproject.toml` at the same time (§6.4).
- The stack only *invokes* FFmpeg/MediaMTX/Pure-FTPd as separate processes/containers,
  so their licenses (LGPL/GPL for typical ffmpeg builds, MIT, BSD) don't constrain your
  choice.

---

## 3. Naming & first impressions

- **"batter" → "battery":** the typo is in the GitHub repo name, `pyproject.toml`
  (`name = "reo-batter-to-frigate"`), and the README's clone URL. Rename the repo
  before launch — GitHub redirects old URLs, but the name appears in every share link,
  search result, and `docker compose` project name.
- **Three names for one project:** the repo is `reo-batter-to-frigate`, the README
  calls it "Reo Bridge", the package is `reo_bridge`. Pick one public identity.
  Suggestion: keep the human name **Reo Bridge** but make the repo name searchable —
  people will search "reolink battery camera frigate". Something like
  `reolink-battery-frigate-bridge` hits every keyword. Add GitHub topics
  (`frigate`, `reolink`, `rtsp`, `nvr`, `home-automation`) either way.
- **README first screen:** the problem statement is excellent. What's missing for
  traction: a **screenshot of the web UI** and ideally a short **GIF of a clip playing
  through the stream**, plus badges (license, CI once it exists). Repos with a visual
  above the fold convert dramatically better.
- **Be honest about limitations up front.** Add a "Limitations" section to the README:
  footage is inherently delayed (record → upload → settle → replay), so Frigate event
  timestamps are minutes behind reality; this is a *review* pipeline, not live
  monitoring; standard MP4 uploads can't be streamed mid-upload (moov at EOF); no
  camera audio passthrough. Users who discover limitations from the README file
  feature requests; users who discover them after setup file angry issues.

---

## 4. Security posture

Nothing here is alarming for a single-user LAN deployment, but a public README invites
deployments you didn't anticipate. Fix the cheap ones; document the rest.

### 4.1 Web UI: unauthenticated, all interfaces
`web.py:37` binds `0.0.0.0` and compose publishes `5001:5001`, which on Linux also
means "all host interfaces" and **bypasses ufw/firewalld** via Docker's iptables rules.
Anyone who can reach the host can reconfigure the encoder (harmless-ish) — but it's an
unauthenticated Flask dev server exposed by default. Cheap fixes:
- Publish as `127.0.0.1:5001:5001` by default and document how to open it to the LAN, **or**
- Add an optional `WEB_UI_TOKEN` env check.
- Input validation in `web.py` is genuinely good (whitelisted presets/tunes/rate modes,
  range-checked ints), so there's no command-injection path into the FFmpeg argv. Keep
  it that way — never interpolate free-text params into `ffmpeg_args()`.

### 4.2 FTP: plaintext, default creds, exposed on all interfaces
Inherent to the camera (Reolink battery cams speak plain FTP), so this can't be
"fixed," but it must be **documented**: credentials cross the LAN in cleartext, and
compose publishes port 21 + passive ports on all interfaces. Add a README "Security
notes" section saying: change `FTP_USER`/`FTP_PASS` from `reolink`/`reolink`, run this
on a trusted LAN (ideally a camera VLAN), don't port-forward FTP or the web UI to the
internet.

### 4.3 MediaMTX: open publish/subscribe
The default MediaMTX config accepts **any** publisher on any path — anyone on the LAN
can push their own stream over yours (or read it). Ship a minimal `mediamtx.yml` that
restricts publishing to authenticated or source-IP-limited access, or at least document
the risk. Frigate-side read access can stay open on a trusted LAN.

### 4.4 `.env.example` leaks your real LAN IP
`FTP_PUBLIC_HOST=192.168.100.201` is (presumably) your actual machine. Replace with an
obvious placeholder (`FTP_PUBLIC_HOST=192.168.1.100`). Also note the inline comment on
that line: some env-file parsers include trailing `# comments` in the value — move
comments to their own line to be safe.

### 4.5 Container hardening (nice-to-have)
The bridge runs as root in the container. It only needs read (+optional delete) on
`/watch`. Add a non-root `USER` in the Dockerfile once the volume permission story with
Pure-FTPd's upload UID is worked out — worth a TODO, not a blocker.

---

## 5. Build & deployment

### 5.1 Missing `.dockerignore` — BLOCKER-adjacent
The build context is the whole repo: currently **695 MB**, dominated by `watch_dir/`
(your real camera footage) plus `.git/`, `docs/`, `.env`. Every `docker compose build`
copies all of it to the daemon. Add:

```
watch_dir/
.git/
.env
docs/
__pycache__/
*.pyc
.claude/
```

This makes builds seconds faster and, more importantly, keeps personal footage and
your `.env` secrets out of the build context entirely (a stray `COPY . .` added later
would otherwise bake them into an image).

### 5.2 Unpinned images
- `bluenviron/mediamtx:latest` — MediaMTX has made breaking config changes between
  minor versions. Pin a major/minor tag (e.g. `bluenviron/mediamtx:1`).
- `stilliard/pure-ftpd` — no tag at all (implicit `latest`).
Pinning is table stakes for a compose file strangers will run: "works on my machine"
bugs from image drift are miserable to triage in issues.

### 5.3 No healthchecks / readiness ordering
`depends_on: mediamtx` only orders container *start*, not readiness. In practice the
bridge's first RTSP push can race MediaMTX's listener; FFmpeg fails, and with encoder
stderr at `DEVNULL` (June #2) the failure is invisible until nothing streams. Either
add a compose `healthcheck` on mediamtx + `condition: service_healthy`, or (better,
because it also covers mid-run restarts) implement the encoder supervision from
REMEDIATION_PLAN §2.2 so the bridge retries the push itself.

### 5.4 Dockerfile
- Layer ordering fix already specced (REMEDIATION_PLAN §4.3).
- Consider `PYTHONUNBUFFERED=1` so logs appear in `docker compose logs` in real time —
  Python buffers stdout when not a TTY, which makes the "watch the logs" instructions
  in SETUP.md misleading during slow periods.
- Optional: a `HEALTHCHECK` hitting `http://localhost:5001/api/config` gives users
  `docker ps` visibility for free.

---

## 6. Code quality & correctness (new findings — not in the June report)

The code is clean, well-commented, consistently styled, and fully type-annotated —
genuinely above-average for a hobby project. Findings below are the remaining gaps.

### 6.1 `Config` reads env vars at import time
`config.py`: every field except `watch_dir` uses `os.environ.get(...)` as a *class-level
default*, evaluated once when the module is imported. Works today (Docker sets env
before Python starts), but it means `Config()` ignores environment changes made after
import — which breaks the obvious way to write tests (`monkeypatch.setenv` then
construct). Convert all fields to `default_factory=lambda: ...` like `watch_dir`. Also:
an invalid value (e.g. `STREAM_WIDTH=abc`) raises a bare `ValueError` at import with no
hint of *which* variable — a tiny `_env_int("STREAM_WIDTH", 2560)` helper that names
the variable in the error message will save you support burden.

### 6.2 Odd dimensions would corrupt the stream silently
`STREAM_WIDTH`/`STREAM_HEIGHT` must be even for YUV420P (`w*h*3//2` and the encoder's
`-video_size` both assume it). A user setting `1919x1080` gets either an FFmpeg error
(invisible, stderr is DEVNULL) or frame-size mismatch garbage. Validate at startup:
reject odd dimensions and non-positive FPS with a clear log message.

### 6.3 Shutdown is delayed by a full clip
The SIGTERM handler only sets a flag that `main.py`'s loop checks *between* files;
`stream_file()` blocks until the clip finishes. `docker stop` waits 10 s then SIGKILLs,
so stopping the stack mid-clip skips all cleanup (decoder proc, encoder SIGINT). Fix:
check a `shutdown` flag inside the frame-read loop in `_decode_from_offset` (pass a
`threading.Event` into `StreamManager`), or document `stop_grace_period` in compose.

### 6.4 `pyproject.toml` metadata is bare
Missing: `license`, `readme`, `authors`, `classifiers`, `[project.urls]` (homepage /
issues). This is what PyPI and GitHub's dependency graph read. Two minutes of work,
add together with the LICENSE file.

### 6.5 `.jpg` uploads accumulate forever
Reolink cameras upload a `.jpg` snapshot beside every `.mp4` (visible in your own
`watch_dir/2026/...`). The watcher ignores them (correct), but `DELETE_AFTER_STREAM`
only unlinks the streamed video, so jpgs (and the empty date dirs — June #7) grow
without bound. Either delete sibling non-video files when cleaning up, or add a
retention sweep (`MAX_FILE_AGE_DAYS`), or document that users must clean the dir.

### 6.6 UI-triggered encoder restarts wait for idle
`main.py` only checks `needs_restart()` between files, so clicking "Apply & Restart
Encoder" during a long clip does nothing until the clip ends. Not a bug — restarting
mid-clip would be worse — but the UI says "the encoder restarts," so either mention
"(after the current clip finishes)" in the UI copy or check `needs_restart()` between
clips in the queue. One-line copy fix is fine.

### 6.7 Minor nits
- `stream.py` module docstring says idle frames are "(black)" while CLAUDE.md/ARCHITECTURE
  say blue/red — part of the drift cluster in §8.
- `watcher.py:21` — `queue.Queue[Path]` annotation is fine on 3.9+; `requires-python
  = ">=3.11"` covers it. No action.
- `web.py` uses module-level globals for shared state; acceptable at this size, but a
  comment noting the single-app-instance assumption would help contributors.

---

## 7. Testing & CI — currently none

There are zero tests and no CI. For OSS traction this matters twice: contributors
won't submit PRs they can't validate, and you can't merge PRs you can't validate.
Pragmatic minimum, in order of value:

1. **Unit tests that need no Docker/FFmpeg** (fast, pure-Python):
   - `_yuv420p_solid` frame size/content; `_frame_size` math.
   - `EncoderParams.ffmpeg_args()` for cbr/crf modes; `update()` version bumping and
     unknown-key rejection.
   - `web.py` validation (`_validate_encoder` / `_validate_streaming`) via Flask's
     test client — this is your public API surface.
   - Watcher settle logic with a tmpdir and a fake growing file.
2. **One integration smoke test** (needs ffmpeg, runs in CI fine): feed a tiny
   generated clip through `_decode_from_offset` into a pipe read by the test, assert
   N complete frames of the right size come out. This pins the frame-alignment
   invariant the whole architecture depends on.
3. **GitHub Actions:** `ruff check` + `ruff format --check` + `pytest` on 3.11/3.12,
   and a `docker build` job. Add `ruff` config to `pyproject.toml`. Badge in README.
4. Later: a `docker compose up` end-to-end job that uploads via curl-FTP and probes
   the RTSP stream with ffprobe — this is the test that actually guards the product,
   but get 1–3 in first.

---

## 8. Documentation accuracy — drift will burn users

Docs are unusually good for a project this age, but several statements are **wrong**,
and wrong docs are worse than no docs once strangers follow them:

| Doc | Says | Reality |
|---|---|---|
| `docs/SETUP.md` (×3: step 3, step 5, VLC check) | Frigate/VLC connect on port **8554** | Compose maps host **8654**→8554 precisely because Frigate owns 8554. README has it right. Anyone following SETUP.md gets a dead connection or accidentally hits Frigate's own restreamer. |
| `docs/SETUP.md` "Verifying" | "You should see alternating blue/red frames" | Idle frames are solid black (`stream.py:44`) |
| `CLAUDE.md`, `docs/ARCHITECTURE.md`, PROGRESS Phase 1.5 | blue/red idle frames | Same — black |
| `docs/PROGRESS.md` Phase 2 | "Switched … to named Docker volume (`watch_data`)" | Compose uses the `./watch_dir` bind mount |
| README config table | `RTSP_OUTPUT_URL` default `rtsp://mediamtx:8554/camera` | Code default is `rtsp://localhost:8554/camera` (`config.py:17`); compose sets the mediamtx value explicitly. Say "code default X, compose sets Y". |
| README + UI help | Recommends 2000–4000 kbps at 2K, warns <1000 is blocky | Shipped default is 1500 (June #1 — fix the default, then re-sync README/PROGRESS tables) |
| `docs/PROGRESS.md` ordering | Phase 2.6 (dated 2026-05-01) appears *after* the 2026-06-11 review entry | Reorder chronologically before publishing — external readers use this file to judge project health |

Also: SETUP.md and README duplicate the entire setup flow and have already diverged
(the port bug exists only in SETUP.md). Make README the canonical quick start and
strip SETUP.md down to the detailed/troubleshooting content, or delete it.

`CLAUDE.md` is your AI-assistant config; fine to keep in-repo (increasingly normal),
just make sure its facts stay synced — it has the same blue/red drift.

---

## 9. Web UI / UX review

The tuner UI is a real asset — clean dark theme, excellent inline help text (the
GOP/preset/CRF explanations are better than most commercial NVR docs). Findings, in
impact order:

### 9.1 No runtime visibility (biggest gap)
The UI shows *settings* but nothing about what the bridge is *doing*. Users tuning
blind can't tell if a clip is playing, queued, or if the encoder died. Add a
`GET /api/status` endpoint — `{state: idle|streaming, current_file, queue_depth,
encoder_alive, encoder_version, uptime_s, last_clip: {name, frames, finished_at}}` —
and a status card polling it every ~2 s. Most of this state already exists; it just
isn't exposed. This is also the foundation for a Docker healthcheck (§5.4).

### 9.2 No live preview — and MediaMTX already provides one
Compose already publishes MediaMTX's HLS/WebRTC port (8889). MediaMTX serves a ready
made player at `http://<host>:8889/camera`. Embedding that in an `<iframe>` (or even
just linking it prominently) turns the tuner into a closed loop: change bitrate →
Apply → *see* the result. This is the single highest-value UI improvement and it's
nearly free.

### 9.3 Settings silently reset on restart
The UI presents tuning as durable, but everything reverts to defaults when the
container restarts (REMEDIATION_PLAN §1.3 has the persistence design). Until that
lands, the UI should at least say "settings reset on container restart." Shipping a
tuner whose work evaporates is the kind of thing that gets called out in a Show HN
comment.

### 9.4 Smaller UX items
- **CRF mode hides the bitrate slider** — after the VBV fix (Plan §1.1) it becomes the
  quality *cap* and should stay visible, relabelled "Max bitrate."
- **"Apply & Restart Encoder" during a clip** takes effect only after the clip ends
  (§6.6) — say so in the status text.
- **No failure feedback loop:** if the encoder restart fails (bad RTSP target), the UI
  still reports "Applied ✓". The status endpoint (9.1) fixes this properly.
- **Accessibility:** `<label>` elements aren't associated with their inputs (no
  `for`/`id`), sliders have no `aria-label`, and help text at 0.75rem is small. Cheap
  fixes, worth doing before screenshots go public.
- **Polish:** no favicon (404 noise in logs); no light theme (fine — but the dark
  palette is hardcoded, so at least it's consistent); the page title says "Stream
  Tuner" which is good — keep it in sync with whatever public name §3 lands on.

---

## 10. Video pipeline quality — delta beyond the June report

The June report covers the encoder-side quality issues (bitrate, VBV, zerolatency,
preset). Remaining observations:

- **Idle→clip hard cut is fine, but keyframe timing matters for Frigate.** With
  GOP=40 (2 s), a clip can start up to 2 s before Frigate gets a decodable keyframe of
  it. Since clips are short (10–30 s), that's a meaningful slice of the event. After
  dropping `zerolatency`, x264's scene-cut detection will usually insert an I-frame at
  the black→clip transition on its own — verify this with
  `ffprobe -show_frames` once Phase 1 lands; if it doesn't, keep GOP ≤ 2 s as default
  and document it.
- **FPS resampling is correct as designed.** Battery cams record ~15 fps (sometimes
  variable); the `fps=20` filter duplicates frames to the constant output rate. Fine.
  Worth one README sentence: set `STREAM_FPS` ≥ the camera's clip fps, never below
  (downsampling would drop frames Frigate could have detected on).
- **Detection-side note for the README's Frigate snippet:** running `detect` at
  2560×1440@20 is heavy for Frigate; most users should add a `detect:` at reduced
  resolution/fps or use the stream for `record` only. A two-line note in the Frigate
  section will preempt "this pegs my CPU" issues that will otherwise be filed against
  *this* project.
- **Clip audio is dropped** (silent AAC only). Fine as a documented limitation (§3);
  a future audio-passthrough would require muxed A/V through the pipe (non-trivial —
  raw audio interleaving or a switch to something like an intermediate MPEG-TS). Don't
  promise it; list it under "ideas."

---

## Launch checklist

### Blockers (hours, not days)
- [ ] Add `LICENSE` (MIT recommended) + `license`/`readme`/`urls` in `pyproject.toml`
- [ ] Rename repo (fix "batter" typo; pick searchable name) + update README/clone URLs
- [ ] Replace real LAN IP in `.env.example`; move inline comments to their own lines
- [ ] Add `.dockerignore` (watch_dir, .git, .env, docs, caches)
- [ ] Apply REMEDIATION_PLAN Phase 1 (bitrate 4500 + VBV, drop `zerolatency`) and
      re-sync the README/PROGRESS parameter tables
- [ ] Fix SETUP.md port 8554→8654 (three places) and the blue/red→black drift
      everywhere (CLAUDE.md, ARCHITECTURE.md, SETUP.md, PROGRESS.md)

### Strongly recommended (a weekend)
- [ ] REMEDIATION_PLAN §2.1 (decoder stderr drain) and §2.2 (encoder supervision +
      stderr logging) — the two silent-hang modes strangers will hit
- [ ] Pin `mediamtx` and `pure-ftpd` image tags
- [ ] README: security notes (§4), Limitations section, web-UI screenshot, Frigate
      detect-resolution note
- [ ] Bind web UI to 127.0.0.1 by default (or document exposure clearly)
- [ ] Unit tests for params/validation/frame math + GitHub Actions (ruff + pytest +
      docker build)
- [ ] Commit the untracked docs; reorder PROGRESS.md chronologically
- [ ] `CONTRIBUTING.md` (dev setup, how to run tests, PR expectations) and issue
      templates (bug: ask for `docker compose logs`, camera model, resolution)

### High-leverage post-launch
- [ ] `GET /api/status` + status card in UI (§9.1)
- [ ] Embedded/linked MediaMTX live preview in the tuner (§9.2)
- [ ] Settings persistence (Plan §1.3) — until then, label the reset behavior
- [ ] Remaining REMEDIATION_PLAN Phases 2.3–4 (pacing drift, on_moved, pipe sizing,
      layer ordering, dir cleanup) + §6.5 jpg retention
- [ ] Startup validation of dimensions/FPS with named-variable error messages (§6.1–6.2)
- [ ] Graceful shutdown mid-clip (§6.3)
- [ ] Multi-camera support (PROGRESS Phase 4) — the most-requested feature this will
      get; the compose-duplication answer is fine for v1, design the real one later
