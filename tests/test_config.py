"""Config: env parsing and validation."""

import pytest

from reo_bridge.config import Config


def test_defaults():
    cfg = Config()
    assert cfg.stream_width == 2560
    assert cfg.stream_height == 1440
    assert cfg.stream_fps == 20
    assert cfg.delete_after_stream is False


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("STREAM_WIDTH", "1920")
    monkeypatch.setenv("STREAM_HEIGHT", "1080")
    monkeypatch.setenv("STREAM_FPS", "15")
    monkeypatch.setenv("DELETE_AFTER_STREAM", "true")
    monkeypatch.setenv("SETTLE_SECONDS", "0.5")
    cfg = Config()
    assert (cfg.stream_width, cfg.stream_height, cfg.stream_fps) == (1920, 1080, 15)
    assert cfg.delete_after_stream is True
    assert cfg.settle_seconds == 0.5


@pytest.mark.parametrize("value", ["abc", "20.5", ""])
def test_invalid_int_names_the_variable(monkeypatch, value):
    monkeypatch.setenv("STREAM_FPS", value)
    with pytest.raises(ValueError, match="STREAM_FPS"):
        Config()


def test_odd_dimensions_rejected(monkeypatch):
    monkeypatch.setenv("STREAM_WIDTH", "1919")
    with pytest.raises(ValueError, match="even"):
        Config()


def test_zero_fps_rejected(monkeypatch):
    monkeypatch.setenv("STREAM_FPS", "0")
    with pytest.raises(ValueError, match="STREAM_FPS"):
        Config()


def test_negative_settle_rejected(monkeypatch):
    monkeypatch.setenv("SETTLE_SECONDS", "-1")
    with pytest.raises(ValueError, match="SETTLE_SECONDS"):
        Config()
