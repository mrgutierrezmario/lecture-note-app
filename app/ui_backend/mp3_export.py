"""Background MP3 assembly with progress, so the UI can show a spinner.

Building an MP3 means fetching every retained chunk from object storage and
running ffmpeg — seconds for a short recording, longer for a two-hour one.
``start`` kicks that off in a thread and returns immediately; ``status``
reports progress; ``wait`` blocks until the file exists. Finished files are
kept on disk for a while so a second download (or the History link right
after "prepare") is instant, and are invalidated when more chunks arrive.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field

from s3_client import s3_client

logger = logging.getLogger(__name__)

KEEP_SECONDS = 30 * 60  # how long a finished file stays available
FFMPEG_TIMEOUT = 900  # seconds; a multi-hour lecture takes a while to encode


@dataclass
class Job:
    """One MP3 build for a session, at a given chunk count."""

    session_id: str
    chunk_count: int
    filename: str
    status: str = "building"  # building | ready | error
    phase: str = "fetching"  # fetching | converting | done
    done: int = 0  # chunks fetched so far
    error: str | None = None
    path: str | None = None
    dir: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def progress(self) -> dict:
        """The status payload the API returns."""
        pct = 0
        if self.status == "ready":
            pct = 100
        elif self.chunk_count:
            # Fetching is quick; encoding dominates and has no fine-grained
            # progress, so fetching maps to 0–30% and converting parks at 60%.
            pct = 60 if self.phase == "converting" else int(self.done / self.chunk_count * 30)
        return {
            "status": self.status,
            "phase": self.phase,
            "percent": min(pct, 99) if self.status != "ready" else 100,
            "chunks_done": self.done,
            "chunks_total": self.chunk_count,
            "error": self.error,
            "filename": self.filename,
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _cleanup_old() -> None:
    """Drop finished jobs (and their files) older than KEEP_SECONDS."""
    now = time.time()
    for sid, job in list(_jobs.items()):
        if job.finished_at and now - job.finished_at > KEEP_SECONDS:
            if job.dir:
                shutil.rmtree(job.dir, ignore_errors=True)
            _jobs.pop(sid, None)


def _build(job: Job, keys: list[str]) -> None:
    """Thread body: fetch chunks, concatenate, encode."""
    try:
        job.dir = tempfile.mkdtemp(prefix="mp3-")
        combined = os.path.join(job.dir, "combined.webm")
        with open(combined, "wb") as f:
            for key in keys:
                f.write(s3_client.download_chunk(key))
                job.done += 1
        job.phase = "converting"
        out = os.path.join(job.dir, "recording.mp3")
        # Speech: mono at 80 kbps is transparent and a third the size of 192k stereo.
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", combined, "-ar", "44100", "-ac", "1", "-b:a", "80k", out],
            capture_output=True,
            timeout=FFMPEG_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode()[-300:])
        os.unlink(combined)
        job.path = out
        job.phase = "done"
        job.status = "ready"
    except Exception as e:  # noqa: BLE001 — any failure is reported to the UI
        job.status = "error"
        job.error = str(e)[:300]
        logger.error("MP3 build failed for %s: %s", job.session_id, e)
    finally:
        job.finished_at = time.time()


def start(session_id: str, keys: list[str], filename: str) -> Job:
    """Start a build unless a matching one exists (same chunk count, not failed)."""
    with _lock:
        _cleanup_old()
        job = _jobs.get(session_id)
        if job and job.chunk_count == len(keys) and job.status != "error":
            return job
        if job and job.dir:
            shutil.rmtree(job.dir, ignore_errors=True)
        job = Job(session_id=session_id, chunk_count=len(keys), filename=filename)
        _jobs[session_id] = job
        threading.Thread(target=_build, args=(job, keys), daemon=True).start()
        return job


def status(session_id: str) -> Job | None:
    """The current job for a session, if any."""
    return _jobs.get(session_id)


async def wait(job: Job, timeout: float = FFMPEG_TIMEOUT + 60) -> Job:
    """Await completion without blocking the event loop."""
    deadline = time.time() + timeout
    while job.status == "building" and time.time() < deadline:
        await asyncio.sleep(0.5)
    return job
