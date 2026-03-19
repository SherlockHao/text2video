import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.repositories.base import BaseRepository


class AssetRepository(BaseRepository[Asset]):
    def __init__(self, session: AsyncSession):
        super().__init__(Asset, session)

    async def get_by_project_id(
        self, project_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Asset]:
        query = (
            self._base_query()
            .where(Asset.project_id == project_id)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
