import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import AITask
from app.repositories.task_repo import TaskRepository


class TaskService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = TaskRepository(session)

    async def create_task(
        self, project_id: uuid.UUID, task_type: str, input_params: dict | None = None
    ) -> AITask:
        data = {
            "project_id": project_id,
            "task_type": task_type,
            "input_params": input_params or {},
        }
        task = await self.repo.create(data)
        await self.session.commit()
        return task

    async def get_task(self, task_id: uuid.UUID) -> AITask | None:
        return await self.repo.get_by_id(task_id)

    async def update_progress(
        self, task_id: uuid.UUID, progress: float
    ) -> AITask | None:
        task = await self.repo.update_progress(task_id, progress)
        if task:
            await self.session.commit()
        return task

    async def enqueue_task(self, task_id: uuid.UUID) -> AITask | None:
        """Placeholder for task queue integration (e.g., Celery, ARQ)."""
        task = await self.repo.update(
            task_id, {"status": "queued", "started_at": datetime.now(timezone.utc)}
        )
        if task:
            await self.session.commit()
        return task
