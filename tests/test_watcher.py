"""Watcher: settle detection, rename handling, and dedupe."""

import queue
import time
from pathlib import Path

import pytest

from reo_bridge.config import Config
from reo_bridge.streaming_params import StreamingParams
from reo_bridge.watcher import _VideoFileHandler


@pytest.fixture
def fast_config(monkeypatch):
    monkeypatch.setenv("SETTLE_SECONDS", "0.05")
    return Config()


@pytest.fixture
def handler_and_queue(fast_config):
    q: queue.Queue[Path] = queue.Queue()
    handler = _VideoFileHandler(fast_config, q, StreamingParams())
    return handler, q


def test_stable_file_is_queued(handler_and_queue, tmp_path):
    handler, q = handler_and_queue
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x" * 1000)

    handler._handle_new_file(clip)
    assert q.get(timeout=5) == clip


def test_growing_file_waits_until_stable(monkeypatch, tmp_path):
    # Settle interval (0.3s) is much longer than the growth interval (0.05s)
    # so the size cannot appear stable while the file is still growing.
    monkeypatch.setenv("SETTLE_SECONDS", "0.3")
    q: queue.Queue[Path] = queue.Queue()
    handler = _VideoFileHandler(Config(), q, StreamingParams())

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x" * 100)

    handler._handle_new_file(clip)
    for _ in range(3):
        time.sleep(0.05)
        with clip.open("ab") as f:
            f.write(b"y" * 100)

    queued = q.get(timeout=5)
    assert queued == clip
    # By the time it was queued the file must have stopped growing
    assert clip.stat().st_size == 400


def test_non_video_suffix_ignored(handler_and_queue, tmp_path):
    handler, q = handler_and_queue
    snap = tmp_path / "snapshot.jpg"
    snap.write_bytes(b"x" * 100)

    handler._handle_new_file(snap)
    time.sleep(0.2)
    assert q.empty()


def test_duplicate_events_queue_once(handler_and_queue, tmp_path):
    handler, q = handler_and_queue
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x" * 1000)

    # Simulates FTP create-then-rename arriving as two events for one file
    handler._handle_new_file(clip)
    handler._handle_new_file(clip)

    assert q.get(timeout=5) == clip
    time.sleep(0.3)
    assert q.empty()


def test_vanished_file_not_queued(handler_and_queue, tmp_path):
    handler, q = handler_and_queue
    handler._handle_new_file(tmp_path / "gone.mp4")
    time.sleep(0.3)
    assert q.empty()
