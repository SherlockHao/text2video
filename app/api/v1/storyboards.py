import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.storyboard import (
    ShotResponse,
    ShotUpdateRequest,
    StoryboardGenerateRequest,
    StoryboardResponse,
)
from app.dependencies import get_db, get_arq_pool
from app.services.storyboard_service import StoryboardService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["storyboards"])


@router.post(
    "/{project_id}/storyboard/generate",
    status_code=201,
)
async def generate_storyboard(
    project_id: UUID,
    body: StoryboardGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> dict:
    """Generate a storyboard for a project by submitting a script_breakdown task."""
    service = StoryboardService(db)
    source_text = body.source_text if body else None
    try:
        task = await service.generate_storyboard(
            project_id=project_id,
            source_text=source_text,
            arq_pool=arq_pool,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"task_id": str(task.id), "status": task.status}


@router.get(
    "/{project_id}/storyboard",
    response_model=StoryboardResponse,
)
async def get_storyboard(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> StoryboardResponse:
    """Get the latest storyboard for a project, including all shots."""
    service = StoryboardService(db)
    storyboard = await service.get_storyboard(project_id)
    if storyboard is None:
        raise HTTPException(status_code=404, detail="Storyboard not found")
    return StoryboardResponse.model_validate(storyboard)


@router.put(
    "/{project_id}/storyboard/shots/{shot_id}",
    response_model=ShotResponse,
)
async def update_shot(
    project_id: UUID,
    shot_id: UUID,
    body: ShotUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ShotResponse:
    """Update a shot's editable fields (image_prompt, narration_text, scene_description)."""
    service = StoryboardService(db)
    try:
        shot = await service.update_shot(shot_id, body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ShotResponse.model_validate(shot)


@router.post(
    "/{project_id}/storyboard/regenerate",
    status_code=201,
)
async def regenerate_storyboard(
    project_id: UUID,
    body: StoryboardGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> dict:
    """Regenerate a storyboard (creates a new version)."""
    service = StoryboardService(db)
    source_text = body.source_text if body else None
    try:
        task = await service.generate_storyboard(
            project_id=project_id,
            source_text=source_text,
            arq_pool=arq_pool,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"task_id": str(task.id), "status": task.status}
