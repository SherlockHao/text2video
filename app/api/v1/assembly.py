from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.assembly import (
    AssemblyStatusResponse,
    AssemblyTriggerResponse,
    ProjectOutputResponse,
)
from app.dependencies import get_arq_pool, get_db
from app.services.assembly_service import AssemblyService

router = APIRouter(prefix="/projects", tags=["assembly"])


@router.post(
    "/{project_id}/assembly/generate",
    status_code=201,
    response_model=AssemblyTriggerResponse,
)
async def trigger_assembly(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> AssemblyTriggerResponse:
    """Trigger assembly for a project (combine all shot videos + TTS audio)."""
    service = AssemblyService(db)
    try:
        task = await service.trigger_assembly(
            project_id=project_id,
            arq_pool=arq_pool,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return AssemblyTriggerResponse(
        task_id=str(task.id),
        status=task.status,
        message="Assembly task created successfully.",
    )


@router.get(
    "/{project_id}/assembly/status",
    response_model=AssemblyStatusResponse,
)
async def get_assembly_status(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> AssemblyStatusResponse:
    """Get assembly status for a project."""
    service = AssemblyService(db)
    result = await service.get_status(project_id)
    return AssemblyStatusResponse(**result)


@router.get(
    "/{project_id}/output",
    response_model=ProjectOutputResponse,
)
async def get_project_output(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ProjectOutputResponse:
    """Get final project outputs (MP4 video + ZIP asset package)."""
    service = AssemblyService(db)
    try:
        result = await service.get_output(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ProjectOutputResponse(**result)
