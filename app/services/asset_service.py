import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.repositories.asset_repo import AssetRepository


class AssetService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = AssetRepository(session)

    async def create_asset(self, project_id: uuid.UUID, data: dict) -> Asset:
        data["project_id"] = project_id
        asset = await self.repo.create(data)
        await self.session.commit()
        return asset

    async def get_asset(self, asset_id: uuid.UUID) -> Asset | None:
        return await self.repo.get_by_id(asset_id)

    async def list_assets(
        self, project_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Asset]:
        return await self.repo.get_by_project_id(project_id, skip=skip, limit=limit)

    async def update_asset(self, asset_id: uuid.UUID, data: dict) -> Asset | None:
        asset = await self.repo.update(asset_id, data)
        if asset:
            await self.session.commit()
        return asset

    async def delete_asset(self, asset_id: uuid.UUID) -> bool:
        deleted = await self.repo.soft_delete(asset_id)
        if deleted:
            await self.session.commit()
        return deleted
