"""The recording WebSocket: audio in, transcript and notes out.

Protocol (one socket per lecture, path ``/ws/session/{session_id}``):

* Browser → server, JSON text frames: ``{"type": "start", "title", "save_storage"}``,
  ``{"type": "stop"}``, ``{"type": "ping"}``.
* Browser → server, binary frames: 5-second WebM/Opus chunks from
  ``MediaRecorder``. Only the first chunk carries the container header, so it
  is kept (trimmed to the metadata prefix) and prepended to every later chunk
  before decoding.
* Server → browser, JSON: ``transcript_delta``, ``notes_update``, ``status``,
  ``quota_exceeded`` and ``pong``.

Each chunk is stored in object storage, transcribed by Whisper, and its
segments are broadcast to every socket open on the session. A background task
regenerates the notes every ``notes_interval_seconds`` while a socket is open.
"""

import asyncio
import json
import logging
import uuid as uuid_module

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import google_drive
import quota
from auth import websocket_user
from config import get_settings
from database import AsyncSessionLocal
from models import AudioChunk, Session, TranscriptSegment
from notes_generator import generate_notes_for_session
from s3_client import s3_client
from transcriber import reset_session as reset_transcriber_session
from transcriber import transcribe_chunk

logger = logging.getLogger(__name__)
settings = get_settings()

# MediaRecorder's first chunk of a stream starts with the EBML header; every later
# chunk is a continuation segment that only decodes with that header prepended.
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"
# Matroska Cluster element ID: audio starts here. Everything before the first
# Cluster (EBML header, Segment, Info, Tracks) is the metadata later chunks need.
_CLUSTER_ID = b"\x1f\x43\xb6\x75"


def _webm_header(first_chunk: bytes) -> bytes:
    """The decodable metadata prefix of a MediaRecorder stream's first blob.

    The first blob is header *and* ~5 s of audio. Prepending the whole blob to
    every later chunk meant each one decoded as [first 5 s] + [new 5 s], so
    Whisper re-transcribed the opening sentence on every chunk. Cut at the
    first Cluster so later chunks decode to their own audio only.
    """
    idx = first_chunk.find(_CLUSTER_ID)
    if idx <= 0:
        logger.warning("No Cluster element found in first webm chunk; using whole chunk as header")
        return first_chunk
    return first_chunk[:idx]


# Sessions whose header could not be read back from object storage. Without this,
# an unrecoverable session would re-query Postgres and S3 every 5 seconds.
_header_recovery_failed: set[str] = set()


async def _recover_webm_header(session_id: str) -> bytes | None:
    """Re-read a session's EBML header from object storage.

    ``manager.webm_headers`` is memory-only, and it is dropped both on backend
    restart and whenever the last socket for a session closes. A browser that
    reconnects mid-stream therefore sends continuation chunks with no header
    available, and every one of them fails to decode for the rest of the
    recording. Chunk 0 is still in object storage unless retention removed it,
    so recover the header from there rather than losing the session.
    """
    if session_id in _header_recovery_failed:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AudioChunk).where(
                AudioChunk.session_id == session_id,
                AudioChunk.chunk_index == 0,
            )
        )
        chunk = result.scalar_one_or_none()

    if chunk is None or not chunk.s3_key or chunk.deleted_from_s3:
        reason = (
            "was never stored"
            if chunk is None or not chunk.s3_key
            else "was already deleted from storage"
        )
        logger.warning(
            "Cannot recover webm header for session %s: chunk 0 %s. "
            "Audio will not transcribe until recording is restarted.",
            session_id,
            reason,
        )
        _header_recovery_failed.add(session_id)
        return None

    try:
        # boto3 is synchronous; keep it off the event loop.
        data = await asyncio.to_thread(s3_client.download_chunk, chunk.s3_key)
    except Exception as e:
        logger.error("Failed to download chunk 0 for session %s: %s", session_id, e)
        _header_recovery_failed.add(session_id)
        return None

    if data[:4] != _EBML_MAGIC:
        logger.warning("Stored chunk 0 for session %s carries no EBML header", session_id)
        _header_recovery_failed.add(session_id)
        return None

    logger.info("Recovered webm header for session %s from object storage", session_id)
    return _webm_header(data)


