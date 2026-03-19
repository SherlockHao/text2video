"""Tests for ProjectService status and resume methods."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.models.shot import Shot
from app.models.storyboard import Storyboard
from app.models.task import AITask


@pytest.fixture
async def storyboard_with_mixed_shots(db_session, sample_project):
    """Create a storyboard with shots in various states."""
    sb = Storyboard(
        id=uuid.UUID("00000000-0000-0000-0000-000000000500"),
        project_id=sample_project.id,
        version=1,
        scene_count=3,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000501"),
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
        id=uuid.UUID("00000000-0000-0000-0000-000000000502"),
        storyboard_id=sb.id,
        sequence_number=2,
        scene_number=1,
        image_prompt="Ship",
        narration_text="A ship sails",
        image_status="completed",
        video_status="failed",
        tts_status="completed",
    )
    shot3 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000503"),
        storyboard_id=sb.id,
        sequence_number=3,
        scene_number=2,
        image_prompt="Ocean",
        narration_text="The ocean",
        image_status="failed",
        video_status="pending",
        tts_status="failed",
    )
    db_session.add_all([shot1, shot2, shot3])
    await db_session.commit()

    return {"storyboard": sb, "shots": [shot1, shot2, shot3]}


@pytest.fixture
async def storyboard_all_complete(db_session, sample_project):
    """Create a storyboard with all shots completed."""
    sb = Storyboard(
        id=uuid.UUID("00000000-0000-0000-0000-000000000510"),
        project_id=sample_project.id,
        version=1,
        scene_count=2,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000511"),
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
        id=uuid.UUID("00000000-0000-0000-0000-000000000512"),
        storyboard_id=sb.id,
        sequence_number=2,
        scene_number=1,
        image_prompt="Ship",
        narration_text="A ship sails",
        image_status="completed",
        video_status="completed",
        tts_status="completed",
    )
    db_session.add_all([shot1, shot2])
    await db_session.flush()

    # Create completed assembly task
    task = AITask(
        id=uuid.UUID("00000000-0000-0000-0000-000000000520"),
        project_id=sample_project.id,
        task_type="assembly",
        status="completed",
        provider_name="internal",
    )
    db_session.add(task)
    await db_session.commit()

    return {"storyboard": sb, "shots": [shot1, shot2], "task": task}


async def test_get_project_status_empty(db_session, sample_project):
    """Status with no storyboard should show zero progress."""
    from app.services.project_service import ProjectService

    service = ProjectService(db_session)
    status = await service.get_project_status(sample_project.id)

    assert status["project_id"] == sample_project.id
    assert status["project_name"] == "Test Project"
    assert status["overall_progress"] == 0.0
    assert status["is_complete"] is False
    assert status["failed_stages"] == []
    assert "script_breakdown" in status["next_stages"]


async def test_get_project_status_with_shots(
    db_session, sample_project, storyboard_with_mixed_shots
):
    """Status with mixed shot states should reflect per-stage progress."""
    from app.services.project_service import ProjectService

    service = ProjectService(db_session)
    status = await service.get_project_status(sample_project.id)

    pipeline = status["pipeline"]

    # Script breakdown always complete when we have shots
    assert pipeline["script_breakdown"]["is_complete"] is True

    # Image: 2 completed, 1 failed out of 3
    assert pipeline["image_generation"]["completed"] == 2
    assert pipeline["image_generation"]["failed"] == 1
    assert pipeline["image_generation"]["total"] == 3
    assert pipeline["image_generation"]["is_complete"] is False

    # TTS: 2 completed, 1 failed out of 3
    assert pipeline["tts_generation"]["completed"] == 2
    assert pipeline["tts_generation"]["failed"] == 1

    # Video: 1 completed, 1 failed out of 3
    assert pipeline["video_generation"]["completed"] == 1
    assert pipeline["video_generation"]["failed"] == 1

    assert status["is_complete"] is False
    assert len(status["failed_stages"]) > 0


async def test_get_project_status_complete(
    db_session, sample_project, storyboard_all_complete
):
    """Status should show complete when all stages are done."""
    from app.services.project_service import ProjectService

    service = ProjectService(db_session)
    status = await service.get_project_status(sample_project.id)

    assert status["is_complete"] is True
    assert status["overall_progress"] == 1.0
    assert status["failed_stages"] == []


async def test_resume_from_checkpoint(
    db_session, sample_project, storyboard_with_mixed_shots
):
    """Resume should create retry tasks for failed shots."""
    from app.services.project_service import ProjectService

    mock_pool = AsyncMock()
    service = ProjectService(db_session)
    result = await service.resume_from_checkpoint(
        sample_project.id, arq_pool=mock_pool
    )

    # Shot2 has video_status=failed -> 1 task
    # Shot3 has image_status=failed + tts_status=failed -> 2 tasks
    # Total: 3 tasks
    assert result["resumed_tasks"] == 3
    assert len(result["task_ids"]) == 3

    # Verify arq was called for each task
    assert mock_pool.enqueue_job.call_count == 3


async def test_resume_no_failures(
    db_session, sample_project, storyboard_all_complete
):
    """Resume with no failures should return 0 resumed tasks."""
    from app.services.project_service import ProjectService

    service = ProjectService(db_session)
    result = await service.resume_from_checkpoint(sample_project.id)

    assert result["resumed_tasks"] == 0
    assert result["task_ids"] == []
