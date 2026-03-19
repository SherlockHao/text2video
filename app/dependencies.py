from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, settings


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return settings


def _build_engine():
    return create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)


def _build_session_factory():
    engine = _build_engine()
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = _build_session_factory()
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    factory = _get_session_factory()
    async with factory() as session:
        yield session
