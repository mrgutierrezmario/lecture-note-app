"""Lecture history: list, rename, delete — scoped to the signed-in user."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from accounts.auth import CurrentUser, current_user
from core.config import get_settings
from core.database import get_db
from core.models import (
    AudioChunk,
    DocumentUpload,
    DriveFile,
    NotesVersion,
    Session,
    TranscriptSegment,
    User,
)
from core.schemas import SessionLock, SessionRename, SessionSummary, StorageUsage
from storage import quota
from storage.s3_client import s3_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["history"])

# Each 5 s browser chunk becomes one AudioChunk row; that count times the
# chunk length is a good-enough duration without decoding anything.
CHUNK_SECONDS = 5


async def _owned_session(session_id: str, user: CurrentUser, db: AsyncSession) -> Session:
    session = (
        await db.execute(select(Session).where(Session.id == session_id))
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(404, "Lecture not found")
    if not user.is_admin and session.user_id != user.id:
        raise HTTPException(403, "This lecture belongs to another user")
    return session


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Lectures with at least one transcribed segment, newest first.

    A session row is created on every page load, so most rows are empty
    shells; only ones with content count as history."""
    seg_count = (
        select(TranscriptSegment.session_id, func.count().label("segments"))
        .group_by(TranscriptSegment.session_id)
        .subquery()
    )
    chunks = (
        select(
            AudioChunk.session_id,
            func.count().label("chunks"),
            func.sum(case((AudioChunk.deleted_from_s3.is_(False), 1), else_=0)).label("kept"),
        )
        .group_by(AudioChunk.session_id)
        .subquery()
    )
    drive = (
        select(DriveFile.session_id, func.max(DriveFile.updated_at).label("saved_at"))
        .group_by(DriveFile.session_id)
        .subquery()
    )
    query = (
        select(
            Session,
            seg_count.c.segments,
            chunks.c.chunks,
            chunks.c.kept,
            User.username,
            drive.c.saved_at,
        )
        .join(seg_count, seg_count.c.session_id == Session.id)
        .outerjoin(chunks, chunks.c.session_id == Session.id)
        .outerjoin(User, User.id == Session.user_id)
        .outerjoin(drive, drive.c.session_id == Session.id)
        .order_by(Session.created_at.desc())
    )
    if not user.is_admin:
        query = query.where(Session.user_id == user.id)

    rows = (await db.execute(query)).all()
    return [
        SessionSummary(
            id=s.id,
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
            segment_count=segments or 0,
            notes_version=s.last_notes_version or 0,
            duration_seconds=(chunk_count or 0) * CHUNK_SECONDS,
            has_audio=bool(kept),
            locked=bool(s.locked),
            owner=username if user.is_admin else None,
            drive_saved_at=saved_at,
        )
        for s, segments, chunk_count, kept, username, saved_at in rows
    ]


async def _locked_count(db: AsyncSession, user_id) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Session)
            .where(Session.user_id == user_id, Session.locked.is_(True))
        )
        or 0
    )


@router.get("/usage", response_model=StorageUsage)
async def storage_usage(
    user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """The caller's retained-audio usage, quota and kept-lecture allowance."""
    used, limit, _ = await quota.status(db, user.id)
    return StorageUsage(
        used_bytes=used,
        quota_bytes=limit,
        locked_count=await _locked_count(db, user.id),
        lock_limit=0 if user.is_admin else get_settings().max_locked_lectures,
        retention_days=get_settings().audio_retention_days,
    )  # 0 = unlimited


@router.put("/{session_id}/lock", response_model=SessionSummary)
async def set_lock(
    session_id: str,
    body: SessionLock,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Keep a lecture: its audio is exempt from the retention cleanup and it
    can't be deleted until unlocked. Limited per owner."""
    session = await _owned_session(session_id, user, db)
    # Admins are not limited; the cap applies to regular users' own lectures.
    if body.locked and not session.locked and not user.is_admin:
        limit = get_settings().max_locked_lectures
        if limit and await _locked_count(db, user.id) >= limit:
            raise HTTPException(
                409, f"You can keep up to {limit} lectures. Unlock one to keep this one."
            )
    session.locked = body.locked
    await db.commit()
    for item in await list_sessions(user, db):
        if item.id == session_id:
            return item
    raise HTTPException(404, "Lecture not found")


@router.delete("/{session_id}/audio", status_code=204)
async def delete_session_audio(
    session_id: str, user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Free quota by dropping a lecture's audio while keeping transcript and notes."""
    session = await _owned_session(session_id, user, db)
    if session.locked:
        raise HTTPException(409, "This lecture is kept — unlock it first")
    chunks = (
        (
            await db.execute(
                select(AudioChunk).where(
                    AudioChunk.session_id == session_id, AudioChunk.deleted_from_s3.is_(False)
                )
            )
        )
        .scalars()
        .all()
    )
    for chunk in chunks:
        if chunk.s3_key and s3_client.delete_object(chunk.s3_bucket, chunk.s3_key):
            chunk.deleted_from_s3 = True
    await db.commit()
    logger.info(
        "Audio for session %s deleted by %s (%d chunks)", session_id, user.username, len(chunks)
    )
    return Response(status_code=204)


@router.patch("/{session_id}", response_model=SessionSummary)
async def rename_session(
    session_id: str,
    body: SessionRename,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set (or clear, with an empty string) a lecture's title."""
    session = await _owned_session(session_id, user, db)
    session.title = body.title.strip()[:200] or None
    await db.commit()
    # Reuse the list query for a consistent shape.
    for item in await list_sessions(user, db):
        if item.id == session_id:
            return item
    raise HTTPException(404, "Lecture not found")


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str, user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Delete a lecture entirely: transcript, notes, documents and audio objects.
    Refused while the lecture is kept.
    """
    session = await _owned_session(session_id, user, db)
    if session.locked:
        raise HTTPException(409, "This lecture is kept — unlock it first")
    chunks = (
        (await db.execute(select(AudioChunk).where(AudioChunk.session_id == session_id)))
        .scalars()
        .all()
    )
    for chunk in chunks:
        if chunk.s3_key and not chunk.deleted_from_s3:
            try:
                s3_client.delete_object(chunk.s3_bucket, chunk.s3_key)
            except Exception as e:
                logger.warning(
                    "Could not delete %s for session %s: %s", chunk.s3_key, session_id, e
                )
    # Explicit deletes: ORM cascades would lazy-load relationships, which the
    # async session cannot do.
    for model in (TranscriptSegment, AudioChunk, NotesVersion, DocumentUpload):
        await db.execute(delete(model).where(model.session_id == session_id))
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()
    logger.info("Session %s deleted by %s", session_id, user.username)
    return Response(status_code=204)
