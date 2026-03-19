"""Tests for TTSService."""

import uuid
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
async def sample_storyboard_with_shots(db_session, sample_project):
    """Create a storyboard with shots for TTS tests."""
    from app.models.shot import Shot
    from app.models.storyboard import Storyboard

    sb = Storyboard(
        id=uuid.uuid4(),
        project_id=sample_project.id,
        version=1,
        scene_count=2,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.uuid4(),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        narration_text="夕阳下的海面波光粼粼",
        image_prompt="Sunset over the ocean",
        tts_status="pending",
    )
    shot2 = Shot(
        id=uuid.uuid4(),
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


async def test_get_or_create_config_creates_default(db_session, sample_project):
    """get_or_create_config should create a default config if none exists."""
    from app.services.tts_service import TTSService

    service = TTSService(db_session)
    config = await service.get_or_create_config(sample_project.id)

    assert config is not None
    assert config.project_id == sample_project.id
    assert config.voice_id == ""
    assert config.speed == 1.0
    assert config.stability == 0.5
    assert config.similarity_boost == 0.75
    assert config.language == "zh"


async def test_get_or_create_config_returns_existing(db_session, sample_project):
    """get_or_create_config should return existing config without creating a new one."""
    from app.services.tts_service import TTSService

    service = TTSService(db_session)

    # Create first
    config1 = await service.get_or_create_config(sample_project.id)
    # Get again
    config2 = await service.get_or_create_config(sample_project.id)

    assert config1.id == config2.id


async def test_update_config(db_session, sample_project):
    """update_config should update existing config fields."""
    from app.services.tts_service import TTSService

    service = TTSService(db_session)

    config = await service.update_config(
        sample_project.id,
        {"voice_id": "test-voice", "speed": 1.5, "language": "en"},
    )

    assert config.voice_id == "test-voice"
    assert config.speed == 1.5
    assert config.language == "en"
    # Defaults should remain for unspecified fields
    assert config.stability == 0.5
    assert config.similarity_boost == 0.75


async def test_preview_returns_estimate(db_session, sample_project):
    """preview should return duration estimate based on character count."""
    from app.services.tts_service import TTSService

    service = TTSService(db_session)

    result = await service.preview(
        text="夕阳下的海面波光粼粼",
        voice_id="test",
        speed=1.0,
        stability=0.5,
        similarity_boost=0.75,
    )

    assert result["audio_url"] is None
    assert result["char_count"] == 10
    # 10 chars / 3 chars per second / 1.0 speed = 3.33
    assert result["duration_estimate"] == 3.33


async def test_generate_batch_creates_tasks(
    db_session, sample_project, sample_storyboard_with_shots
):
    """generate_batch should create one task per pending shot."""
    from app.services.tts_service import TTSService

    mock_pool = AsyncMock()
    service = TTSService(db_session)

    result = await service.generate_batch(
        project_id=sample_project.id,
        arq_pool=mock_pool,
    )

    assert result["total_shots"] == 2
    assert result["tasks_created"] == 2
    assert len(result["task_ids"]) == 2

    # Verify arq enqueue was called for each task
    assert mock_pool.enqueue_job.call_count == 2

    # Verify shots status changed to generating
    shots = sample_storyboard_with_shots["shots"]
    for shot in shots:
        await db_session.refresh(shot)
        assert shot.tts_status == "generating"


async def test_generate_batch_no_storyboard(db_session, sample_project):
    """generate_batch should raise ValueError when no storyboard exists."""
    from app.services.tts_service import TTSService

    service = TTSService(db_session)

    with pytest.raises(ValueError, match="No storyboard found"):
        await service.generate_batch(project_id=sample_project.id)


async def test_get_shot_tts_status(
    db_session, sample_project, sample_storyboard_with_shots
):
    """get_shot_tts_status should return status for all shots."""
    from app.services.tts_service import TTSService

    service = TTSService(db_session)
    statuses = await service.get_shot_tts_status(sample_project.id)

    assert len(statuses) == 2
    assert statuses[0]["tts_status"] == "pending"
    assert statuses[0]["narration_text"] == "夕阳下的海面波光粼粼"
    assert statuses[1]["tts_status"] == "pending"


async def test_get_shot_tts_status_no_storyboard(db_session, sample_project):
    """get_shot_tts_status should return empty list when no storyboard."""
    from app.services.tts_service import TTSService

    service = TTSService(db_session)
    statuses = await service.get_shot_tts_status(sample_project.id)

    assert statuses == []
