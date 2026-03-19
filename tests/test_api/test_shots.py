"""Tests for shot image API endpoints."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def seed_storyboard_with_shots(db_session, sample_project):
    """Seed a storyboard with shots for shot image tests."""
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
async def api_client(db_engine, sample_project, seed_storyboard_with_shots):
    """Create an API test client with DB session override and seeded data."""
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


async def test_generate_shot_image(api_client):
    """POST /projects/{id}/shots/{shot_id}/generate-image should return task info."""
    project_id = "00000000-0000-0000-0000-000000000010"
    shot_id = "00000000-0000-0000-0000-000000000031"

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/generate-image",
        json={"seed": 42, "width": 1024, "height": 1024},
    )
    assert response.status_code == 201
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "pending"


async def test_list_shot_images(api_client):
    """GET /projects/{id}/shots/{shot_id}/images should return a list (may be empty)."""
    project_id = "00000000-0000-0000-0000-000000000010"
    shot_id = "00000000-0000-0000-0000-000000000031"

    response = await api_client.get(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/images",
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


async def test_select_shot_image(api_client):
    """POST /projects/{id}/shots/{shot_id}/images/{image_id}/select should return 404 for non-existent asset."""
    project_id = "00000000-0000-0000-0000-000000000010"
    shot_id = "00000000-0000-0000-0000-000000000031"
    fake_image_id = str(uuid.uuid4())

    response = await api_client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/images/{fake_image_id}/select",
    )
    # Should 404 because the asset doesn't exist
    assert response.status_code == 404
