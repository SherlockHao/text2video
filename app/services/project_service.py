import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import PipelineOrchestrator
from app.models.project import Project
from app.repositories.project_repo import ProjectRepository
from app.repositories.shot_repo import ShotRepository
from app.repositories.storyboard_repo import StoryboardRepository
from app.repositories.task_repo import TaskRepository

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ProjectRepository(session)
        self.storyboard_repo = StoryboardRepository(session)
        self.shot_repo = ShotRepository(session)
        self.task_repo = TaskRepository(session)

    async def create_project(self, user_id: uuid.UUID, data: dict) -> Project:
        data["user_id"] = user_id
        project = await self.repo.create(data)
        await self.session.commit()
        return project

    async def get_project(self, project_id: uuid.UUID) -> Project | None:
        return await self.repo.get_by_id(project_id)

    async def list_projects(
        self, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Project]:
        return await self.repo.get_by_user_id(user_id, skip=skip, limit=limit)

    async def update_project(
        self, project_id: uuid.UUID, data: dict
    ) -> Project | None:
        project = await self.repo.update(project_id, data)
        if project:
            await self.session.commit()
        return project

    async def delete_project(self, project_id: uuid.UUID) -> bool:
        deleted = await self.repo.soft_delete(project_id)
        if deleted:
            await self.session.commit()
        return deleted

    async def get_project_status(self, project_id: uuid.UUID) -> dict:
        """Get comprehensive project status with per-stage progress.

        Returns: {
            project: {...},
            pipeline: {stage_name: {total, completed, failed, progress, is_complete}},
            overall_progress: float,
            is_complete: bool,
            failed_stages: [str],
            next_stages: [str],
        }
        """
        # 1. Load project
        project = await self.repo.get_by_id(project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        # 2. Load latest storyboard with shots
        storyboard = await self.storyboard_repo.get_latest_by_project_id(project_id)
        shots = []
        if storyboard:
            shots = await self.shot_repo.get_by_storyboard_id(storyboard.id)

        # 3. Load all project tasks
        tasks = await self.task_repo.get_by_project_id(project_id)

        # 4. Build PipelineOrchestrator from data
        orch = PipelineOrchestrator.from_project_data(
            project_id=str(project_id),
            shots=shots,
            tasks=tasks,
        )

        # 5. Return structured status
        return {
            "project_id": project.id,
            "project_name": project.name,
            "current_step": project.current_step,
            "pipeline": orch.get_pipeline_dict(),
            "overall_progress": orch.get_overall_progress(),
            "is_complete": orch.is_complete(),
            "failed_stages": [s.value for s in orch.get_failed_stages()],
            "next_stages": [s.value for s in orch.get_next_stages()],
        }

    async def resume_from_checkpoint(self, project_id: uuid.UUID, arq_pool=None) -> dict:
        """Resume a project from its current checkpoint.

        Identifies failed shots and re-enqueues tasks for them.
        Returns: {resumed_tasks: int, task_ids: [str]}
        """
        # 1. Load project + storyboard + shots
        project = await self.repo.get_by_id(project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        storyboard = await self.storyboard_repo.get_latest_by_project_id(project_id)
        if storyboard is None:
            return {"resumed_tasks": 0, "task_ids": []}

        shots = await self.shot_repo.get_by_storyboard_id(storyboard.id)

        # 2. Find shots with failed status in any phase and create retry tasks
        task_ids = []

        for shot in shots:
            # Image generation failed
            if shot.image_status == "failed":
                task = await self.task_repo.create({
                    "project_id": project_id,
                    "task_type": "image_generation",
                    "status": "pending",
                    "shot_id": shot.id,
                    "provider_name": "jimeng",
                    "input_params": {"shot_id": str(shot.id), "retry": True},
                })
                shot.image_status = "pending"
                task_ids.append(str(task.id))
                if arq_pool is not None:
                    await arq_pool.enqueue_job("process_ai_task", str(task.id))

            # TTS generation failed
            if shot.tts_status == "failed":
                task = await self.task_repo.create({
                    "project_id": project_id,
                    "task_type": "tts_generation",
                    "status": "pending",
                    "shot_id": shot.id,
                    "provider_name": "elevenlabs",
                    "input_params": {"shot_id": str(shot.id), "retry": True},
                })
                shot.tts_status = "pending"
                task_ids.append(str(task.id))
                if arq_pool is not None:
                    await arq_pool.enqueue_job("process_ai_task", str(task.id))

            # Video generation failed
            if shot.video_status == "failed":
                task = await self.task_repo.create({
                    "project_id": project_id,
                    "task_type": "video_generation",
                    "status": "pending",
                    "shot_id": shot.id,
                    "provider_name": "kling",
                    "input_params": {"shot_id": str(shot.id), "retry": True},
                })
                shot.video_status = "pending"
                task_ids.append(str(task.id))
                if arq_pool is not None:
                    await arq_pool.enqueue_job("process_ai_task", str(task.id))

        # Also check for failed assembly tasks
        all_tasks = await self.task_repo.get_by_project_id(project_id, task_type="assembly", status="failed")
        for failed_task in all_tasks:
            task = await self.task_repo.create({
                "project_id": project_id,
                "task_type": "assembly",
                "status": "pending",
                "provider_name": "internal",
                "input_params": failed_task.input_params,
            })
            task_ids.append(str(task.id))
            if arq_pool is not None:
                await arq_pool.enqueue_job("process_ai_task", str(task.id))

        await self.session.commit()

        return {"resumed_tasks": len(task_ids), "task_ids": task_ids}
