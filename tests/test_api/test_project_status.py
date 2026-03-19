"""Tests for project status and resume API endpoints."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.shot import Shot
from app.models.storyboard import Storyboard


@pytest.fixture
async def seed_status_data(db_session, sample_project):
    """Seed a storyboard with shots in mixed states."""
    sb = Storyboard(
        id=uuid.UUID("00000000-0000-0000-0000-000000000600"),
        project_id=sample_project.id,
        version=1,
        scene_count=2,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000601"),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        image_prompt="Sunset",
        narration_text="The sun sets",
        image_status="completed",
        video_status="completed",
        tts_status="completed",
    )
    shot2 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000602"),
        storyboard_id=sb.id,
        sequence_number=2,
        scene_number=1,
        image_prompt="Ship",
        narration_text="A ship sails",
        image_status="completed",
        video_status="failed",
        tts_status="completed",
    )
    db_session.add_all([shot1, shot2])
    await db_session.commit()

    return {"storyboard": sb, "shots": [shot1, shot2]}


@pytest.fixture
async def status_api_client(db_engine, sample_project, seed_status_data):
    """Create an API test client with seeded status data."""
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


async def test_get_status_endpoint(status_api_client):
    """GET /projects/{id}/status should return pipeline status."""
    project_id = "00000000-0000-0000-0000-000000000010"

    response = await status_api_client.get(
        f"/api/v1/projects/{project_id}/status",
    )
    assert response.status_code == 200
    data = response.json()

    assert data["project_id"] == project_id
    assert data["project_name"] == "Test Project"
    assert "pipeline" in data
    assert "overall_progress" in data
    assert isinstance(data["is_complete"], bool)
    assert isinstance(data["failed_stages"], list)
    assert isinstance(data["next_stages"], list)

    # Verify pipeline stages are present
    pipeline = data["pipeline"]
    assert "script_breakdown" in pipeline
    assert "image_generation" in pipeline
    assert "video_generation" in pipeline
    assert "tts_generation" in pipeline
    assert "assembly" in pipeline

    # Video gen should have 1 failed
    assert pipeline["video_generation"]["failed"] == 1
    assert data["is_complete"] is False


async def test_resume_endpoint(status_api_client):
    """POST /projects/{id}/resume should retry failed tasks."""
    project_id = "00000000-0000-0000-0000-000000000010"

    response = await status_api_client.post(
        f"/api/v1/projects/{project_id}/resume",
    )
    assert response.status_code == 200
    data = response.json()

    assert "resumed_tasks" in data
    assert "task_ids" in data
    # Shot2 has video_status=failed -> 1 retry task
    assert data["resumed_tasks"] == 1
    assert len(data["task_ids"]) == 1
