import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tts_config import TTSConfig
from app.repositories.shot_repo import ShotRepository
from app.repositories.storyboard_repo import StoryboardRepository
from app.repositories.task_repo import TaskRepository
from app.repositories.tts_config_repo import TTSConfigRepository

logger = logging.getLogger(__name__)


class TTSService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.tts_config_repo = TTSConfigRepository(session)
        self.shot_repo = ShotRepository(session)
        self.task_repo = TaskRepository(session)
        self.storyboard_repo = StoryboardRepository(session)

    async def get_or_create_config(self, project_id: UUID) -> TTSConfig:
        """Get TTS config for project, create default if not exists."""
        config = await self.tts_config_repo.get_by_project_id(project_id)
        if config is not None:
            return config

        config = await self.tts_config_repo.create(
            {
                "project_id": project_id,
                "voice_id": "",
                "speed": 1.0,
                "stability": 0.5,
                "similarity_boost": 0.75,
                "language": "zh",
            }
        )
        await self.session.commit()
        return config

    async def update_config(self, project_id: UUID, data: dict) -> TTSConfig:
        """Update TTS config. Creates if not exists."""
        config = await self.tts_config_repo.get_by_project_id(project_id)
        if config is None:
            # Create with provided data merged into defaults
            create_data = {
                "project_id": project_id,
                "voice_id": "",
                "speed": 1.0,
                "stability": 0.5,
                "similarity_boost": 0.75,
                "language": "zh",
            }
            create_data.update(data)
            config = await self.tts_config_repo.create(create_data)
        else:
            for key, value in data.items():
                setattr(config, key, value)
            await self.session.flush()
            await self.session.refresh(config)

        await self.session.commit()
        return config

    async def preview(
        self,
        text: str,
        voice_id: str,
        speed: float,
        stability: float,
        similarity_boost: float,
    ) -> dict:
        """Generate a TTS preview for a short text snippet.

        For MVP, returns estimated duration only (actual audio generation
        requires ElevenLabs API key).

        Returns:
            {"audio_url": None, "duration_estimate": float, "char_count": int}

        Duration estimate: ~3 chars per second for Chinese text.
        """
        char_count = len(text)
        # ~3 characters per second for Chinese text, adjusted by speed
        duration_estimate = round(char_count / 3.0 / speed, 2)

        return {
            "audio_url": None,
            "duration_estimate": duration_estimate,
            "char_count": char_count,
        }

    async def generate_batch(self, project_id: UUID, arq_pool=None) -> dict:
        """Generate TTS for all shots with tts_status='pending' in the latest storyboard.

        Creates one AITask per shot with type=tts_generation.
        Input params for each task: {text, voice_id, speed, stability, similarity_boost, shot_id}

        Returns:
            {"total_shots": int, "tasks_created": int, "task_ids": list[str]}
        """
        storyboard = await self.storyboard_repo.get_latest_by_project_id(project_id)
        if storyboard is None:
            raise ValueError(f"No storyboard found for project {project_id}")

        # Get TTS config
        config = await self.get_or_create_config(project_id)

        # Get all shots and pending shots
        all_shots = await self.shot_repo.get_by_storyboard_id(storyboard.id)
        pending_shots = await self.shot_repo.get_pending_shots(
            storyboard.id, phase="tts"
        )

        task_ids: list[str] = []
        for shot in pending_shots:
            task = await self.task_repo.create(
                {
                    "project_id": project_id,
                    "task_type": "tts_generation",
                    "status": "pending",
                    "provider_name": "elevenlabs",
                    "shot_id": shot.id,
                    "input_params": {
                        "text": shot.narration_text or "",
                        "voice_id": config.voice_id,
                        "speed": config.speed,
                        "stability": config.stability,
                        "similarity_boost": config.similarity_boost,
                        "shot_id": str(shot.id),
                    },
                }
            )
            shot.tts_status = "generating"
            task_ids.append(str(task.id))

        await self.session.flush()

        # Enqueue all tasks to arq
        if arq_pool is not None:
            for task_id in task_ids:
                await arq_pool.enqueue_job("process_ai_task", task_id)

        await self.session.commit()

        return {
            "total_shots": len(all_shots),
            "tasks_created": len(task_ids),
            "task_ids": task_ids,
        }

    async def get_shot_tts_status(self, project_id: UUID) -> list[dict]:
        """Get TTS generation status for all shots in latest storyboard."""
        storyboard = await self.storyboard_repo.get_latest_by_project_id(project_id)
        if storyboard is None:
            return []

        shots = await self.shot_repo.get_by_storyboard_id(storyboard.id)
        return [
            {
                "shot_id": str(shot.id),
                "sequence_number": shot.sequence_number,
                "tts_status": shot.tts_status,
                "tts_audio_id": str(shot.tts_audio_id) if shot.tts_audio_id else None,
                "narration_text": shot.narration_text,
            }
            for shot in shots
        ]
