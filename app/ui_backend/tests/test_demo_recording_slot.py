"""The shared demo account records one lecture at a time (one Whisper stream on
the host), however many visitors are using it."""

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
