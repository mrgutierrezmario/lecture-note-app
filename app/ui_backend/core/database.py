"""Async SQLAlchemy engine, session factory and the FastAPI ``get_db`` dependency."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    """Yield a database session for one request and close it afterwards."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
