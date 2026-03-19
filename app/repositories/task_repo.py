import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import AITask
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[AITask]):
    def __init__(self, session: AsyncSession):
        super().__init__(AITask, session)

    async def get_pending_tasks(self, limit: int = 50) -> list[AITask]:
        query = (
            select(AITask)
            .where(AITask.status == "pending")
            .order_by(AITask.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update_progress(
        self, task_id: uuid.UUID, progress: float
    ) -> AITask | None:
        stmt = (
            update(AITask)
            .where(AITask.id == task_id)
            .values(progress=progress)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        return await self.get_by_id(task_id)
