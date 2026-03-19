import logging
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, settings

logger = logging.getLogger(__name__)


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


# ── arq pool (lazy singleton) ──────────────────────────────────────

_arq_pool = None


async def _create_arq_pool():
    """Create arq connection pool from settings."""
    global _arq_pool
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        url = settings.REDIS_URL
        stripped = url.replace("redis://", "")
        host_port, _, database = stripped.partition("/")
        host, _, port_str = host_port.partition(":")
        port = int(port_str) if port_str else 6379
        db = int(database) if database else 0

        _arq_pool = await create_pool(
            RedisSettings(host=host, port=port, database=db)
        )
    except Exception:
        logger.warning("Failed to create arq pool — task enqueueing will be skipped")
        _arq_pool = None
    return _arq_pool


async def get_arq_pool():
    """FastAPI dependency that returns the arq connection pool (or None)."""
    global _arq_pool
    if _arq_pool is None:
        await _create_arq_pool()
    return _arq_pool
