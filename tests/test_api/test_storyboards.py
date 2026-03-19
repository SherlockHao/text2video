"""Tests for storyboard API endpoints."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def seed_storyboard(db_session, sample_project):
    """Seed a storyboard with shots."""
    from app.models.shot import Shot
    from app.models.storyboard import Storyboard

    sb = Storyboard(
        id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
        project_id=sample_project.id,
        version=1,
        scene_count=2,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000031"),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        image_prompt="Sunset over the ocean",
        narration_text="The sun sets beautifully",
        scene_description="Wide shot of sunset",
        duration_seconds=5.0,
    )
    shot2 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000032"),
        storyboard_id=sb.id,
        sequence_number=2,
        scene_number=1,
        image_prompt="Waves on the shore",
        narration_text="Waves crash against rocks",
        scene_description="Close up of waves",
        duration_seconds=4.0,
    )
    db_session.add_all([shot1, shot2])
    await db_session.commit()

    return {"storyboard": sb, "shots": [shot1, shot2]}


@pytest.fixture
async def api_client(db_engine, sample_project):
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


@pytest.fixture
async def api_client_with_storyboard(db_engine, sample_project, seed_storyboard):
    """Create an API test client with seeded storyboard data."""
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


async def test_generate_storyboard(api_client):
    """POST /projects/{id}/storyboard/generate should return task_id."""
    project_id = "00000000-0000-0000-0000-000000000010"
    response = await api_client.post(
        f"/api/v1/projects/{project_id}/storyboard/generate",
        json={"source_text": "A test story about nature."},
    )
    assert response.status_code == 201
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "pending"


async def test_generate_storyboard_no_body(api_client):
    """POST generate without body should use project.source_text."""
    project_id = "00000000-0000-0000-0000-000000000010"
    response = await api_client.post(
        f"/api/v1/projects/{project_id}/storyboard/generate",
    )
    assert response.status_code == 201
    data = response.json()
    assert "task_id" in data


async def test_generate_storyboard_project_not_found(api_client):
    """POST generate for non-existent project should return 404."""
    fake_id = str(uuid.uuid4())
    response = await api_client.post(
        f"/api/v1/projects/{fake_id}/storyboard/generate",
        json={"source_text": "test"},
    )
    assert response.status_code == 404


async def test_get_storyboard(api_client_with_storyboard):
    """GET /projects/{id}/storyboard should return storyboard with shots."""
    project_id = "00000000-0000-0000-0000-000000000010"
    response = await api_client_with_storyboard.get(
        f"/api/v1/projects/{project_id}/storyboard",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == project_id
    assert data["version"] == 1
    assert data["scene_count"] == 2
    assert len(data["shots"]) == 2
    assert data["shots"][0]["image_prompt"] == "Sunset over the ocean"
    assert data["shots"][1]["sequence_number"] == 2


async def test_get_storyboard_not_found(api_client):
    """GET storyboard for project with no storyboard should return 404."""
    project_id = "00000000-0000-0000-0000-000000000010"
    response = await api_client.get(
        f"/api/v1/projects/{project_id}/storyboard",
    )
    assert response.status_code == 404


async def test_update_shot(api_client_with_storyboard):
    """PUT /projects/{id}/storyboard/shots/{shot_id} should update shot."""
    project_id = "00000000-0000-0000-0000-000000000010"
    shot_id = "00000000-0000-0000-0000-000000000031"
    response = await api_client_with_storyboard.put(
        f"/api/v1/projects/{project_id}/storyboard/shots/{shot_id}",
        json={
            "image_prompt": "Updated sunset prompt",
            "narration_text": "Updated narration text",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["image_prompt"] == "Updated sunset prompt"
    assert data["narration_text"] == "Updated narration text"


async def test_update_shot_not_found(api_client_with_storyboard):
    """PUT for non-existent shot should return 404."""
    project_id = "00000000-0000-0000-0000-000000000010"
    fake_shot = str(uuid.uuid4())
    response = await api_client_with_storyboard.put(
        f"/api/v1/projects/{project_id}/storyboard/shots/{fake_shot}",
        json={"image_prompt": "test"},
    )
    assert response.status_code == 404
