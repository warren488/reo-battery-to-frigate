"""Web API: validation, updates, and persistence wiring."""

import json

import pytest

from reo_bridge import web
from reo_bridge.config import Config
from reo_bridge.encoder_params import EncoderParams
from reo_bridge.streaming_params import StreamingParams


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PARAMS_FILE", str(tmp_path / "params.json"))
    app = web.init_app(Config(), EncoderParams(), StreamingParams())
    app.config["TESTING"] = True
    return app.test_client()


def test_get_encoder(client):
    data = client.get("/api/encoder").get_json()
    assert data["bitrate_kbps"] == 4500
    assert data["tune"] == "none"


def test_get_config(client):
    data = client.get("/api/config").get_json()
    assert data["stream_width"] == 2560
    assert "rtsp_output_url" in data


def test_get_options_includes_none_tune(client):
    data = client.get("/api/options").get_json()
    assert "none" in data["tunes"]
    assert data["rate_modes"] == ["cbr", "crf"]


def test_post_encoder_updates_and_persists(client, tmp_path):
    res = client.post("/api/encoder", json={"bitrate_kbps": 6000, "preset": "veryfast"})
    assert res.status_code == 200
    assert res.get_json()["bitrate_kbps"] == 6000

    saved = json.loads((tmp_path / "params.json").read_text())
    assert saved["encoder"]["bitrate_kbps"] == 6000
    assert "version" not in saved["encoder"]


def test_post_encoder_rejects_bad_preset(client):
    res = client.post("/api/encoder", json={"preset": "warp-speed"})
    assert res.status_code == 400
    assert any("preset" in e for e in res.get_json()["errors"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bitrate_kbps", 50),
        ("bitrate_kbps", 999999),
        ("bitrate_kbps", "fast"),
        ("crf", 99),
        ("gop_frames", 0),
        ("audio_bitrate_kbps", 1),
        ("rate_mode", "vbr"),
        ("tune", "bogus"),
    ],
)
def test_post_encoder_rejects_out_of_range(client, field, value):
    res = client.post("/api/encoder", json={field: value})
    assert res.status_code == 400


def test_post_streaming_updates(client):
    res = client.post(
        "/api/streaming",
        json={"realtime_streaming": True, "realtime_delay_seconds": 2.5},
    )
    assert res.status_code == 200
    data = client.get("/api/streaming").get_json()
    assert data["realtime_streaming"] is True
    assert data["realtime_delay_seconds"] == 2.5


def test_post_streaming_rejects_bad_delay(client):
    res = client.post("/api/streaming", json={"realtime_delay_seconds": 9999})
    assert res.status_code == 400


def test_index_serves_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"Stream Tuner" in res.data
