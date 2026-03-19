"""
arq worker for processing AI tasks.

The worker:
1. Loads task details from DB
2. Routes to the correct provider via ProviderRouter
3. Handles submit -> poll -> download -> store lifecycle
4. Updates task status in DB at each step
5. Manages checkpoint/resume via checkpoint_data

Phase 2: script_breakdown handler added.
"""

import logging
from datetime import datetime, timezone

from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# Import providers and prompts so they register themselves
import app.ai.providers.qwen  # noqa: F401
import app.ai.providers.jimeng  # noqa: F401
import app.ai.providers.elevenlabs  # noqa: F401
import app.ai.providers.minimax_tts  # noqa: F401
import app.ai.providers.seedance2  # noqa: F401
import app.ai.providers.kling  # noqa: F401
import app.ai.prompts.narration_manga  # noqa: F401

logger = logging.getLogger(__name__)


def _build_worker_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a session factory for use in the arq worker process."""
    engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def startup(ctx: dict) -> None:
    """arq worker startup hook — initialise DB session factory."""
    ctx["session_factory"] = _build_worker_session_factory()
    logger.info("Worker started, DB session factory initialised")


async def shutdown(ctx: dict) -> None:
    """arq worker shutdown hook."""
    logger.info("Worker shutting down")


async def process_ai_task(ctx: dict, task_id: str) -> dict:
    """
    Main worker function. Dispatches to the appropriate handler based on task_type.

    Args:
        ctx: arq worker context (contains session_factory from startup)
        task_id: UUID of the AITask to process

    Returns:
        dict with status and result info
    """
    import uuid

    from app.ai.base import JobState
    from app.ai.providers import get_provider
    from app.repositories.task_repo import TaskRepository
    from app.services.storyboard_service import StoryboardService

    logger.info("Processing task: %s", task_id)

    session_factory = ctx.get("session_factory")
    if session_factory is None:
        session_factory = _build_worker_session_factory()

    async with session_factory() as session:
        task_repo = TaskRepository(session)
        task = await task_repo.get_by_id(uuid.UUID(task_id))

        if task is None:
            logger.error("Task %s not found", task_id)
            return {"task_id": task_id, "status": "failed", "error": "Task not found"}

        # Mark as running
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()

        try:
            if task.task_type == "script_breakdown":
                result = await _handle_script_breakdown(task, session)
            elif task.task_type == "image_generation":
                result = await _handle_image_generation(task, session)
            elif task.task_type == "video_generation":
                result = await _handle_video_generation(task, session)
            elif task.task_type == "tts_generation":
                result = await _handle_tts_generation(task, session)
            else:
                logger.warning("Unknown task_type: %s", task.task_type)
                result = {"status": "failed", "error": f"Unknown task_type: {task.task_type}"}

            return {"task_id": task_id, **result}

        except Exception as e:
            logger.exception("Task %s failed with exception", task_id)
            task.status = "failed"
            task.error_message = str(e)
            task.completed_at = datetime.now(timezone.utc)
            await session.flush()
            await session.commit()
            return {"task_id": task_id, "status": "failed", "error": str(e)}


async def _handle_script_breakdown(task, session: AsyncSession) -> dict:
    """Handle the script_breakdown task type."""
    from app.ai.base import JobState
    from app.ai.providers import get_provider
    from app.services.storyboard_service import StoryboardService

    # Get the provider (Qwen for script_breakdown)
    provider = get_provider("script_breakdown")

    # Submit job
    external_job_id = await provider.submit_job(task.input_params)
    task.external_job_id = external_job_id
    await session.flush()

    # Poll for result (Qwen is sync, so this returns immediately)
    job_status = await provider.poll_job(external_job_id)

    if job_status.state == JobState.COMPLETED:
        result_data = job_status.metadata.get("data", {})

        # Parse the LLM response into storyboard + shots
        storyboard_service = StoryboardService(session)
        storyboard = await storyboard_service.parse_llm_response(
            task_id=task.id,
            llm_data=result_data,
        )

        # Update task as completed
        task.status = "completed"
        task.output_result = result_data
        task.progress = 1.0
        task.completed_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()

        return {"status": "completed", "storyboard_id": str(storyboard.id)}

    elif job_status.state == JobState.FAILED:
        task.status = "failed"
        task.error_message = job_status.error or "Provider returned failure"
        task.completed_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()

        return {"status": "failed", "error": task.error_message}

    else:
        # Shouldn't happen for sync Qwen provider, but handle gracefully
        task.status = "running"
        task.progress = job_status.progress
        await session.flush()
        await session.commit()

        return {"status": "running", "progress": job_status.progress}


async def _handle_image_generation(task, session: AsyncSession) -> dict:
    """Handle the image_generation task type.

    Workflow:
    1. Get the Jimeng provider via the router.
    2. Submit the image generation job (blocks until Jimeng returns).
    3. Poll for the cached result.
    4. On success: save image to local storage, create an Asset record,
       and update the associated shot's image_status.
    5. Update task status accordingly.
    """
    import os
    import uuid as _uuid

    from app.ai.base import JobState
    from app.ai.providers import get_provider
    from app.core.config import settings
    from app.models.asset import Asset
    from app.repositories.asset_repo import AssetRepository
    from app.repositories.shot_repo import ShotRepository

    provider = get_provider("image_generation")

    # Submit job (Jimeng provider does submit + internal poll in one shot)
    external_job_id = await provider.submit_job(task.input_params)
    task.external_job_id = external_job_id
    task.provider_name = provider.provider_name
    await session.flush()

    # Poll for result (returns cached result immediately)
    job_status = await provider.poll_job(external_job_id)

    if job_status.state == JobState.COMPLETED:
        image_bytes = job_status.result_data

        asset_id = None
        storage_path = ""

        if image_bytes:
            # Save image to local storage
            project_dir = os.path.join(
                settings.STORAGE_ROOT,
                "projects",
                str(task.project_id),
                "images",
            )
            os.makedirs(project_dir, exist_ok=True)

            file_name = f"{_uuid.uuid4()}.png"
            storage_path = os.path.join(project_dir, file_name)

            with open(storage_path, "wb") as f:
                f.write(image_bytes)

            logger.info("Saved image to %s (%d bytes)", storage_path, len(image_bytes))

            # Create Asset record
            asset_repo = AssetRepository(session)
            asset = await asset_repo.create({
                "project_id": task.project_id,
                "file_name": file_name,
                "file_type": "image/png",
                "storage_path": storage_path,
                "file_size_bytes": len(image_bytes),
                "asset_category": "generated_image",
                "source_task_id": task.id,
                "metadata_": job_status.metadata.get("data", {}),
            })
            asset_id = asset.id

        # Update shot image_status if shot_id is set
        if task.shot_id:
            shot_repo = ShotRepository(session)
            shot = await shot_repo.get_by_id(task.shot_id)
            if shot:
                shot.image_status = "completed"
                if asset_id:
                    shot.selected_image_id = asset_id
                await session.flush()

        # Mark task completed
        task.status = "completed"
        task.output_result = {
            "asset_id": str(asset_id) if asset_id else None,
            "storage_path": storage_path,
            "jimeng_task_id": job_status.metadata.get("jimeng_task_id"),
        }
        task.progress = 1.0
        task.completed_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()

        return {
            "status": "completed",
            "asset_id": str(asset_id) if asset_id else None,
        }

    elif job_status.state == JobState.FAILED:
        # Update shot image_status to failed if applicable
        if task.shot_id:
            from app.repositories.shot_repo import ShotRepository

            shot_repo = ShotRepository(session)
            shot = await shot_repo.get_by_id(task.shot_id)
            if shot:
                shot.image_status = "failed"
                await session.flush()

        task.status = "failed"
        task.error_message = job_status.error or "Image generation failed"
        task.completed_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()

        return {"status": "failed", "error": task.error_message}

    else:
        task.status = "running"
        task.progress = job_status.progress
        await session.flush()
        await session.commit()

        return {"status": "running", "progress": job_status.progress}


async def _handle_video_generation(task, session: AsyncSession) -> dict:
    """Handle the video_generation task type.

    Workflow:
    1. Get the video provider via the router (quality_tier selects seedance2 or kling).
    2. Submit the I2V job (blocks until the vendor returns the video).
    3. Poll for the cached result.
    4. On success: save video to local storage as MP4, create an Asset record,
       and update the associated shot's video_status / generated_video_id.
    5. Update task status accordingly.
    """
    import os
    import uuid as _uuid

    from app.ai.base import JobState
    from app.ai.providers import get_provider
    from app.core.config import settings
    from app.repositories.asset_repo import AssetRepository
    from app.repositories.shot_repo import ShotRepository

    # Determine quality tier from input_params or default
    quality_tier = (task.input_params or {}).get("quality_tier")
    provider = get_provider("video_generation", quality_tier)

    # Build provider params — image_path comes from the shot's selected_image asset
    provider_params = dict(task.input_params or {})

    # If image_path not directly provided, look it up from the shot's selected image
    if "image_path" not in provider_params and task.shot_id:
        shot_repo = ShotRepository(session)
        shot = await shot_repo.get_by_id(task.shot_id)
        if shot and shot.selected_image_id:
            asset_repo = AssetRepository(session)
            image_asset = await asset_repo.get_by_id(shot.selected_image_id)
            if image_asset:
                provider_params["image_path"] = image_asset.storage_path
        if shot and not provider_params.get("prompt"):
            # Use scene_description as motion prompt fallback
            provider_params.setdefault("prompt", shot.scene_description or "")

    # Submit job
    external_job_id = await provider.submit_job(provider_params)
    task.external_job_id = external_job_id
    task.provider_name = provider.provider_name
    await session.flush()

    # Poll for result (returns cached result immediately for sync providers)
    job_status = await provider.poll_job(external_job_id)

    if job_status.state == JobState.COMPLETED:
        video_bytes = job_status.result_data

        asset_id = None
        storage_path = ""

        if video_bytes:
            # Save video to local storage
            project_dir = os.path.join(
                settings.STORAGE_ROOT,
                "projects",
                str(task.project_id),
                "videos",
            )
            os.makedirs(project_dir, exist_ok=True)

            file_name = f"{_uuid.uuid4()}.mp4"
            storage_path = os.path.join(project_dir, file_name)

            with open(storage_path, "wb") as f:
                f.write(video_bytes)

            logger.info("Saved video to %s (%d bytes)", storage_path, len(video_bytes))

            # Create Asset record
            asset_repo = AssetRepository(session)
            asset = await asset_repo.create({
                "project_id": task.project_id,
                "file_name": file_name,
                "file_type": "video/mp4",
                "storage_path": storage_path,
                "file_size_bytes": len(video_bytes),
                "asset_category": "shot_video",
                "source_task_id": task.id,
                "metadata_": job_status.metadata.get("data", {}),
            })
            asset_id = asset.id

        # Update shot video_status if shot_id is set
        if task.shot_id:
            shot_repo = ShotRepository(session)
            shot = await shot_repo.get_by_id(task.shot_id)
            if shot:
                shot.video_status = "completed"
                if asset_id:
                    shot.generated_video_id = asset_id
                await session.flush()

        # Mark task completed
        task.status = "completed"
        task.output_result = {
            "asset_id": str(asset_id) if asset_id else None,
            "storage_path": storage_path,
            "jimeng_task_id": job_status.metadata.get("jimeng_task_id"),
        }
        task.progress = 1.0
        task.completed_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()

        return {
            "status": "completed",
            "asset_id": str(asset_id) if asset_id else None,
        }

    elif job_status.state == JobState.FAILED:
        # Update shot video_status to failed if applicable
        if task.shot_id:
            shot_repo = ShotRepository(session)
            shot = await shot_repo.get_by_id(task.shot_id)
            if shot:
                shot.video_status = "failed"
                await session.flush()

        task.status = "failed"
        task.error_message = job_status.error or "Video generation failed"
        task.completed_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()

        return {"status": "failed", "error": task.error_message}

    else:
        task.status = "running"
        task.progress = job_status.progress
        await session.flush()
        await session.commit()

        return {"status": "running", "progress": job_status.progress}


async def _handle_tts_generation(task, session: AsyncSession) -> dict:
    """Handle the tts_generation task type.

    Workflow:
    1. Get the ElevenLabs provider via the router.
    2. Submit the TTS job (blocks until ElevenLabs returns audio).
    3. Poll for the cached result.
    4. On success: save audio to local storage as MP3, create an Asset record,
       and update the associated shot's tts_status.
    5. Update task status accordingly.
    """
    import os
    import uuid as _uuid

    from app.ai.base import JobState
    from app.ai.providers import get_provider
    from app.core.config import settings
    from app.repositories.asset_repo import AssetRepository
    from app.repositories.shot_repo import ShotRepository

    provider = get_provider("tts_generation")

    # Submit job (ElevenLabs provider does the API call in submit)
    external_job_id = await provider.submit_job(task.input_params)
    task.external_job_id = external_job_id
    task.provider_name = provider.provider_name
    await session.flush()

    # Poll for result (returns cached result immediately)
    job_status = await provider.poll_job(external_job_id)

    if job_status.state == JobState.COMPLETED:
        audio_bytes = job_status.result_data

        asset_id = None
        storage_path = ""

        if audio_bytes:
            # Save audio to local storage
            project_dir = os.path.join(
                settings.STORAGE_ROOT,
                "projects",
                str(task.project_id),
                "audio",
            )
            os.makedirs(project_dir, exist_ok=True)

            file_name = f"{_uuid.uuid4()}.mp3"
            storage_path = os.path.join(project_dir, file_name)

            with open(storage_path, "wb") as f:
                f.write(audio_bytes)

            logger.info("Saved TTS audio to %s (%d bytes)", storage_path, len(audio_bytes))

            # Create Asset record
            asset_repo = AssetRepository(session)
            asset = await asset_repo.create({
                "project_id": task.project_id,
                "file_name": file_name,
                "file_type": "audio/mpeg",
                "storage_path": storage_path,
                "file_size_bytes": len(audio_bytes),
                "asset_category": "tts_audio",
                "source_task_id": task.id,
                "metadata_": {
                    "voice_id": job_status.metadata.get("voice_id"),
                    "model_id": job_status.metadata.get("model_id"),
                    "text_length": job_status.metadata.get("text_length"),
                },
            })
            asset_id = asset.id

        # Estimate audio duration: ~15 characters per second for most languages
        text = task.input_params.get("text", "")
        estimated_duration = len(text) / 15.0 if text else None

        # Update shot tts_status if shot_id is set
        if task.shot_id:
            shot_repo = ShotRepository(session)
            shot = await shot_repo.get_by_id(task.shot_id)
            if shot:
                shot.tts_status = "completed"
                if asset_id:
                    shot.tts_audio_id = asset_id
                if estimated_duration is not None:
                    shot.duration_seconds = estimated_duration
                await session.flush()

        # Mark task completed
        task.status = "completed"
        task.output_result = {
            "asset_id": str(asset_id) if asset_id else None,
            "storage_path": storage_path,
            "estimated_duration_seconds": estimated_duration,
            "voice_id": job_status.metadata.get("voice_id"),
        }
        task.progress = 1.0
        task.completed_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()

        return {
            "status": "completed",
            "asset_id": str(asset_id) if asset_id else None,
        }

    elif job_status.state == JobState.FAILED:
        # Update shot tts_status to failed if applicable
        if task.shot_id:
            shot_repo = ShotRepository(session)
            shot = await shot_repo.get_by_id(task.shot_id)
            if shot:
                shot.tts_status = "failed"
                await session.flush()

        task.status = "failed"
        task.error_message = job_status.error or "TTS generation failed"
        task.completed_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()

        return {"status": "failed", "error": task.error_message}

    else:
        task.status = "running"
        task.progress = job_status.progress
        await session.flush()
        await session.commit()

        return {"status": "running", "progress": job_status.progress}


def _parse_redis_settings() -> RedisSettings:
    """Derive arq RedisSettings from the application REDIS_URL."""
    url = settings.REDIS_URL
    stripped = url.replace("redis://", "")
    host_port, _, database = stripped.partition("/")
    host, _, port_str = host_port.partition(":")
    port = int(port_str) if port_str else 6379
    db = int(database) if database else 0
    return RedisSettings(host=host, port=port, database=db)


class WorkerSettings:
    """arq worker settings."""
    functions = [process_ai_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _parse_redis_settings()
    max_jobs = 10
    job_timeout = 600  # 10 minutes max per task
