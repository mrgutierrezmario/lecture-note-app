"""The shared demo account records one lecture at a time (one Whisper stream on
the host), however many visitors are using it."""

import asyncio

from realtime import websocket_handler as wh
from realtime.websocket_handler import ConnectionManager


def _open(m, session_id):
    m.active_connections.setdefault(session_id, []).append(object())


def test_second_demo_recording_is_refused_until_the_first_stops():
    m = ConnectionManager()
    _open(m, "a")
    _open(m, "b")
    assert m.claim_demo_recording("a")
    assert m.claim_demo_recording("a")  # the holder may start/resume again
    assert not m.claim_demo_recording("b")
    m.release_demo_recording("b")  # a non-holder can't free it
    assert not m.claim_demo_recording("b")
    m.release_demo_recording("a")  # "stop"
    assert m.claim_demo_recording("b")


def test_closing_the_last_socket_frees_the_slot():
    m = ConnectionManager()
    ws = object()
    m.active_connections["a"] = [ws]
    assert m.claim_demo_recording("a")
    m.disconnect(ws, "a")
    _open(m, "b")
    assert m.claim_demo_recording("b")


def test_a_holder_with_no_sockets_left_does_not_block():
    m = ConnectionManager()
    m.demo_recording = "gone"  # e.g. its socket vanished without a clean close
    _open(m, "b")
    assert m.claim_demo_recording("b")


# ── Demo recording limits: minutes per lecture, recorded lectures kept ───────


class _FakeDB:
    """Stands in for AsyncSessionLocal(): scalar() returns a fixed count."""

    def __init__(self, count):
        self.count = count

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def scalar(self, _query):
        return self.count


def _refusal(monkeypatch, chunk_index, recorded=0, minutes=40, max_recordings=3):
    monkeypatch.setattr(wh.settings, "demo_max_recording_minutes", minutes)
    monkeypatch.setattr(wh.settings, "demo_max_recordings", max_recordings)
    monkeypatch.setattr(wh, "AsyncSessionLocal", lambda: _FakeDB(recorded))
    return asyncio.run(wh._demo_start_refusal("s1", "demo-user", chunk_index))


def test_forty_minutes_is_480_five_second_chunks(monkeypatch):
    monkeypatch.setattr(wh.settings, "demo_max_recording_minutes", 40)
    assert wh._demo_chunk_cap() == 480


def test_new_recording_allowed_under_the_lecture_cap(monkeypatch):
    assert _refusal(monkeypatch, chunk_index=0, recorded=2) is None


def test_fourth_recorded_lecture_is_refused(monkeypatch):
    r = _refusal(monkeypatch, chunk_index=0, recorded=3)
    assert r["type"] == "recording_refused" and r["stop"] is True
    assert r["title"] == "Demo Recording Limit"
    assert "3 recorded lectures" in r["message"]


def test_continuing_a_lecture_is_not_counted_as_a_new_one(monkeypatch):
    # Resuming lecture #3 mid-way must work even with 3 lectures on record.
    assert _refusal(monkeypatch, chunk_index=10, recorded=3) is None


def test_resume_after_forty_minutes_is_refused(monkeypatch):
    r = _refusal(monkeypatch, chunk_index=480)
    assert r["title"] == "Demo Time Limit"
    assert "40 minutes" in r["message"]
    assert _refusal(monkeypatch, chunk_index=479) is None


def test_zero_means_no_limit(monkeypatch):
    r = _refusal(monkeypatch, chunk_index=10_000, recorded=99, minutes=0, max_recordings=0)
    assert r is None
