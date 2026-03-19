import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.repositories.base import BaseRepository


class CharacterRepository(BaseRepository[Character]):
    def __init__(self, session: AsyncSession):
        super().__init__(Character, session)

    async def get_by_user_id(
        self,
        user_id: uuid.UUID,
        filters: dict[str, Any] | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Character]:
        """Get characters for a user with optional tag filtering.

        Args:
            user_id: The user ID to filter by.
            filters: Optional dict. Supports 'tags' key with a list of tags
                     to filter characters that contain any of the given tags.
            skip: Pagination offset.
            limit: Pagination limit.
        """
        query = (
            self._base_query()
            .where(Character.user_id == user_id)
        )

        if filters:
            tags = filters.get("tags")
            if tags and isinstance(tags, list):
                # JSONB contains any of the provided tags
                for tag in tags:
                    query = query.where(Character.tags.contains([tag]))

        query = query.offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())
