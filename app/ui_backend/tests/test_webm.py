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
