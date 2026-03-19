import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import String, event
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base


def _patch_sqlite_for_pg_types():
    """
    Make PostgreSQL-specific column types compile on the SQLite dialect.
    This patches the type compiler so CREATE TABLE statements succeed with SQLite.
    It also patches the PG UUID type so values round-trip correctly as strings.
    """
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if getattr(SQLiteTypeCompiler, "_pg_patched", False):
        return

    def visit_JSONB(self, type_, **kw):
        return "JSON"

    def visit_UUID(self, type_, **kw):
        return "VARCHAR(36)"

    SQLiteTypeCompiler.visit_JSONB = visit_JSONB
    SQLiteTypeCompiler.visit_UUID = visit_UUID
    SQLiteTypeCompiler._pg_patched = True

    # Patch PG UUID type so it stores/retrieves as string in SQLite
    _orig_bind_processor = PG_UUID.bind_processor

    def _bind_processor(self, dialect):
        if dialect.name == "sqlite":
            def process(value):
                if value is not None:
                    return str(value)
                return value
            return process
        return _orig_bind_processor(self, dialect)

    _orig_result_processor = PG_UUID.result_processor

    def _result_processor(self, dialect, coltype):
        if dialect.name == "sqlite":
            def process(value):
                if value is not None:
                    if isinstance(value, uuid.UUID):
                        return value
                    return uuid.UUID(str(value))
                return value
            return process
        return _orig_result_processor(self, dialect)

    PG_UUID.bind_processor = _bind_processor
    PG_UUID.result_processor = _result_processor


# Apply patch at import time so all tests benefit
_patch_sqlite_for_pg_types()


@pytest.fixture
async def db_engine():
    """Create an in-memory SQLite async engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Create an async session from the shared engine."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def sample_user(db_session):
    """Create a sample user for FK constraints."""
    from app.models.user import User

    user = User(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        username="testuser",
        email="test@example.com",
        hashed_password="fakehash",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def sample_project(db_session, sample_user):
    """Create a sample project for testing."""
    from app.models.project import Project

    project = Project(
        id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        user_id=sample_user.id,
        name="Test Project",
        description="A test project",
        content_type="narration",
        visual_style="manga",
        source_text="A beautiful sunset over the ocean. A ship sails into the distance.",
    )
    db_session.add(project)
    await db_session.flush()
    return project


@pytest.fixture
def test_settings():
    """Override settings for testing with SQLite async."""
    from app.core.config import Settings

    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        REDIS_URL="redis://localhost:6379/1",
        DEBUG=True,
        ALLOWED_ORIGINS="http://localhost:3000",
        STORAGE_ROOT="./test_storage",
    )


@pytest.fixture
def test_app(test_settings):
    """Create a test FastAPI application."""
    from app.main import app

    return app


@pytest.fixture
async def test_client(test_app):
    """Create an async test client."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
