"""Persistence: round-trips and fail-soft behavior."""

from pathlib import Path

from reo_bridge.persistence import load_params, save_params


def test_round_trip(tmp_path):
    path = tmp_path / "params.json"
    data = {"encoder": {"bitrate_kbps": 6000}, "streaming": {"realtime_streaming": True}}
    save_params(path, data)
    assert load_params(path) == data


def test_missing_file_returns_empty(tmp_path):
    assert load_params(tmp_path / "nope.json") == {}


def test_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "params.json"
    path.write_text("{not json!!")
    assert load_params(path) == {}


def test_non_object_json_returns_empty(tmp_path):
    path = tmp_path / "params.json"
    path.write_text("[1, 2, 3]")
    assert load_params(path) == {}


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "deep" / "nested" / "params.json"
    save_params(path, {"encoder": {}})
    assert path.exists()


def test_save_to_unwritable_path_does_not_raise():
    save_params(Path("/proc/definitely/not/writable/params.json"), {"a": 1})


def test_save_is_atomic_no_tmp_left_behind(tmp_path):
    path = tmp_path / "params.json"
    save_params(path, {"a": 1})
    leftovers = [p for p in tmp_path.iterdir() if p.name != "params.json"]
    assert leftovers == []
