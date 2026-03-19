import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sensitive_word import SensitiveWordHit
from app.repositories.base import BaseRepository


class SensitiveWordHitRepository(BaseRepository[SensitiveWordHit]):
    def __init__(self, session: AsyncSession):
        super().__init__(SensitiveWordHit, session)

    async def get_by_project_id(
        self, project_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[SensitiveWordHit]:
        query = (
            self._base_query()
            .where(SensitiveWordHit.project_id == project_id)
            .order_by(SensitiveWordHit.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
