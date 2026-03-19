import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character_image import CharacterImage
from app.repositories.base import BaseRepository


class CharacterImageRepository(BaseRepository[CharacterImage]):
    def __init__(self, session: AsyncSession):
        super().__init__(CharacterImage, session)

    async def get_by_character_id(
        self, character_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[CharacterImage]:
        query = (
            self._base_query()
            .where(CharacterImage.character_id == character_id)
            .order_by(CharacterImage.attempt_number.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
