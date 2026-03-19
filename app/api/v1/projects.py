from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])

_NOT_IMPLEMENTED = {"detail": "Not implemented yet"}


@router.post("", status_code=201, response_model=ProjectResponse)
async def create_project(body: ProjectCreate) -> JSONResponse:
    """Create a new project."""
    return JSONResponse(status_code=501, content=_NOT_IMPLEMENTED)


@router.get("", response_model=list[ProjectResponse])
async def list_projects() -> JSONResponse:
    """List all projects."""
    return JSONResponse(status_code=501, content=_NOT_IMPLEMENTED)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID) -> JSONResponse:
    """Get a single project by ID."""
    return JSONResponse(status_code=501, content=_NOT_IMPLEMENTED)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: UUID, body: ProjectUpdate) -> JSONResponse:
    """Update a project."""
    return JSONResponse(status_code=501, content=_NOT_IMPLEMENTED)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: UUID) -> JSONResponse:
    """Soft-delete a project."""
    return JSONResponse(status_code=501, content=_NOT_IMPLEMENTED)
