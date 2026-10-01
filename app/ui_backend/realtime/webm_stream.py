"""Re-frame MediaRecorder's WebM blobs so each one decodes to all of its audio.

MediaRecorder cuts blobs on a timer, not on Matroska element boundaries: a blob
usually starts partway through a Cluster (often in the middle of a SimpleBlock).
Decoding ``header + blob`` makes ffmpeg skip everything up to the blob's first
Cluster. Normally that is ~0.1 s, but pause/resume shifts where Clusters start,
and after one Cluster began ~4.6 s into every blob, so each 5 s chunk
transcribed as 0.36 s.

``WebmStream`` walks the stream element by element. Each blob comes out as
header + a synthetic Cluster (carrying the running Cluster timecode) + every
complete element; a trailing partial element is held and prepended to the next
blob. If the bytes stop parsing, it falls back to ``header + blob`` and resyncs
at the next Cluster.
"""

import logging

logger = logging.getLogger(__name__)

EBML_MAGIC = b"\x1a\x45\xdf\xa3"
CLUSTER_ID = b"\x1f\x43\xb6\x75"
_TIMECODE_ID = b"\xe7"
_UNKNOWN_SIZE = b"\x01\xff\xff\xff\xff\xff\xff\xff"
# Anything larger than this inside a Cluster means we are not on an element boundary.
_MAX_ELEMENT = 4 * 1024 * 1024


def _read_vint(buf: bytes, pos: int, keep_marker: bool) -> tuple[int, int] | None:
    """Parse an EBML variable-length integer at ``pos``.

    Returns ``(value, length)``, ``None`` when the buffer ends mid-vint, and
    raises ``ValueError`` for a byte that cannot start a vint. An all-ones size
    ("unknown size") is returned as -1.
    """
    if pos >= len(buf):
        return None
    first = buf[pos]
    if first == 0:
        raise ValueError("invalid vint")
    length = 8 - first.bit_length() + 1
    if pos + length > len(buf):
        return None
    raw = buf[pos : pos + length]
    if keep_marker:
        return int.from_bytes(raw, "big"), length
    value = int.from_bytes(raw, "big") & ((1 << (7 * length)) - 1)
    if value == (1 << (7 * length)) - 1:
        value = -1
    return value, length


def _cluster_prefix(timecode: int) -> bytes:
    """A Cluster header of unknown size, opened at ``timecode``."""
    tc = timecode.to_bytes(max(1, (timecode.bit_length() + 7) // 8), "big")
    return CLUSTER_ID + _UNKNOWN_SIZE + _TIMECODE_ID + bytes([0x80 | len(tc)]) + tc


class WebmStream:
    """Per-session state turning MediaRecorder blobs into decodable WebM."""

    def __init__(self, header: bytes):
        """Start unsynced; the first blob with a Cluster syncs the stream."""
        self.header = header
        self.pending = b""
        self.cluster_tc: int | None = None  # None = not synced to the element stream

    def feed(self, blob: bytes) -> bytes:
        """Return the bytes to decode for ``blob`` (a whole WebM file)."""
        if self.cluster_tc is None:
            return self._resync(blob)
        start_tc = self.cluster_tc
        try:
            body, self.pending = self._walk(self.pending + blob)
        except ValueError as e:
            logger.warning("WebM stream lost sync (%s); resyncing at next Cluster", e)
            self.cluster_tc = None
            self.pending = b""
            return self._resync(blob)
        if body.startswith(CLUSTER_ID):
            return self.header + body
        return self.header + _cluster_prefix(start_tc) + body

    def _resync(self, blob: bytes) -> bytes:
        """Old behaviour for this blob, and pick up the element stream at its first Cluster."""
        idx = blob.find(CLUSTER_ID)
        if idx != -1:
            try:
                _, self.pending = self._walk(blob[idx:])
            except ValueError:
                self.cluster_tc = None
                self.pending = b""
        return blob if blob.startswith(EBML_MAGIC) else self.header + blob

    def _walk(self, buf: bytes) -> tuple[bytes, bytes]:
        """Split ``buf`` into (complete elements, trailing partial element).

        Updates ``cluster_tc`` from every Cluster Timecode it passes. Clusters
        are descended into (their header alone is one "element").
        """
        pos = 0
        while pos < len(buf):
            elem_id = _read_vint(buf, pos, keep_marker=True)
            if elem_id is None:
                break
            size = _read_vint(buf, pos + elem_id[1], keep_marker=False)
            if size is None:
                break
            head = elem_id[1] + size[1]
            id_bytes = buf[pos : pos + elem_id[1]]
            if id_bytes == CLUSTER_ID:
                pos += head  # descend: children follow
                if self.cluster_tc is None:
                    self.cluster_tc = 0
                continue
            if size[0] < 0 or size[0] > _MAX_ELEMENT:
                raise ValueError(f"implausible element size {size[0]}")
            end = pos + head + size[0]
            if end > len(buf):
                break
            if id_bytes == _TIMECODE_ID:
                self.cluster_tc = int.from_bytes(buf[pos + head : end], "big")
            pos = end
        return buf[:pos], buf[pos:]
