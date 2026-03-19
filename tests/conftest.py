import pytest
from httpx import ASGITransport, AsyncClient


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
