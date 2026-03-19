from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.project import (
    ProjectCreate,
    ProjectResponse,
    ProjectStatusResponse,
    ProjectUpdate,
    ResumeResponse,
)
from app.dependencies import get_arq_pool, get_db
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])

# Placeholder user_id until auth is implemented
_DEFAULT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


@router.post("", status_code=201, response_model=ProjectResponse)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Create a new project."""
    service = ProjectService(db)
    project = await service.create_project(
        user_id=_DEFAULT_USER_ID,
        data=body.model_dump(),
    )
    return ProjectResponse.model_validate(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectResponse]:
    """List all projects (paginated)."""
    service = ProjectService(db)
    projects = await service.list_projects(
        user_id=_DEFAULT_USER_ID, skip=skip, limit=limit
    )
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Get a single project by ID."""
    service = ProjectService(db)
    project = await service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """Update a project."""
    service = ProjectService(db)
    project = await service.update_project(
        project_id, body.model_dump(exclude_unset=True)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a project."""
    service = ProjectService(db)
    deleted = await service.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/{project_id}/status", response_model=ProjectStatusResponse)
async def get_project_status(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ProjectStatusResponse:
    """Get comprehensive project pipeline status."""
    service = ProjectService(db)
    try:
        status = await service.get_project_status(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ProjectStatusResponse(**status)


@router.post("/{project_id}/resume", response_model=ResumeResponse)
async def resume_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> ResumeResponse:
    """Resume a project from checkpoint (retry failed tasks)."""
    service = ProjectService(db)
    try:
        result = await service.resume_from_checkpoint(project_id, arq_pool=arq_pool)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ResumeResponse(**result)
