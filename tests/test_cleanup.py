"""DELETE_AFTER_STREAM cleanup: snapshots and empty date directories."""

from reo_bridge.config import Config
from reo_bridge.main import _cleanup_streamed_file


def _nested(tmp_path):
    d = tmp_path / "2026" / "07" / "03"
    d.mkdir(parents=True)
    return d


def test_removes_clip_snapshots_and_empty_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCH_DIR", str(tmp_path))
    cfg = Config()
    d = _nested(tmp_path)
    clip = d / "cam_001.mp4"
    snap = d / "cam_002.jpg"  # snapshots have their own timestamps
    clip.write_bytes(b"x")
    snap.write_bytes(b"x")

    _cleanup_streamed_file(cfg, clip)

    assert not clip.exists()
    assert not snap.exists()
    assert not (tmp_path / "2026").exists()  # empty date tree pruned
    assert tmp_path.exists()  # watch dir itself never removed


def test_keeps_dirs_with_remaining_clips(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCH_DIR", str(tmp_path))
    cfg = Config()
    d = _nested(tmp_path)
    clip = d / "cam_001.mp4"
    pending = d / "cam_003.mp4"  # still queued — must survive
    clip.write_bytes(b"x")
    pending.write_bytes(b"x")

    _cleanup_streamed_file(cfg, clip)

    assert not clip.exists()
    assert pending.exists()
    assert d.exists()


def test_missing_file_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCH_DIR", str(tmp_path))
    cfg = Config()
    d = _nested(tmp_path)
    _cleanup_streamed_file(cfg, d / "already_gone.mp4")
    assert not (tmp_path / "2026").exists()
