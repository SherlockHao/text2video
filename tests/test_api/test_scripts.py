from unittest.mock import AsyncMock

import pytest

from app.dependencies import get_db


@pytest.fixture
def mock_db_client(test_app):
    """Override get_db with a mock async session for tests that hit the DB."""
    mock_session = AsyncMock()
    mock_session.add = lambda x: None
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    test_app.dependency_overrides[get_db] = _override
    yield
    test_app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_script_check_clean(test_client, mock_db_client):
    """POST with clean text should return has_hits=false."""
    response = await test_client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/script/check",
        json={"text": "今天天气真好，适合出去散步。"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["has_hits"] is False
    assert data["hit_count"] == 0
    assert data["hits"] == []
    assert data["is_blocked"] is False


@pytest.mark.asyncio
async def test_script_check_sensitive(test_client, mock_db_client):
    """POST with sensitive text should return hits."""
    response = await test_client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000001/script/check",
        json={"text": "这段视频涉及色情和赌博内容。"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["has_hits"] is True
    assert data["hit_count"] >= 1
    assert len(data["hits"]) >= 1
    assert data["is_blocked"] is True


@pytest.mark.asyncio
async def test_script_validate_ok(test_client):
    """POST validate with normal text should return valid."""
    response = await test_client.post(
        "/api/v1/scripts/validate",
        json={"text": "这是一段正常的脚本文案。"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["errors"] == []
    assert data["char_count"] > 0


@pytest.mark.asyncio
async def test_script_validate_too_long(test_client):
    """POST validate with very long text should return invalid."""
    long_text = "a" * 60000
    response = await test_client.post(
        "/api/v1/scripts/validate",
        json={"text": long_text},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert data["char_count"] == 60000
    assert len(data["errors"]) > 0
