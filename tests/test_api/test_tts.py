"""Tests for TTS API endpoints."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def seed_storyboard_for_tts(db_session, sample_project):
    """Seed a storyboard with shots for TTS tests."""
    from app.models.shot import Shot
    from app.models.storyboard import Storyboard

    sb = Storyboard(
        id=uuid.UUID("00000000-0000-0000-0000-000000000050"),
        project_id=sample_project.id,
        version=1,
        scene_count=2,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000051"),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        narration_text="夕阳下的海面波光粼粼",
        image_prompt="Sunset over the ocean",
        tts_status="pending",
    )
    shot2 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000052"),
        storyboard_id=sb.id,
        sequence_number=2,
        scene_number=1,
        narration_text="帆船在远方缓缓驶过",
        image_prompt="Ship sailing away",
        tts_status="pending",
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
async def api_client_with_storyboard(db_engine, sample_project, seed_storyboard_for_tts):
    """Create an API test client with seeded storyboard data for TTS."""
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


async def test_get_voices(api_client):
    """GET /tts/voices should return a list of voices."""
    response = await api_client.get("/api/v1/tts/voices")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "voice_id" in data[0]
    assert "name" in data[0]


async def test_get_config(api_client):
    """GET /projects/{id}/tts/config should return TTS config (creating default)."""
    project_id = "00000000-0000-0000-0000-000000000010"
    response = await api_client.get(f"/api/v1/projects/{project_id}/tts/config")
    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == project_id
    assert data["voice_id"] == ""
    assert data["speed"] == 1.0
    assert data["language"] == "zh"


async def test_update_config(api_client):
    """PUT /projects/{id}/tts/config should update TTS config."""
    project_id = "00000000-0000-0000-0000-000000000010"
    response = await api_client.put(
        f"/api/v1/projects/{project_id}/tts/config",
        json={"voice_id": "test-voice", "speed": 1.5},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["voice_id"] == "test-voice"
    assert data["speed"] == 1.5


async def test_preview(api_client):
    """POST /projects/{id}/tts/preview should return duration estimate."""
    project_id = "00000000-0000-0000-0000-000000000010"
    response = await api_client.post(
        f"/api/v1/projects/{project_id}/tts/preview",
        json={"text": "夕阳下的海面波光粼粼", "speed": 1.0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["audio_url"] is None
    assert data["char_count"] == 10
    assert data["duration_estimate"] == 3.33


async def test_generate_batch(api_client_with_storyboard):
    """POST /projects/{id}/tts/generate-batch should create tasks for pending shots."""
    project_id = "00000000-0000-0000-0000-000000000010"
    response = await api_client_with_storyboard.post(
        f"/api/v1/projects/{project_id}/tts/generate-batch",
    )
    assert response.status_code == 201
    data = response.json()
    assert data["total_shots"] == 2
    assert data["tasks_created"] == 2
    assert len(data["task_ids"]) == 2


async def test_generate_batch_no_storyboard(api_client):
    """POST generate-batch with no storyboard should return 404."""
    project_id = "00000000-0000-0000-0000-000000000010"
    response = await api_client.post(
        f"/api/v1/projects/{project_id}/tts/generate-batch",
    )
    assert response.status_code == 404


async def test_get_tts_status(api_client_with_storyboard):
    """GET /projects/{id}/tts/status should return per-shot TTS status."""
    project_id = "00000000-0000-0000-0000-000000000010"
    response = await api_client_with_storyboard.get(
        f"/api/v1/projects/{project_id}/tts/status",
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["tts_status"] == "pending"
    assert "narration_text" in data[0]
