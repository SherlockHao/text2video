import uuid
from datetime import datetime, timezone
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, model: type[T], session: AsyncSession):
        self.model = model
        self.session = session

    def _base_query(self):
        """Return base query filtering out soft-deleted records if applicable."""
        query = select(self.model)
        if hasattr(self.model, "deleted_at"):
            query = query.where(self.model.deleted_at.is_(None))  # type: ignore[union-attr]
        return query

    async def get_by_id(self, id: uuid.UUID) -> T | None:
        query = self._base_query().where(self.model.id == id)  # type: ignore[attr-defined]
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_all(self, skip: int = 0, limit: int = 100) -> list[T]:
        query = self._base_query().offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(self, data: dict) -> T:
        instance = self.model(**data)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, id: uuid.UUID, data: dict) -> T | None:
        instance = await self.get_by_id(id)
        if instance is None:
            return None
        for key, value in data.items():
            setattr(instance, key, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def soft_delete(self, id: uuid.UUID) -> bool:
        instance = await self.get_by_id(id)
        if instance is None:
            return False
        if hasattr(instance, "deleted_at"):
            instance.deleted_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
            await self.session.flush()
            return True
        return False
