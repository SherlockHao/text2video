"""Tests for StoryboardService."""

import uuid
from unittest.mock import AsyncMock

import pytest


async def test_generate_creates_task(db_session, sample_project):
    """generate_storyboard should create an AITask with correct params."""
    from app.services.storyboard_service import StoryboardService

    mock_pool = AsyncMock()
    service = StoryboardService(db_session)

    task = await service.generate_storyboard(
        project_id=sample_project.id,
        arq_pool=mock_pool,
    )

    assert task is not None
    assert task.task_type == "script_breakdown"
    assert task.status == "pending"
    assert task.provider_name == "qwen"
    assert task.project_id == sample_project.id
    assert "system_prompt" in task.input_params
    assert "user_prompt" in task.input_params

    # Verify arq enqueue was called
    mock_pool.enqueue_job.assert_called_once_with("process_ai_task", str(task.id))


async def test_generate_uses_override_source_text(db_session, sample_project):
    """generate_storyboard should use provided source_text over project's."""
    from app.services.storyboard_service import StoryboardService

    mock_pool = AsyncMock()
    service = StoryboardService(db_session)
    override_text = "Custom text for generation"

    task = await service.generate_storyboard(
        project_id=sample_project.id,
        source_text=override_text,
        arq_pool=mock_pool,
    )

    assert override_text in task.input_params["user_prompt"]


async def test_generate_raises_for_missing_project(db_session):
    """generate_storyboard should raise ValueError if project not found."""
    from app.services.storyboard_service import StoryboardService

    service = StoryboardService(db_session)
    fake_id = uuid.uuid4()

    with pytest.raises(ValueError, match="not found"):
        await service.generate_storyboard(project_id=fake_id)


async def test_generate_raises_for_no_source_text(db_session, sample_user):
    """generate_storyboard should raise ValueError if no source text available."""
    from app.models.project import Project
    from app.services.storyboard_service import StoryboardService

    project = Project(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        name="No Text Project",
        source_text=None,
    )
    db_session.add(project)
    await db_session.flush()

    service = StoryboardService(db_session)

    with pytest.raises(ValueError, match="No source text"):
        await service.generate_storyboard(project_id=project.id)


async def test_parse_llm_response(db_session, sample_project):
    """parse_llm_response should create Storyboard + Shot records."""
    from app.models.task import AITask
    from app.services.storyboard_service import StoryboardService

    # Create a task first
    task = AITask(
        id=uuid.uuid4(),
        project_id=sample_project.id,
        task_type="script_breakdown",
        status="running",
    )
    db_session.add(task)
    await db_session.flush()

    llm_data = {
        "storyboards": [
            {
                "shot_number": 1,
                "scene_number": 1,
                "prompt_en": "A golden sunset over the ocean waves",
                "description_zh": "夕阳下的海面",
                "narration_text": "The sun sets slowly.",
                "description": "Wide shot of ocean at sunset",
                "duration_seconds": 5.0,
            },
            {
                "shot_number": 2,
                "scene_number": 1,
                "prompt_en": "A sailing ship silhouette against orange sky",
                "description_zh": "帆船剪影",
                "description": "Medium shot of ship sailing away",
                "duration_seconds": 4.0,
            },
        ]
    }

    service = StoryboardService(db_session)
    storyboard = await service.parse_llm_response(task.id, llm_data)

    assert storyboard is not None
    assert storyboard.project_id == sample_project.id
    assert storyboard.version == 1
    assert storyboard.scene_count == 2
    assert storyboard.status == "completed"
    assert len(storyboard.shots) == 2

    shot1 = storyboard.shots[0]
    assert shot1.sequence_number == 1
    assert shot1.image_prompt == "A golden sunset over the ocean waves"
    assert "夕阳下的海面" in shot1.narration_text
    assert shot1.scene_description == "Wide shot of ocean at sunset"
    assert shot1.duration_seconds == 5.0

    shot2 = storyboard.shots[1]
    assert shot2.sequence_number == 2
    assert shot2.image_prompt == "A sailing ship silhouette against orange sky"


async def test_parse_llm_response_increments_version(db_session, sample_project):
    """A second parse should create version 2."""
    from app.models.task import AITask
    from app.services.storyboard_service import StoryboardService

    service = StoryboardService(db_session)

    # First task + parse
    task1 = AITask(
        id=uuid.uuid4(),
        project_id=sample_project.id,
        task_type="script_breakdown",
        status="running",
    )
    db_session.add(task1)
    await db_session.flush()

    llm_data = {"storyboards": [{"shot_number": 1, "prompt_en": "test", "description": "d"}]}
    sb1 = await service.parse_llm_response(task1.id, llm_data)
    assert sb1.version == 1

    # Second task + parse
    task2 = AITask(
        id=uuid.uuid4(),
        project_id=sample_project.id,
        task_type="script_breakdown",
        status="running",
    )
    db_session.add(task2)
    await db_session.flush()

    sb2 = await service.parse_llm_response(task2.id, llm_data)
    assert sb2.version == 2


async def test_get_storyboard(db_session, sample_project):
    """get_storyboard should return the latest storyboard with shots."""
    from app.models.shot import Shot
    from app.models.storyboard import Storyboard
    from app.services.storyboard_service import StoryboardService

    sb = Storyboard(
        id=uuid.uuid4(),
        project_id=sample_project.id,
        version=1,
        scene_count=1,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot = Shot(
        id=uuid.uuid4(),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        image_prompt="A test prompt",
        narration_text="Test narration",
    )
    db_session.add(shot)
    await db_session.flush()
    await db_session.commit()

    service = StoryboardService(db_session)
    result = await service.get_storyboard(sample_project.id)

    assert result is not None
    assert result.id == sb.id
    assert len(result.shots) == 1
    assert result.shots[0].image_prompt == "A test prompt"


async def test_get_storyboard_returns_none_if_missing(db_session, sample_project):
    """get_storyboard should return None if no storyboard exists."""
    from app.services.storyboard_service import StoryboardService

    service = StoryboardService(db_session)
    result = await service.get_storyboard(sample_project.id)
    assert result is None


async def test_update_shot(db_session, sample_project):
    """update_shot should update the specified fields."""
    from app.models.shot import Shot
    from app.models.storyboard import Storyboard
    from app.services.storyboard_service import StoryboardService

    sb = Storyboard(
        id=uuid.uuid4(),
        project_id=sample_project.id,
        version=1,
        scene_count=1,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot = Shot(
        id=uuid.uuid4(),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        image_prompt="Original prompt",
        narration_text="Original narration",
    )
    db_session.add(shot)
    await db_session.flush()
    await db_session.commit()

    service = StoryboardService(db_session)
    updated = await service.update_shot(
        shot.id,
        {"image_prompt": "Updated prompt", "narration_text": "Updated narration"},
    )

    assert updated.image_prompt == "Updated prompt"
    assert updated.narration_text == "Updated narration"


async def test_update_shot_raises_for_missing(db_session):
    """update_shot should raise ValueError if shot not found."""
    from app.services.storyboard_service import StoryboardService

    service = StoryboardService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await service.update_shot(uuid.uuid4(), {"image_prompt": "test"})
