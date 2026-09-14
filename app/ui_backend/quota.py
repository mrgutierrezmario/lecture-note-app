"""Per-user audio storage quota.

Usage is the bytes of audio chunks still in object storage across a user's
sessions. Transcripts and notes are small and never count. The limit is the
user's override if set, else the global ``storage_quota_mb``; 0 means unlimited.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import AudioChunk, Session, User

MB = 1024 * 1024


async def usage_bytes(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Bytes of audio still in object storage across all of a user's sessions."""
    total = await db.scalar(
        select(func.coalesce(func.sum(AudioChunk.size_bytes), 0))
        .join(Session, Session.id == AudioChunk.session_id)
        .where(Session.user_id == user_id, AudioChunk.deleted_from_s3.is_(False))
    )
    return int(total or 0)


async def quota_bytes(db: AsyncSession, user_id: uuid.UUID) -> int:
    """The user's limit in bytes: their override if set, else the global default."""
    override = await db.scalar(select(User.quota_mb).where(User.id == user_id))
    mb = override if override is not None else get_settings().storage_quota_mb
    return int(mb) * MB


async def status(db: AsyncSession, user_id: uuid.UUID) -> tuple[int, int, bool]:
    """(used, quota, over). quota 0 = unlimited."""
    used = await usage_bytes(db, user_id)
    quota = await quota_bytes(db, user_id)
    return used, quota, bool(quota and used >= quota)
