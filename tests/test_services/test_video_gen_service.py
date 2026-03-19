"""Tests for VideoGenerationService."""

import uuid
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
async def sample_asset(db_session, sample_project):
    """Create a sample asset (selected image) for video generation tests."""
    from app.models.asset import Asset

    asset = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000100"),
        project_id=sample_project.id,
        file_name="shot_image.png",
        file_type="image",
        storage_path="/storage/images/shot_image.png",
        file_size_bytes=102400,
        asset_category="shot_image_selected",
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


@pytest.fixture
async def storyboard_with_shots_for_video(db_session, sample_project, sample_asset):
    """Create a storyboard with shots for video generation tests.

    Shot 1: has selected_image_id (ready for video gen), video_status=pending
    Shot 2: has selected_image_id, video_status=pending
    Shot 3: no selected_image_id (should be skipped)
    """
    from app.models.asset import Asset
    from app.models.shot import Shot
    from app.models.storyboard import Storyboard

    asset2 = Asset(
        id=uuid.UUID("00000000-0000-0000-0000-000000000101"),
        project_id=sample_project.id,
        file_name="shot_image_2.png",
        file_type="image",
        storage_path="/storage/images/shot_image_2.png",
        file_size_bytes=102400,
        asset_category="shot_image_selected",
    )
    db_session.add(asset2)
    await db_session.flush()

    sb = Storyboard(
        id=uuid.UUID("00000000-0000-0000-0000-000000000060"),
        project_id=sample_project.id,
        version=1,
        scene_count=2,
        status="completed",
    )
    db_session.add(sb)
    await db_session.flush()

    shot1 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000061"),
        storyboard_id=sb.id,
        sequence_number=1,
        scene_number=1,
        image_prompt="Sunset over the ocean",
        narration_text="The sun sets beautifully",
        image_status="completed",
        video_status="pending",
        selected_image_id=sample_asset.id,
    )
    shot2 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000062"),
        storyboard_id=sb.id,
        sequence_number=2,
        scene_number=1,
        image_prompt="Ship sailing away",
        narration_text="A ship sails into the distance",
        image_status="completed",
        video_status="pending",
        selected_image_id=asset2.id,
    )
    shot3 = Shot(
        id=uuid.UUID("00000000-0000-0000-0000-000000000063"),
        storyboard_id=sb.id,
        sequence_number=3,
        scene_number=2,
        image_prompt="Waves on the shore",
        narration_text="Waves crash against rocks",
        image_status="pending",
        video_status="pending",
        selected_image_id=None,
    )
    db_session.add_all([shot1, shot2, shot3])
    await db_session.commit()

    return {"storyboard": sb, "shots": [shot1, shot2, shot3], "assets": [sample_asset, asset2]}


async def test_generate_shot_video_creates_task(
    db_session, sample_project, storyboard_with_shots_for_video
):
    """generate_shot_video should create an AITask for a shot with a selected image."""
    from app.services.video_generation_service import VideoGenerationService

    mock_pool = AsyncMock()
    service = VideoGenerationService(db_session)

    shots = storyboard_with_shots_for_video["shots"]
    shot = shots[0]

    task = await service.generate_shot_video(
        project_id=sample_project.id,
        shot_id=shot.id,
        params={"prompt": "smooth camera pan", "seed": 42, "frames": 121},
        arq_pool=mock_pool,
    )

    assert task is not None
    assert task.task_type == "video_generation"
    assert task.status == "pending"
    assert task.project_id == sample_project.id
    assert task.shot_id == shot.id
    assert task.input_params["image_path"] == "/storage/images/shot_image.png"
    assert task.input_params["prompt"] == "smooth camera pan"
    assert task.input_params["seed"] == 42
    assert task.input_params["frames"] == 121

    # Verify arq enqueue was called
    mock_pool.enqueue_job.assert_called_once_with("process_ai_task", str(task.id))

    # Verify shot status updated
    await db_session.refresh(shot)
    assert shot.video_status == "generating"


async def test_generate_shot_video_no_image(
    db_session, sample_project, storyboard_with_shots_for_video
):
    """generate_shot_video should raise ValueError if shot has no selected image."""
    from app.services.video_generation_service import VideoGenerationService

    service = VideoGenerationService(db_session)
    shot_without_image = storyboard_with_shots_for_video["shots"][2]

    with pytest.raises(ValueError, match="has no selected image"):
        await service.generate_shot_video(
            project_id=sample_project.id,
            shot_id=shot_without_image.id,
            params={},
        )


async def test_generate_batch_creates_tasks(
    db_session, sample_project, storyboard_with_shots_for_video
):
    """generate_batch should create tasks for shots with selected images and pending video_status."""
    from app.services.video_generation_service import VideoGenerationService

    mock_pool = AsyncMock()
    service = VideoGenerationService(db_session)

    result = await service.generate_batch(
        project_id=sample_project.id,
        params={"prompt": "cinematic", "seed": 123, "frames": 121},
        arq_pool=mock_pool,
    )

    assert result["total_shots"] == 3
    assert result["tasks_created"] == 2
    assert len(result["task_ids"]) == 2
    assert result["skipped"] == 1

    # Verify arq enqueue was called for each created task
    assert mock_pool.enqueue_job.call_count == 2

    # Verify shots with images have video_status='generating'
    shots = storyboard_with_shots_for_video["shots"]
    for shot in shots[:2]:
        await db_session.refresh(shot)
        assert shot.video_status == "generating"

    # Shot without image should still be pending
    await db_session.refresh(shots[2])
    assert shots[2].video_status == "pending"


async def test_generate_batch_skips_without_image(
    db_session, sample_project, storyboard_with_shots_for_video
):
    """generate_batch should report correct skipped count for shots without selected images."""
    from app.services.video_generation_service import VideoGenerationService

    service = VideoGenerationService(db_session)

    result = await service.generate_batch(
        project_id=sample_project.id,
        params={},
    )

    # Shot 3 has no selected image, should be skipped
    assert result["skipped"] == 1
    # Shots 1 and 2 have selected images
    assert result["tasks_created"] == 2


async def test_get_progress(
    db_session, sample_project, storyboard_with_shots_for_video
):
    """get_progress should return correct aggregate counts by video_status."""
    from app.services.video_generation_service import VideoGenerationService

    service = VideoGenerationService(db_session)

    # Initially all shots are pending
    progress = await service.get_progress(sample_project.id)

    assert progress["total_shots"] == 3
    assert progress["pending"] == 3
    assert progress["completed"] == 0
    assert progress["failed"] == 0
    assert progress["running"] == 0
    assert progress["progress"] == 0.0


async def test_get_progress_no_storyboard(db_session, sample_project):
    """get_progress should return zeros when no storyboard exists."""
    from app.services.video_generation_service import VideoGenerationService

    service = VideoGenerationService(db_session)

    progress = await service.get_progress(sample_project.id)

    assert progress["total_shots"] == 0
    assert progress["completed"] == 0
    assert progress["progress"] == 0.0


async def test_generate_shot_video_not_found(db_session, sample_project):
    """generate_shot_video should raise ValueError for non-existent shot."""
    from app.services.video_generation_service import VideoGenerationService

    service = VideoGenerationService(db_session)

    with pytest.raises(ValueError, match="not found"):
        await service.generate_shot_video(
            project_id=sample_project.id,
            shot_id=uuid.uuid4(),
            params={},
        )
