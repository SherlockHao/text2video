"""Tests for AssemblyService."""

import uuid
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
async def video_asset(db_session, sample_project):
    """Create a video asset for assembly tests."""
    from app.models.asset import Asset

    asset = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000300"),
        project_id=sample_project.id,
        file_name="shot1_video.mp4",
        file_type="video",
        storage_path="/storage/videos/shot1_video.mp4",
        file_size_bytes=2048000,
        asset_category="shot_video",
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


@pytest.fixture
async def audio_asset(db_session, sample_project):
    """Create an audio asset for assembly tests."""
    from app.models.asset import Asset

    asset = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000301"),
        project_id=sample_project.id,
        file_name="shot1_tts.mp3",
        file_type="audio",
        storage_path="/storage/audio/shot1_tts.mp3",
        file_size_bytes=128000,
        asset_category="tts_audio",
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


@pytest.fixture
async def video_asset_2(db_session, sample_project):
    """Create a second video asset."""
    from app.models.asset import Asset

    asset = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000302"),
        project_id=sample_project.id,
        file_name="shot2_video.mp4",
        file_type="video",
        storage_path="/storage/videos/shot2_video.mp4",
        file_size_bytes=2048000,
        asset_category="shot_video",
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


@pytest.fixture
async def audio_asset_2(db_session, sample_project):
    """Create a second audio asset."""
    from app.models.asset import Asset

    asset = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000303"),
        project_id=sample_project.id,
        file_name="shot2_tts.mp3",
        file_type="audio",
        storage_path="/storage/audio/shot2_tts.mp3",
        file_size_bytes=128000,
        asset_category="tts_audio",
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


@pytest.fixture
async def storyboard_all_ready(
    db_session, sample_project, video_asset, audio_asset, video_asset_2, audio_asset_2
):
    """Create a storyboard where all shots have video + TTS completed."""
    from app.models.shot import Shot
    from app.models.storyboard import Storyboard

    sb = Storyboard(
        id=uuid.UUID("00000000-0000-0000-0000-000000000080"),
        project_id=sample_project.id,
        version=1,
        scene_count=2,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000081"),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        image_prompt="Sunset",
        narration_text="The sun sets",
        image_status="completed",
        video_status="completed",
        tts_status="completed",
        generated_video_id=video_asset.id,
        tts_audio_id=audio_asset.id,
    )
    shot2 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000082"),
        storyboard_id=sb.id,
        sequence_number=2,
        scene_number=1,
        image_prompt="Ship",
        narration_text="A ship sails",
        image_status="completed",
        video_status="completed",
        tts_status="completed",
        generated_video_id=video_asset_2.id,
        tts_audio_id=audio_asset_2.id,
    )
    db_session.add_all([shot1, shot2])
    await db_session.commit()

    return {"storyboard": sb, "shots": [shot1, shot2]}


@pytest.fixture
async def storyboard_not_ready(db_session, sample_project, video_asset, audio_asset):
    """Create a storyboard where NOT all shots are ready."""
    from app.models.shot import Shot
    from app.models.storyboard import Storyboard

    sb = Storyboard(
        id=uuid.UUID("00000000-0000-0000-0000-000000000090"),
        project_id=sample_project.id,
        version=1,
        scene_count=2,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000091"),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        image_prompt="Sunset",
        narration_text="The sun sets",
        image_status="completed",
        video_status="completed",
        tts_status="completed",
        generated_video_id=video_asset.id,
        tts_audio_id=audio_asset.id,
    )
    shot2 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000092"),
        storyboard_id=sb.id,
        sequence_number=2,
        scene_number=1,
        image_prompt="Ship",
        narration_text="A ship sails",
        image_status="completed",
        video_status="pending",
        tts_status="pending",
    )
    db_session.add_all([shot1, shot2])
    await db_session.commit()

    return {"storyboard": sb, "shots": [shot1, shot2]}


async def test_check_readiness_all_ready(
    db_session, sample_project, storyboard_all_ready
):
    """check_readiness should return ready=True when all shots have video + TTS completed."""
    from app.services.assembly_service import AssemblyService

    service = AssemblyService(db_session)
    result = await service.check_readiness(sample_project.id)

    assert result["ready"] is True
    assert result["shots_ready"] == 2
    assert result["shots_total"] == 2
    assert result["missing"] == []


async def test_check_readiness_not_ready(
    db_session, sample_project, storyboard_not_ready
):
    """check_readiness should return ready=False when some shots are not completed."""
    from app.services.assembly_service import AssemblyService

    service = AssemblyService(db_session)
    result = await service.check_readiness(sample_project.id)

    assert result["ready"] is False
    assert result["shots_ready"] == 1
    assert result["shots_total"] == 2
    assert len(result["missing"]) == 1
    assert result["missing"][0]["sequence_number"] == 2


async def test_trigger_assembly_creates_task(
    db_session, sample_project, storyboard_all_ready
):
    """trigger_assembly should create an AITask with type=assembly when all shots are ready."""
    from app.services.assembly_service import AssemblyService

    mock_pool = AsyncMock()
    service = AssemblyService(db_session)

    task = await service.trigger_assembly(
        project_id=sample_project.id,
        arq_pool=mock_pool,
    )

    assert task is not None
    assert task.task_type == "assembly"
    assert task.status == "pending"
    assert task.project_id == sample_project.id
    assert "shots" in task.input_params
    assert len(task.input_params["shots"]) == 2

    # Verify shot data includes paths
    shot_data = task.input_params["shots"]
    assert shot_data[0]["video_path"] == "/storage/videos/shot1_video.mp4"
    assert shot_data[0]["audio_path"] == "/storage/audio/shot1_tts.mp3"

    # Verify arq enqueue was called
    mock_pool.enqueue_job.assert_called_once_with("process_ai_task", str(task.id))

    # Verify project step updated
    await db_session.refresh(sample_project)
    assert sample_project.current_step == "assembly"


async def test_trigger_assembly_not_ready(
    db_session, sample_project, storyboard_not_ready
):
    """trigger_assembly should raise ValueError when not all shots are ready."""
    from app.services.assembly_service import AssemblyService

    service = AssemblyService(db_session)

    with pytest.raises(ValueError, match="not ready for assembly"):
        await service.trigger_assembly(project_id=sample_project.id)


async def test_get_output_empty(db_session, sample_project):
    """get_output should return empty output when no final assets exist."""
    from app.services.assembly_service import AssemblyService

    service = AssemblyService(db_session)
    result = await service.get_output(sample_project.id)

    assert result["project_id"] == sample_project.id
    assert result["project_name"] == "Test Project"
    assert result["final_video"] is None
    assert result["asset_package"] is None
    assert result["shots"] == []


async def test_get_status_no_task(db_session, sample_project):
    """get_status should return pending status when no assembly task exists."""
    from app.services.assembly_service import AssemblyService

    service = AssemblyService(db_session)
    result = await service.get_status(sample_project.id)

    assert result["status"] == "pending"
    assert result["progress"] == 0.0
    assert result["final_video_url"] is None
    assert result["asset_package_url"] is None


async def test_get_status_with_task(
    db_session, sample_project, storyboard_all_ready
):
    """get_status should return task status when an assembly task exists."""
    from app.services.assembly_service import AssemblyService

    mock_pool = AsyncMock()
    service = AssemblyService(db_session)

    # Trigger assembly to create a task
    await service.trigger_assembly(
        project_id=sample_project.id,
        arq_pool=mock_pool,
    )

    result = await service.get_status(sample_project.id)

    assert result["status"] == "pending"
    assert result["shots_ready"] == 2
    assert result["shots_total"] == 2
