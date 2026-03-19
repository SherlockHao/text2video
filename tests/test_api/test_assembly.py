"""Tests for assembly API endpoints."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def seed_assembly_data(db_session, sample_project):
    """Seed a storyboard with all shots ready for assembly."""
    from app.models.asset import Asset
    from app.models.shot import Shot
    from app.models.storyboard import Storyboard

    video1 = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000400"),
        project_id=sample_project.id,
        file_name="shot1_video.mp4",
        file_type="video",
        storage_path="/storage/videos/shot1_video.mp4",
        file_size_bytes=2048000,
        asset_category="shot_video",
    )
    audio1 = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000401"),
        project_id=sample_project.id,
        file_name="shot1_tts.mp3",
        file_type="audio",
        storage_path="/storage/audio/shot1_tts.mp3",
        file_size_bytes=128000,
        asset_category="tts_audio",
    )
    video2 = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000402"),
        project_id=sample_project.id,
        file_name="shot2_video.mp4",
        file_type="video",
        storage_path="/storage/videos/shot2_video.mp4",
        file_size_bytes=2048000,
        asset_category="shot_video",
    )
    audio2 = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000403"),
        project_id=sample_project.id,
        file_name="shot2_tts.mp3",
        file_type="audio",
        storage_path="/storage/audio/shot2_tts.mp3",
        file_size_bytes=128000,
        asset_category="tts_audio",
    )
    db_session.add_all([video1, audio1, video2, audio2])
    await db_session.flush()

    sb = Storyboard(
        id=uuid.UUID("00000000-0000-0000-0000-000000000410"),
        project_id=sample_project.id,
        version=1,
        scene_count=1,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000411"),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        image_prompt="Sunset",
        narration_text="The sun sets",
        image_status="completed",
        video_status="completed",
        tts_status="completed",
        generated_video_id=video1.id,
        tts_audio_id=audio1.id,
    )
    shot2 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000412"),
        storyboard_id=sb.id,
        sequence_number=2,
        scene_number=1,
        image_prompt="Ship",
        narration_text="A ship sails",
        image_status="completed",
        video_status="completed",
        tts_status="completed",
        generated_video_id=video2.id,
        tts_audio_id=audio2.id,
    )
    db_session.add_all([shot1, shot2])
    await db_session.commit()

    return {"storyboard": sb, "shots": [shot1, shot2]}


@pytest.fixture
async def assembly_api_client(db_engine, sample_project, seed_assembly_data):
    """Create an API test client with seeded assembly data."""
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
async def assembly_api_client_no_data(db_engine, sample_project):
    """Create an API test client without assembly data (no storyboard)."""
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


async def test_trigger_assembly(assembly_api_client):
    """POST /projects/{id}/assembly/generate should create an assembly task."""
    project_id = "00000000-0000-0000-0000-000000000010"

    response = await assembly_api_client.post(
        f"/api/v1/projects/{project_id}/assembly/generate",
    )
    assert response.status_code == 201
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "pending"
    assert data["message"] == "Assembly task created successfully."


async def test_get_status(assembly_api_client):
    """GET /projects/{id}/assembly/status should return assembly status."""
    project_id = "00000000-0000-0000-0000-000000000010"

    response = await assembly_api_client.get(
        f"/api/v1/projects/{project_id}/assembly/status",
    )
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "progress" in data
    assert data["shots_ready"] == 2
    assert data["shots_total"] == 2


async def test_get_output(assembly_api_client_no_data):
    """GET /projects/{id}/output should return project output info."""
    project_id = "00000000-0000-0000-0000-000000000010"

    response = await assembly_api_client_no_data.get(
        f"/api/v1/projects/{project_id}/output",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == project_id
    assert data["project_name"] == "Test Project"
    assert data["final_video"] is None
    assert data["asset_package"] is None
    assert data["shots"] == []


async def test_trigger_assembly_not_ready(assembly_api_client_no_data):
    """POST /projects/{id}/assembly/generate should return 400 when not ready."""
    project_id = "00000000-0000-0000-0000-000000000010"

    response = await assembly_api_client_no_data.post(
        f"/api/v1/projects/{project_id}/assembly/generate",
    )
    assert response.status_code == 400
    data = response.json()
    assert "not ready" in data["detail"]
