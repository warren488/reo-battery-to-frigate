"""BridgeStatus: lifecycle and provider wiring."""

from reo_bridge.status import BridgeStatus


def test_initial_state():
    snap = BridgeStatus().snapshot()
    assert snap["state"] == "idle"
    assert snap["current_file"] is None
    assert snap["last_clip"] is None
    assert snap["uptime_seconds"] >= 0


def test_clip_lifecycle():
    st = BridgeStatus()
    st.clip_started("a.mp4")
    snap = st.snapshot()
    assert snap["state"] == "streaming"
    assert snap["current_file"] == "a.mp4"

    st.clip_finished("a.mp4", 120)
    snap = st.snapshot()
    assert snap["state"] == "idle"
    assert snap["current_file"] is None
    assert snap["last_clip"]["name"] == "a.mp4"
    assert snap["last_clip"]["frames"] == 120


def test_providers_feed_snapshot():
    st = BridgeStatus()
    st.set_providers(queue_depth=lambda: 3, encoder_alive=lambda: True)
    snap = st.snapshot()
    assert snap["queue_depth"] == 3
    assert snap["encoder_alive"] is True
