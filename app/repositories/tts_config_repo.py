import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tts_config import TTSConfig
from app.repositories.base import BaseRepository


class TTSConfigRepository(BaseRepository[TTSConfig]):
    def __init__(self, session: AsyncSession):
        super().__init__(TTSConfig, session)

    async def get_by_project_id(self, project_id: uuid.UUID) -> TTSConfig | None:
        query = self._base_query().where(TTSConfig.project_id == project_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
