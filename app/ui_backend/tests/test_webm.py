"""Slicing the WebM header out of MediaRecorder's first blob."""

from realtime.websocket_handler import _CLUSTER_ID, _EBML_MAGIC, _webm_header


def test_header_is_everything_before_the_first_cluster():
    blob = _EBML_MAGIC + b"\x00" * 40 + _CLUSTER_ID + b"audio-bytes" + _CLUSTER_ID + b"more"
    header = _webm_header(blob)
    assert header == _EBML_MAGIC + b"\x00" * 40
    assert _CLUSTER_ID not in header


def test_blob_without_cluster_is_used_whole():
    blob = _EBML_MAGIC + b"\x01\x02\x03"
    assert _webm_header(blob) == blob


# ── WebmStream: blobs cut mid-element still decode to all of their audio ──────

from realtime.webm_stream import WebmStream  # noqa: E402

HEADER = _EBML_MAGIC + b"\x80"  # EBML element, empty — stands in for the real header


def _cluster(tc: int) -> bytes:
    return _CLUSTER_ID + b"\x01\xff\xff\xff\xff\xff\xff\xff" + b"\xe7\x82" + tc.to_bytes(2, "big")


def _block(n: int) -> bytes:
    payload = b"\x81\x00" + bytes([n]) + b"\x80" + bytes([n]) * 10
    return b"\xa3" + bytes([0x80 | len(payload)]) + payload


def test_blob_cut_mid_block_is_reframed_behind_a_cluster():
    stream_bytes = HEADER + _cluster(1000) + _block(1) + _block(2) + _block(3) + _block(4)
    cut = len(HEADER) + len(_cluster(1000)) + len(_block(1)) + 5  # inside block 2
    first, second = stream_bytes[:cut], stream_bytes[cut:]

    stream = WebmStream(_webm_header(first))
    assert stream.feed(first) == first  # the first blob decodes as-is
    out = stream.feed(second)
    # Block 2 is carried over whole, behind a Cluster at the running timecode.
    assert out == HEADER + _cluster(1000) + _block(2) + _block(3) + _block(4)


def test_new_cluster_in_a_blob_updates_the_timecode():
    first = HEADER + _cluster(0) + _block(1)
    stream = WebmStream(_webm_header(first))
    stream.feed(first)
    stream.feed(_block(2) + _cluster(5040) + _block(3)[:4])
    assert stream.cluster_tc == 5040
    out = stream.feed(_block(3)[4:] + _block(4))
    assert out == HEADER + _cluster(5040) + _block(3) + _block(4)


def test_garbage_falls_back_to_header_plus_blob_and_resyncs():
    first = HEADER + _cluster(0) + _block(1)
    stream = WebmStream(_webm_header(first))
    stream.feed(first)
    junk = b"\x00\x00\x00"
    assert stream.feed(junk) == HEADER + junk
    assert stream.cluster_tc is None
    nxt = b"\x00" + _cluster(7000) + _block(2)
    assert stream.feed(nxt) == HEADER + nxt
    assert stream.cluster_tc == 7000


def test_continuation_without_a_stream_uses_the_recovered_header():
    stream = WebmStream(HEADER)  # header recovered from storage after a reconnect
    blob = _block(1)[3:] + _cluster(2000) + _block(2)
    assert stream.feed(blob) == HEADER + blob
    assert stream.feed(_block(3)) == HEADER + _cluster(2000) + _block(3)
