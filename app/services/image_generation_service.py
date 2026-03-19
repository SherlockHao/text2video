import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.shot import Shot
from app.models.task import AITask
from app.repositories.asset_repo import AssetRepository
from app.repositories.shot_repo import ShotRepository
from app.repositories.storyboard_repo import StoryboardRepository
from app.repositories.task_repo import TaskRepository

logger = logging.getLogger(__name__)


class ImageGenerationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.shot_repo = ShotRepository(session)
        self.task_repo = TaskRepository(session)
        self.asset_repo = AssetRepository(session)
        self.storyboard_repo = StoryboardRepository(session)

    async def generate_shot_image(
        self, project_id: UUID, shot_id: UUID, params: dict, arq_pool=None
    ) -> AITask:
        """Generate an image for a specific shot.

        Creates AITask with type=image_generation, input_params includes shot's image_prompt.
        """
        shot = await self.shot_repo.get_by_id(shot_id)
        if shot is None:
            raise ValueError(f"Shot {shot_id} not found")

        # Create AITask for shot image generation
        task = await self.task_repo.create(
            {
                "project_id": project_id,
                "task_type": "image_generation",
                "status": "pending",
                "provider_name": "jimeng",
                "shot_id": shot_id,
                "input_params": {
                    "shot_id": str(shot_id),
                    "image_prompt": shot.image_prompt or "",
                    "character_ids": [str(cid) for cid in params.get("character_ids", [])],
                    "seed": params.get("seed", -1),
                    "width": params.get("width", 1024),
                    "height": params.get("height", 1024),
                },
            }
        )

        # Update shot status
        shot.image_status = "generating"
        await self.session.flush()

        # Enqueue to arq
        if arq_pool is not None:
            await arq_pool.enqueue_job("process_ai_task", str(task.id))

        await self.session.commit()
        return task

    async def generate_batch(
        self, project_id: UUID, params: dict, arq_pool=None
    ) -> list[AITask]:
        """Generate images for all shots with image_status='pending' in the latest storyboard."""
        storyboard = await self.storyboard_repo.get_latest_by_project_id(project_id)
        if storyboard is None:
            raise ValueError(f"No storyboard found for project {project_id}")

        pending_shots = await self.shot_repo.get_pending_shots(
            storyboard.id, phase="image"
        )

        tasks = []
        for shot in pending_shots:
            task = await self.task_repo.create(
                {
                    "project_id": project_id,
                    "task_type": "image_generation",
                    "status": "pending",
                    "provider_name": "jimeng",
                    "shot_id": shot.id,
                    "input_params": {
                        "shot_id": str(shot.id),
                        "image_prompt": shot.image_prompt or "",
                        "character_ids": [
                            str(cid) for cid in params.get("character_ids", [])
                        ],
                        "seed": params.get("seed", -1),
                    },
                }
            )
            shot.image_status = "generating"
            tasks.append(task)

        await self.session.flush()

        # Enqueue all tasks to arq
        if arq_pool is not None:
            for task in tasks:
                await arq_pool.enqueue_job("process_ai_task", str(task.id))

        await self.session.commit()
        return tasks

    async def list_shot_images(self, shot_id: UUID) -> list[Asset]:
        """List all image candidates for a shot."""
        from sqlalchemy import select

        query = (
            select(Asset)
            .where(Asset.asset_category == "shot_image_candidate")
            .where(
                Asset.metadata_["shot_id"].as_string() == str(shot_id)
            )
        )
        # Fallback: also check via source task's shot_id
        # For now, use a simpler approach via tasks
        query2 = (
            select(Asset)
            .join(AITask, Asset.source_task_id == AITask.id)
            .where(AITask.shot_id == shot_id)
            .where(Asset.asset_category == "shot_image_candidate")
        )
        result = await self.session.execute(query2)
        assets = list(result.scalars().all())

        # If no results via task join, try direct metadata query
        if not assets:
            result2 = await self.session.execute(query)
            assets = list(result2.scalars().all())

        return assets

    async def select_shot_image(self, shot_id: UUID, image_id: UUID) -> Shot:
        """Select an image for a shot. Updates shot.selected_image_id and shot.image_status='completed'."""
        shot = await self.shot_repo.get_by_id(shot_id)
        if shot is None:
            raise ValueError(f"Shot {shot_id} not found")

        asset = await self.asset_repo.get_by_id(image_id)
        if asset is None:
            raise ValueError(f"Asset {image_id} not found")

        shot.selected_image_id = image_id
        shot.image_status = "completed"
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(shot)
        return shot
