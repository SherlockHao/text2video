import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shot import Shot
from app.repositories.base import BaseRepository


class ShotRepository(BaseRepository[Shot]):
    def __init__(self, session: AsyncSession):
        super().__init__(Shot, session)

    async def get_by_storyboard_id(
        self, storyboard_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Shot]:
        query = (
            self._base_query()
            .where(Shot.storyboard_id == storyboard_id)
            .order_by(Shot.sequence_number.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_pending_shots(
        self, storyboard_id: uuid.UUID, phase: str
    ) -> list[Shot]:
        """Get shots with pending status for the given phase.

        Args:
            storyboard_id: The storyboard to query.
            phase: One of 'image', 'video', or 'tts'.
        """
        status_column_map = {
            "image": Shot.image_status,
            "video": Shot.video_status,
            "tts": Shot.tts_status,
        }
        status_col = status_column_map.get(phase)
        if status_col is None:
            return []

        query = (
            self._base_query()
            .where(Shot.storyboard_id == storyboard_id)
            .where(status_col == "pending")
            .order_by(Shot.sequence_number.asc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
