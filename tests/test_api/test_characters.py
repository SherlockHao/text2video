"""Tests for character API endpoints."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def api_client(db_engine, sample_user):
    """Create an API test client with DB session override."""
    from app.dependencies import get_arq_pool, get_db
    from app.main import app

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    async def override_get_arq_pool():
        return AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_arq_pool] = override_get_arq_pool

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


async def test_create_character(api_client):
    """POST /characters should create a character and return 201."""
    response = await api_client.post(
        "/api/v1/characters",
        json={
            "name": "Test Hero",
            "description": "A brave hero",
            "tags": ["hero"],
            "visual_style": "manga",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Hero"
    assert data["description"] == "A brave hero"
    assert data["tags"] == ["hero"]
    assert data["visual_style"] == "manga"
    assert "id" in data
    assert "created_at" in data


async def test_list_characters(api_client):
    """GET /characters should return a list of characters."""
    # Create two characters first
    await api_client.post(
        "/api/v1/characters",
        json={"name": "Char A", "tags": ["a"]},
    )
    await api_client.post(
        "/api/v1/characters",
        json={"name": "Char B", "tags": ["b"]},
    )

    response = await api_client.get("/api/v1/characters")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2


async def test_get_character(api_client):
    """GET /characters/{id} should return a single character."""
    create_resp = await api_client.post(
        "/api/v1/characters",
        json={"name": "Fetch Me"},
    )
    char_id = create_resp.json()["id"]

    response = await api_client.get(f"/api/v1/characters/{char_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Fetch Me"


async def test_update_character(api_client):
    """PUT /characters/{id} should update and return the character."""
    create_resp = await api_client.post(
        "/api/v1/characters",
        json={"name": "Old Name"},
    )
    char_id = create_resp.json()["id"]

    response = await api_client.put(
        f"/api/v1/characters/{char_id}",
        json={"name": "New Name", "description": "Updated"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["description"] == "Updated"


async def test_delete_character(api_client):
    """DELETE /characters/{id} should return 204."""
    create_resp = await api_client.post(
        "/api/v1/characters",
        json={"name": "Delete Me"},
    )
    char_id = create_resp.json()["id"]

    response = await api_client.delete(f"/api/v1/characters/{char_id}")
    assert response.status_code == 204

    # Should be gone
    get_resp = await api_client.get(f"/api/v1/characters/{char_id}")
    assert get_resp.status_code == 404
