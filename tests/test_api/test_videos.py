"""Tests for video generation API endpoints."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def seed_storyboard_for_video(db_session, sample_project):
    """Seed a storyboard with shots and assets for video generation tests."""
    from app.models.asset import Asset
    from app.models.shot import Shot
    from app.models.storyboard import Storyboard

    asset1 = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000200"),
        project_id=sample_project.id,
        file_name="shot1_image.png",
        file_type="image",
        storage_path="/storage/images/shot1_image.png",
        file_size_bytes=102400,
        asset_category="shot_image_selected",
    )
    asset2 = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000201"),
        project_id=sample_project.id,
        file_name="shot2_image.png",
        file_type="image",
        storage_path="/storage/images/shot2_image.png",
        file_size_bytes=102400,
        asset_category="shot_image_selected",
    )
    db_session.add_all([asset1, asset2])
    await db_session.flush()

    sb = Storyboard(
        id=uuid.UUID("00000000-0000-0000-0000-000000000070"),
        project_id=sample_project.id,
        version=1,
        scene_count=2,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000071"),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        image_prompt="Sunset over the ocean",
        narration_text="The sun sets beautifully",
        image_status="completed",
        video_status="pending",
        selected_image_id=asset1.id,
    )
    shot2 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000072"),
        storyboard_id=sb.id,
        sequence_number=2,
        scene_number=1,
        image_prompt="Ship sailing away",
        narration_text="A ship sails away",
        image_status="completed",
        video_status="pending",
        selected_image_id=asset2.id,
    )
    shot3 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000073"),
        storyboard_id=sb.id,
        sequence_number=3,
        scene_number=2,
        image_prompt="Waves crashing",
        narration_text="Waves crash",
        image_status="pending",
        video_status="pending",
        selected_image_id=None,
    )
    db_session.add_all([shot1, shot2, shot3])
    await db_session.commit()

    return {"storyboard": sb, "shots": [shot1, shot2, shot3]}


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
async def api_client_with_video_data(db_engine, sample_project, seed_storyboard_for_video):
    """Create an API test client with seeded storyboard and shot data for video tests."""
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


async def test_generate_shot_video(api_client_with_video_data):
    """POST /projects/{id}/shots/{shot_id}/generate-video should return task info."""
    project_id = "00000000-0000-0000-0000-000000000010"
    shot_id = "00000000-0000-0000-0000-000000000071"

    response = await api_client_with_video_data.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/generate-video",
        json={"prompt": "smooth zoom", "seed": 42, "frames": 121},
    )
    assert response.status_code == 201
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "pending"


async def test_generate_batch(api_client_with_video_data):
    """POST /projects/{id}/video/generate-batch should create tasks for eligible shots."""
    project_id = "00000000-0000-0000-0000-000000000010"

    response = await api_client_with_video_data.post(
        f"/api/v1/projects/{project_id}/video/generate-batch",
        json={"prompt": "cinematic", "seed": 123},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["total_shots"] == 3
    assert data["tasks_created"] == 2
    assert len(data["task_ids"]) == 2
    assert data["skipped"] == 1


async def test_get_progress(api_client_with_video_data):
    """GET /projects/{id}/video/progress should return aggregate video progress."""
    project_id = "00000000-0000-0000-0000-000000000010"

    response = await api_client_with_video_data.get(
        f"/api/v1/projects/{project_id}/video/progress",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_shots"] == 3
    assert data["pending"] == 3
    assert data["completed"] == 0
    assert data["failed"] == 0
    assert data["running"] == 0
    assert data["progress"] == 0.0


async def test_generate_shot_video_no_image(api_client_with_video_data):
    """POST generate-video for a shot without selected image should return 404."""
    project_id = "00000000-0000-0000-0000-000000000010"
    shot_id = "00000000-0000-0000-0000-000000000073"  # shot3, no selected image

    response = await api_client_with_video_data.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/generate-video",
        json={},
    )
    assert response.status_code == 404


async def test_get_progress_no_storyboard(api_client):
    """GET progress with no storyboard should return zeros."""
    project_id = "00000000-0000-0000-0000-000000000010"

    response = await api_client.get(
        f"/api/v1/projects/{project_id}/video/progress",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_shots"] == 0
    assert data["progress"] == 0.0
