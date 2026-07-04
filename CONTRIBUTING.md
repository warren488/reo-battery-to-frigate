# Contributing

Thanks for your interest! Bug reports, camera compatibility reports, and PRs are all
welcome.

## Development setup

```bash
git clone https://github.com/warren488/reolink-battery-frigate-bridge.git
cd reolink-battery-frigate-bridge

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Run the checks that CI runs:

```bash
ruff check src tests   # lint
pytest                 # tests (integration tests need ffmpeg on PATH)
```

To run the full stack locally:

```bash
cp .env.example .env   # then set FTP_PUBLIC_HOST to your LAN IP
docker compose up -d --build
./scripts/test-upload.sh   # sends a synthetic clip through the FTP → stream path
```

## Before opening a PR

- `ruff check` and `pytest` must pass (CI enforces both on Python 3.11 and 3.12).
- If you touched `src/reo_bridge/stream.py`, test with a real or generated clip —
  stream continuity and exact frame alignment are the invariants everything relies
  on (see `docs/ARCHITECTURE.md`).
- Add or update tests for behavior changes.
- Update `docs/PROGRESS.md` with a short entry for significant work.
- Keep commits focused; explain *why* in the commit message.

## Reporting bugs

Please include:

- Camera model and firmware, and whether it uploads standard or fragmented MP4
- Your `STREAM_WIDTH`/`STREAM_HEIGHT`/`STREAM_FPS` settings
- `docker compose logs reo-bridge` around the failure (encoder lines are prefixed
  with `encoder:`)
- What Frigate/VLC showed at the time

## Good first areas

- Camera compatibility reports (non-Reolink FTP cameras may work too)
- Multi-camera support (see `docs/PROGRESS.md` roadmap)
- Audio passthrough design (see the Limitations section of the README)