class ConnectionManager:
    """Per-session bookkeeping for open sockets and in-flight recordings.

    One instance for the process (``manager``). Everything here is memory
    only and is dropped when the last socket for a session closes.
    """

    def __init__(self):
        """Create empty per-session tables."""
        self.active_connections: dict[str, list[WebSocket]] = {}
        self.notes_tasks: dict[str, asyncio.Task] = {}
        self.webm_headers: dict[str, bytes] = {}
        self.save_storage: dict[str, bool] = {}
        # session -> [used_bytes, quota_bytes]; quota 0 = unlimited
        self.quota: dict[str, list[int]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept a socket and register it under its session."""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        logger.info(f"WebSocket connected for session {session_id}")

    def disconnect(self, websocket: WebSocket, session_id: str):
        """Unregister a socket; when the last one goes, stop the notes loop and drop state."""
        if session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
                if session_id in self.notes_tasks:
                    self.notes_tasks[session_id].cancel()
                    del self.notes_tasks[session_id]
                self.webm_headers.pop(session_id, None)
                self.save_storage.pop(session_id, None)
                self.quota.pop(session_id, None)
                reset_transcriber_session(session_id)
        logger.info(f"WebSocket disconnected for session {session_id}")

    async def broadcast(self, session_id: str, message: dict):
        """Send a JSON message to every socket on a session, pruning dead ones."""
        if session_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.append(connection)
            for conn in disconnected:
                self.disconnect(conn, session_id)

    def start_notes_task(self, session_id: str):
        """Start the periodic notes generator for a session (idempotent)."""
        if session_id not in self.notes_tasks or self.notes_tasks[session_id].done():
            self.notes_tasks[session_id] = asyncio.create_task(
                self._notes_generation_loop(session_id)
            )

    async def _notes_generation_loop(self, session_id: str):
        """Regenerate notes on a timer for as long as the session has a socket."""
        while session_id in self.active_connections:
            await asyncio.sleep(settings.notes_interval_seconds)
            try:
                async with AsyncSessionLocal() as db:
                    await generate_notes_for_session(
                        db,
                        session_id,
                        broadcast_callback=self.broadcast,
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Notes generation error for {session_id}: {e}")


manager = ConnectionManager()


async def ensure_session_exists(db: AsyncSession, session_id: str, user_id=None) -> Session:
    """Create the session row on first contact (no-op if it exists).

    ``on_conflict_do_nothing`` keeps the original owner when a browser
    reconnects to an existing session.
    """
    # on_conflict_do_nothing keeps the original owner on reconnect.
    stmt = pg_insert(Session).values(id=session_id, user_id=user_id).on_conflict_do_nothing()
    await db.execute(stmt)
    await db.commit()

    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one()
    logger.info(f"Ensured session exists: {session_id}")
    return session


async def handle_websocket(websocket: WebSocket, session_id: str):
    """Serve one recording socket for its whole lifetime.

    Rejects users who don't own the session, then loops over frames: JSON
    control messages are handled inline; each binary audio chunk is
    dispatched to ``process_audio_chunk`` as a task so the receive loop never
    stalls. Enforces the storage quota at start and as chunks arrive.
    """
    user = websocket_user(websocket)
    if user is None:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, session_id)

    chunk_index = 0

    async with AsyncSessionLocal() as db:
        session = await ensure_session_exists(db, session_id, user.id)
        if not user.is_admin and session.user_id != user.id:
            logger.warning(
                "User %s tried to join session %s owned by someone else", user.username, session_id
            )
            await websocket.close(code=1008)
            return

        existing_chunks = await db.execute(
            select(AudioChunk)
            .where(AudioChunk.session_id == session_id)
            .order_by(AudioChunk.chunk_index.desc())
            .limit(1)
        )
        last_chunk = existing_chunks.scalar_one_or_none()
        if last_chunk:
            chunk_index = last_chunk.chunk_index + 1

    await manager.broadcast(
        session_id,
        {
            "type": "status",
            "message": f"Connected to session: {session_id}",
        },
    )

    try:
        while True:
            data = await websocket.receive()

            if "text" in data:
                try:
                    message = json.loads(data["text"])
                    msg_type = message.get("type")

                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})

                    elif msg_type == "start":
                        title = message.get("title")
                        manager.save_storage[session_id] = bool(message.get("save_storage", False))

                        async with AsyncSessionLocal() as db:
                            used, limit, over = await quota.status(db, user.id)
                        manager.quota[session_id] = [used, limit]
                        if over and not manager.save_storage[session_id]:
                            await websocket.send_json(
                                {
                                    "type": "quota_exceeded",
                                    "stop": True,
                                    "used_bytes": used,
                                    "quota_bytes": limit,
                                    "message": (
                                        f"Storage quota reached ({used // quota.MB} of "
                                        f"{limit // quota.MB} MB of audio). Delete audio from old "
                                        "lectures in History, or turn on 'Don't keep audio' to "
                                        "record without keeping the recording."
                                    ),
                                }
                            )
                            continue
                        if title:
                            async with AsyncSessionLocal() as db:
                                result = await db.execute(
                                    select(Session).where(Session.id == session_id)
                                )
                                session = result.scalar_one_or_none()
                                if session:
                                    session.title = title
                                    await db.commit()

                        reset_transcriber_session(session_id)
                        manager.start_notes_task(session_id)

                        await manager.broadcast(
                            session_id,
                            {
                                "type": "status",
                                "message": "Recording started",
                            },
                        )

                    elif msg_type == "stop":
                        async with AsyncSessionLocal() as db:
                            await generate_notes_for_session(
                                db,
                                session_id,
                                broadcast_callback=manager.broadcast,
                            )

                        await manager.broadcast(
                            session_id,
                            {
                                "type": "status",
                                "message": "Recording stopped",
                            },
                        )
                        # Owner opted in to "save to my Google Drive after each lecture".
                        asyncio.create_task(google_drive.auto_export(session_id))

                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON")

            elif data.get("type") == "websocket.disconnect":
                break

            elif "bytes" in data:
                audio_data = data["bytes"]
                current_index = chunk_index
                chunk_index += 1

                # On reconnect (backend restart, dropped socket, React StrictMode
                # double-mount) the "first" chunk on the new socket is actually a
                # continuation segment — detect that by the EBML magic bytes and
                # recover the header from object storage rather than dropping the
                # rest of the recording.
                has_ebml_header = audio_data[:4] == _EBML_MAGIC

                if has_ebml_header:
                    manager.webm_headers[session_id] = _webm_header(audio_data)
                    _header_recovery_failed.discard(session_id)
                    data_to_transcribe = audio_data
                else:
                    header = manager.webm_headers.get(session_id)
                    if header is None:
                        header = await _recover_webm_header(session_id)
                        if header:
                            manager.webm_headers[session_id] = header
                    data_to_transcribe = header + audio_data if header else audio_data

                # A reconnect cancels the notes loop (last socket closed) and the
                # browser keeps streaming without re-sending "start" — so make
                # the loop self-healing: audio arriving means we are recording.
                manager.start_notes_task(session_id)

                q = manager.quota.get(session_id)
                if q and q[1] and not manager.save_storage.get(session_id, False):
                    q[0] += len(audio_data)
                    if q[0] >= q[1]:
                        # Keep transcribing; just stop retaining audio from here on.
                        manager.save_storage[session_id] = True
                        logger.info(
                            "Session %s hit the storage quota mid-recording; audio no longer kept",
                            session_id,
                        )
                        await manager.broadcast(
                            session_id,
                            {
                                "type": "quota_exceeded",
                                "stop": False,
                                "used_bytes": q[0],
                                "quota_bytes": q[1],
                                "message": (
                                    f"Storage quota reached ({q[1] // quota.MB} MB). The "
                                    "transcript continues, but audio from this point is not "
                                    "kept. Delete audio from old lectures in History to free "
                                    "space."
                                ),
                            },
                        )

                asyncio.create_task(
                    process_audio_chunk(
                        session_id,
                        current_index,
                        audio_data,
                        data_to_transcribe,
                        manager.save_storage.get(session_id, False),
                    )
                )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
    finally:
        manager.disconnect(websocket, session_id)


async def process_audio_chunk(
    session_id: str,
    chunk_index: int,
    audio_data: bytes,
    data_to_transcribe: bytes | None = None,
    save_storage: bool = False,
):
    """Store, transcribe and broadcast one audio chunk.

    Records an ``AudioChunk`` row, uploads the bytes, runs transcription on
    the header-prefixed data, saves the resulting segments and pushes them to
    the browser. In "don't keep audio" mode the object is deleted right after
    a successful transcription.
    """
    loop = asyncio.get_running_loop()
    audio_chunk = None

    async with AsyncSessionLocal() as db:
        try:
            # Insert the row before uploading, so an upload failure still has a
            # record to report itself on.
            audio_chunk = AudioChunk(
                session_id=session_id,
                chunk_index=chunk_index,
                size_bytes=len(audio_data),
            )
            db.add(audio_chunk)
            await db.commit()

            # boto3 is synchronous: run it off the event loop, or each upload
            # stalls the receive loop and every broadcast, for every session.
            s3_key = await loop.run_in_executor(
                None, s3_client.upload_chunk, session_id, chunk_index, audio_data
            )
            audio_chunk.s3_bucket = settings.s3_bucket
            audio_chunk.s3_key = s3_key
            await db.commit()

            decode_ok, transcribed_ok, segments, error = await transcribe_chunk(
                data_to_transcribe or audio_data, session_id
            )

            audio_chunk.decode_ok = decode_ok
            audio_chunk.transcribed_ok = transcribed_ok
            audio_chunk.error = error

            for seg in segments:
                segment_id = uuid_module.uuid4()
                segment = TranscriptSegment(
                    id=segment_id,
                    session_id=session_id,
                    chunk_index=chunk_index,
                    ts_start=seg["ts_start"],
                    ts_end=seg["ts_end"],
                    text=seg["text"],
                )
                db.add(segment)

                await manager.broadcast(
                    session_id,
                    {
                        "type": "transcript_delta",
                        "text": seg["text"],
                        "chunk": chunk_index,
                        "segment_id": str(segment_id),
                        "ts_start": seg["ts_start"],
                        "ts_end": seg["ts_end"],
                    },
                )

            await db.commit()
            logger.info(
                f"Processed chunk {chunk_index} for session {session_id}: {len(segments)} segments"
            )

            if save_storage and transcribed_ok and audio_chunk.s3_key:
                deleted = await loop.run_in_executor(
                    None, s3_client.delete_object, settings.s3_bucket, audio_chunk.s3_key
                )
                if deleted:
                    audio_chunk.deleted_from_s3 = True
                    await db.commit()
                    logger.info(f"Deleted chunk {chunk_index} from storage (save_storage mode)")

        except Exception as e:
            logger.exception(f"Error processing chunk {chunk_index}: {e}")
            if audio_chunk is not None:
                try:
                    audio_chunk.error = str(e)
                    await db.commit()
                except Exception:
                    logger.exception(f"Could not record error for chunk {chunk_index}")
