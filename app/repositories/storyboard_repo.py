import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.storyboard import Storyboard
from app.repositories.base import BaseRepository


class StoryboardRepository(BaseRepository[Storyboard]):
    def __init__(self, session: AsyncSession):
        super().__init__(Storyboard, session)

    async def get_by_project_id(
        self, project_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Storyboard]:
        query = (
            self._base_query()
            .where(Storyboard.project_id == project_id)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_latest_by_project_id(
        self, project_id: uuid.UUID
    ) -> Storyboard | None:
        query = (
            self._base_query()
            .where(Storyboard.project_id == project_id)
            .order_by(Storyboard.version.desc())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
