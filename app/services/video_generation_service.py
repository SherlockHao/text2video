import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import AITask
from app.repositories.asset_repo import AssetRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.shot_repo import ShotRepository
from app.repositories.storyboard_repo import StoryboardRepository
from app.repositories.task_repo import TaskRepository

logger = logging.getLogger(__name__)


class VideoGenerationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.shot_repo = ShotRepository(session)
        self.storyboard_repo = StoryboardRepository(session)
        self.task_repo = TaskRepository(session)
        self.asset_repo = AssetRepository(session)
        self.project_repo = ProjectRepository(session)

    async def generate_shot_video(
        self, project_id: UUID, shot_id: UUID, params: dict, arq_pool=None
    ) -> AITask:
        """Generate video for a specific shot.

        Requires shot to have a selected_image_id.
        Creates AITask with type=video_generation.
        Input params: {image_path, prompt, seed, frames, quality_tier}
        """
        # 1. Load shot, verify selected_image_id exists
        shot = await self.shot_repo.get_by_id(shot_id)
        if shot is None:
            raise ValueError(f"Shot {shot_id} not found")

        if shot.selected_image_id is None:
            raise ValueError(
                f"Shot {shot_id} has no selected image. "
                "Generate and select an image before generating video."
            )

        # 2. Load the asset to get storage_path
        asset = await self.asset_repo.get_by_id(shot.selected_image_id)
        if asset is None:
            raise ValueError(
                f"Selected image asset {shot.selected_image_id} not found"
            )

        # 3. Load project to get quality_tier
        project = await self.project_repo.get_by_id(project_id)
        quality_tier = project.quality_tier if project else "normal"

        # 4. Create task with input_params including image_path
        task = await self.task_repo.create(
            {
                "project_id": project_id,
                "task_type": "video_generation",
                "status": "pending",
                "provider_name": "kling",
                "shot_id": shot_id,
                "input_params": {
                    "shot_id": str(shot_id),
                    "image_path": asset.storage_path,
                    "prompt": params.get("prompt", ""),
                    "seed": params.get("seed", -1),
                    "frames": params.get("frames", 121),
                    "quality_tier": quality_tier,
                },
            }
        )

        # 5. Update shot.video_status = "generating"
        shot.video_status = "generating"
        await self.session.flush()

        # 6. Enqueue to arq
        if arq_pool is not None:
            await arq_pool.enqueue_job("process_ai_task", str(task.id))

        await self.session.commit()
        return task

    async def generate_batch(
        self, project_id: UUID, params: dict, arq_pool=None
    ) -> dict:
        """Generate videos for all shots with image_status='completed' and video_status='pending'.

        Returns: {total_shots, tasks_created, task_ids, skipped}
        """
        # 1. Load latest storyboard
        storyboard = await self.storyboard_repo.get_latest_by_project_id(project_id)
        if storyboard is None:
            raise ValueError(f"No storyboard found for project {project_id}")

        # 2. Load project for quality_tier
        project = await self.project_repo.get_by_id(project_id)
        quality_tier = project.quality_tier if project else "normal"

        # 3. Get all shots
        all_shots = await self.shot_repo.get_by_storyboard_id(storyboard.id)

        task_ids: list[str] = []
        skipped = 0

        for shot in all_shots:
            # Only process shots with video_status='pending'
            if shot.video_status != "pending":
                continue

            # Skip shots without a selected image
            if shot.selected_image_id is None:
                skipped += 1
                continue

            # Load asset to get image path
            asset = await self.asset_repo.get_by_id(shot.selected_image_id)
            image_path = asset.storage_path if asset else ""

            task = await self.task_repo.create(
                {
                    "project_id": project_id,
                    "task_type": "video_generation",
                    "status": "pending",
                    "provider_name": "kling",
                    "shot_id": shot.id,
                    "input_params": {
                        "shot_id": str(shot.id),
                        "image_path": image_path,
                        "prompt": params.get("prompt", ""),
                        "seed": params.get("seed", -1),
                        "frames": params.get("frames", 121),
                        "quality_tier": quality_tier,
                    },
                }
            )
            shot.video_status = "generating"
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
            "skipped": skipped,
        }

    async def get_progress(self, project_id: UUID) -> dict:
        """Get aggregate video generation progress.

        Returns: {total_shots, completed, failed, pending, running, progress}
        """
        # 1. Load latest storyboard shots
        storyboard = await self.storyboard_repo.get_latest_by_project_id(project_id)
        if storyboard is None:
            return {
                "total_shots": 0,
                "completed": 0,
                "failed": 0,
                "pending": 0,
                "running": 0,
                "progress": 0.0,
            }

        shots = await self.shot_repo.get_by_storyboard_id(storyboard.id)

        # 2. Count by video_status
        total = len(shots)
        completed = sum(1 for s in shots if s.video_status == "completed")
        failed = sum(1 for s in shots if s.video_status == "failed")
        pending = sum(1 for s in shots if s.video_status == "pending")
        running = sum(1 for s in shots if s.video_status == "generating")

        # 3. Calculate progress as completed/total
        progress = completed / total if total > 0 else 0.0

        return {
            "total_shots": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "running": running,
            "progress": round(progress, 4),
        }
