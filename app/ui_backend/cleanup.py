"""Retention: delete audio older than ``audio_retention_days`` from object storage.

Transcripts and notes are never touched; only the audio bytes go, and the
chunk rows are marked ``deleted_from_s3`` so quotas and History stay accurate.
Kept (locked) lectures are exempt. Runs in a background loop started at
startup and can be triggered from the admin API.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import AsyncSessionLocal
from models import AudioChunk, Session
from s3_client import s3_client

logger = logging.getLogger(__name__)
settings = get_settings()


async def cleanup_old_audio(db: AsyncSession) -> dict:
    """Delete expired audio for unlocked sessions; returns counts and any errors."""
    cutoff_date = datetime.utcnow() - timedelta(days=settings.audio_retention_days)

    sessions_result = await db.execute(
        select(Session.id).where(Session.created_at < cutoff_date, Session.locked.is_(False))
    )
    old_session_ids = [row[0] for row in sessions_result.fetchall()]

    result = {
        "sessions_scanned": len(old_session_ids),
        "chunks_deleted": 0,
        "errors": [],
    }

    if not old_session_ids:
        logger.info("No old sessions found for cleanup")
        return result

    chunks_result = await db.execute(
        select(AudioChunk).where(
            AudioChunk.session_id.in_(old_session_ids),
            AudioChunk.deleted_from_s3.is_(False),
            AudioChunk.s3_key.isnot(None),
        )
    )
    chunks = chunks_result.scalars().all()

    logger.info(f"Found {len(chunks)} chunks to delete from {len(old_session_ids)} old sessions")

    for chunk in chunks:
        try:
            if chunk.s3_bucket and chunk.s3_key:
                success = s3_client.delete_object(chunk.s3_bucket, chunk.s3_key)
                if success:
                    chunk.deleted_from_s3 = True
                    chunk.deleted_at = datetime.utcnow()
                    result["chunks_deleted"] += 1
                else:
                    result["errors"].append(f"Failed to delete {chunk.s3_key}")
        except Exception as e:
            error_msg = f"Error deleting chunk {chunk.id}: {str(e)}"
            logger.error(error_msg)
            result["errors"].append(error_msg)

    await db.commit()

    logger.info(
        f"Cleanup completed: {result['chunks_deleted']} chunks deleted, "
        f"{len(result['errors'])} errors"
    )
    return result


async def run_cleanup_task():
    """Loop forever: one cleanup pass every ``cleanup_interval_hours``."""
    while True:
        try:
            logger.info("Starting scheduled cleanup task")
            async with AsyncSessionLocal() as db:
                result = await cleanup_old_audio(db)
                logger.info(f"Cleanup result: {result}")
        except Exception as e:
            logger.exception(f"Cleanup task error: {e}")

        await asyncio.sleep(settings.cleanup_interval_hours * 3600)


def start_cleanup_background_task():
    """Schedule the cleanup loop on the running event loop."""
    asyncio.create_task(run_cleanup_task())
    logger.info(
        f"Cleanup background task started (interval: {settings.cleanup_interval_hours} hours)"
    )
