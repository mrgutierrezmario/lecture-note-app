"""Admin maintenance endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from accounts.auth import require_admin
from core.database import get_db
from core.schemas import CleanupResponse
from storage.cleanup import cleanup_old_audio

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/cleanup_audio", response_model=CleanupResponse)
async def trigger_cleanup(db: AsyncSession = Depends(get_db)):
    """Run one audio-retention cleanup pass now instead of waiting for the timer."""
    result = await cleanup_old_audio(db)
    return CleanupResponse(**result)
