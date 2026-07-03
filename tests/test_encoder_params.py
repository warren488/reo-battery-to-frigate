"""EncoderParams: FFmpeg argument generation and thread-safe updates."""

import pytest

from reo_bridge.encoder_params import EncoderParams


def test_default_args_cbr_with_vbv():
    args = EncoderParams().ffmpeg_args()
    joined = " ".join(args)
    assert "-b:v 4500k" in joined
    # VBV must be present — this is the bottom-of-frame artifacting fix
    assert "-maxrate 4500k" in joined
    assert "-bufsize 9000k" in joined
    # Default tune is "none": no -tune flag at all
    assert "-tune" not in args


def test_crf_mode_is_capped():
    p = EncoderParams()
    p.update(rate_mode="crf", crf=21)
    joined = " ".join(p.ffmpeg_args())
    assert "-crf 21" in joined
    assert "-b:v" not in joined
    # bitrate_kbps acts as the ceiling in CRF mode
    assert "-maxrate 4500k" in joined
    assert "-bufsize 9000k" in joined


def test_explicit_tune_is_emitted():
    p = EncoderParams()
    p.update(tune="zerolatency")
    args = p.ffmpeg_args()
    assert args[args.index("-tune") + 1] == "zerolatency"


def test_update_bumps_version():
    p = EncoderParams()
    v0 = p.version
    p.update(bitrate_kbps=3000)
    assert p.version == v0 + 1
    p.update(bitrate_kbps=3000, preset="veryfast")
    assert p.version == v0 + 2


def test_update_rejects_unknown_key():
    p = EncoderParams()
    with pytest.raises(ValueError, match="unknown_key"):
        p.update(unknown_key=1)


def test_update_rejects_private_key():
    p = EncoderParams()
    with pytest.raises(ValueError):
        p.update(_version=99)


def test_snapshot_matches_values():
    p = EncoderParams()
    p.update(preset="fast", gop_frames=60)
    snap = p.snapshot()
    assert snap["preset"] == "fast"
    assert snap["gop_frames"] == 60
    assert snap["version"] == p.version
