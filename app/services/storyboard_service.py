import logging
import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.ai.prompts.base import get_template
import app.ai.prompts.narration_manga  # noqa: F401 — register template
from app.models.project import Project
from app.models.shot import Shot
from app.models.storyboard import Storyboard
from app.models.task import AITask
from app.repositories.project_repo import ProjectRepository
from app.repositories.shot_repo import ShotRepository
from app.repositories.storyboard_repo import StoryboardRepository
from app.repositories.task_repo import TaskRepository

logger = logging.getLogger(__name__)


class StoryboardService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.storyboard_repo = StoryboardRepository(session)
        self.shot_repo = ShotRepository(session)
        self.task_repo = TaskRepository(session)

    async def generate_storyboard(
        self,
        project_id: UUID,
        source_text: str | None = None,
        arq_pool=None,
    ) -> AITask:
        """
        Initiate storyboard generation for a project.

        1. Load project, resolve source text
        2. Build prompt from template
        3. Create AITask record
        4. Enqueue to arq worker
        5. Update project.current_step

        Args:
            project_id: The project UUID.
            source_text: Optional override text. Falls back to project.source_text.
            arq_pool: arq connection pool for enqueuing jobs.

        Returns:
            The created AITask.

        Raises:
            ValueError: If project not found or no source text available.
        """
        project = await self.project_repo.get_by_id(project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        text = source_text or project.source_text
        if not text:
            raise ValueError("No source text provided and project has no source_text")

        # If source_text was provided as override, also store it on the project
        if source_text and source_text != project.source_text:
            project.source_text = source_text
            await self.session.flush()

        # Build prompts from template registry
        try:
            template_fn = get_template(project.content_type, project.visual_style)
            prompts = template_fn(
                source_text=text,
                content_type=project.content_type,
                visual_style=project.visual_style,
                duration_target=project.duration_target,
                quality_tier=project.quality_tier,
                aspect_ratio=project.aspect_ratio,
            )
        except ValueError:
            # Fallback: use a simple prompt if no template registered
            prompts = {
                "system_prompt": (
                    "You are a professional storyboard writer. "
                    "Break down the script into shots with image prompts and narration."
                ),
                "user_prompt": text,
            }

        # Create AITask
        task = await self.task_repo.create(
            {
                "project_id": project_id,
                "task_type": "script_breakdown",
                "status": "pending",
                "provider_name": "qwen",
                "input_params": {
                    "system_prompt": prompts["system_prompt"],
                    "user_prompt": prompts["user_prompt"],
                },
            }
        )

        # Enqueue to arq
        if arq_pool is not None:
            await arq_pool.enqueue_job("process_ai_task", str(task.id))

        # Update project step
        project.current_step = "script_breakdown"
        await self.session.flush()
        await self.session.commit()

        return task

    async def parse_llm_response(
        self, task_id: UUID, llm_data: dict
    ) -> Storyboard:
        """
        Parse LLM response into Storyboard and Shot records.

        Args:
            task_id: The AITask UUID that produced this response.
            llm_data: The parsed LLM JSON response.

        Returns:
            The created Storyboard with shots.
        """
        task = await self.task_repo.get_by_id(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        project_id = task.project_id

        # Determine version by checking existing storyboards
        latest = await self.storyboard_repo.get_latest_by_project_id(project_id)
        version = (latest.version + 1) if latest else 1

        shots_data = llm_data.get("storyboards", [])

        # Create storyboard
        storyboard = await self.storyboard_repo.create(
            {
                "project_id": project_id,
                "version": version,
                "scene_count": len(shots_data),
                "raw_llm_response": llm_data,
                "status": "completed",
            }
        )

        # Create shots from LLM data
        for idx, shot_data in enumerate(shots_data):
            # Map LLM fields to Shot model fields
            narration_parts = []
            if shot_data.get("description_zh"):
                narration_parts.append(shot_data["description_zh"])
            if shot_data.get("narration_text"):
                narration_parts.append(shot_data["narration_text"])

            await self.shot_repo.create(
                {
                    "storyboard_id": storyboard.id,
                    "sequence_number": shot_data.get("shot_number", idx + 1),
                    "scene_number": shot_data.get("scene_number", 1),
                    "image_prompt": shot_data.get("image_prompt") or shot_data.get("prompt_en"),
                    "narration_text": " ".join(narration_parts) if narration_parts else shot_data.get("narration_text") or shot_data.get("narration"),
                    "scene_description": shot_data.get("scene_description") or shot_data.get("description") or shot_data.get("description_zh"),
                    "duration_seconds": shot_data.get("duration_seconds"),
                }
            )

        await self.session.commit()

        # Reload storyboard with shots
        return await self.get_storyboard(project_id)  # type: ignore[return-value]

    async def get_storyboard(self, project_id: UUID) -> Storyboard | None:
        """
        Get the latest storyboard for a project, eagerly loading shots.
        """
        query = (
            select(Storyboard)
            .where(Storyboard.project_id == project_id)
            .options(selectinload(Storyboard.shots))
            .order_by(Storyboard.version.desc())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def update_shot(self, shot_id: UUID, data: dict) -> Shot:
        """
        Update a shot's editable fields.

        Args:
            shot_id: The shot UUID.
            data: Dict of fields to update (image_prompt, narration_text, scene_description).

        Returns:
            The updated Shot.

        Raises:
            ValueError: If shot not found.
        """
        # Filter to only allowed fields
        allowed = {"image_prompt", "narration_text", "scene_description"}
        update_data = {k: v for k, v in data.items() if k in allowed and v is not None}

        shot = await self.shot_repo.update(shot_id, update_data)
        if shot is None:
            raise ValueError(f"Shot {shot_id} not found")

        await self.session.commit()
        return shot
