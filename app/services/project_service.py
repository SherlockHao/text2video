import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.repositories.project_repo import ProjectRepository


class ProjectService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ProjectRepository(session)

    async def create_project(self, user_id: uuid.UUID, data: dict) -> Project:
        data["user_id"] = user_id
        project = await self.repo.create(data)
        await self.session.commit()
        return project

    async def get_project(self, project_id: uuid.UUID) -> Project | None:
        return await self.repo.get_by_id(project_id)

    async def list_projects(
        self, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Project]:
        return await self.repo.get_by_user_id(user_id, skip=skip, limit=limit)

    async def update_project(
        self, project_id: uuid.UUID, data: dict
    ) -> Project | None:
        project = await self.repo.update(project_id, data)
        if project:
            await self.session.commit()
        return project

    async def delete_project(self, project_id: uuid.UUID) -> bool:
        deleted = await self.repo.soft_delete(project_id)
        if deleted:
            await self.session.commit()
        return deleted
