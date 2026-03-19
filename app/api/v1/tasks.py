from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.schemas.task import TaskCreate, TaskResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])

_NOT_IMPLEMENTED = {"detail": "Not implemented yet"}


@router.post("", status_code=201, response_model=TaskResponse)
async def submit_task(body: TaskCreate) -> JSONResponse:
    """Submit a new AI task."""
    return JSONResponse(status_code=501, content=_NOT_IMPLEMENTED)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID) -> JSONResponse:
    """Get task status by ID."""
    return JSONResponse(status_code=501, content=_NOT_IMPLEMENTED)
