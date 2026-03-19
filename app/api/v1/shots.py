from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.shot import (
    ShotDetailResponse,
    ShotImageBatchRequest,
    ShotImageCandidateResponse,
    ShotImageGenerateRequest,
)
from app.dependencies import get_arq_pool, get_db
from app.services.image_generation_service import ImageGenerationService

router = APIRouter(prefix="/projects", tags=["shots"])


@router.post(
    "/{project_id}/shots/{shot_id}/generate-image",
    status_code=201,
)
async def generate_shot_image(
    project_id: UUID,
    shot_id: UUID,
    body: ShotImageGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> dict:
    """Generate an image for a specific shot."""
    service = ImageGenerationService(db)
    params = body.model_dump() if body else {}
    try:
        task = await service.generate_shot_image(
            project_id=project_id,
            shot_id=shot_id,
            params=params,
            arq_pool=arq_pool,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"task_id": str(task.id), "status": task.status}


@router.get(
    "/{project_id}/shots/{shot_id}/images",
    response_model=list[ShotImageCandidateResponse],
)
async def list_shot_images(
    project_id: UUID,
    shot_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ShotImageCandidateResponse]:
    """List all image candidates for a shot."""
    service = ImageGenerationService(db)
    assets = await service.list_shot_images(shot_id)
    return [ShotImageCandidateResponse.model_validate(a) for a in assets]


@router.post(
    "/{project_id}/shots/{shot_id}/images/{image_id}/select",
    response_model=ShotDetailResponse,
)
async def select_shot_image(
    project_id: UUID,
    shot_id: UUID,
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ShotDetailResponse:
    """Select an image for a shot."""
    service = ImageGenerationService(db)
    try:
        shot = await service.select_shot_image(shot_id, image_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ShotDetailResponse.model_validate(shot)


@router.post(
    "/{project_id}/shots/generate-images-batch",
    status_code=201,
)
async def generate_images_batch(
    project_id: UUID,
    body: ShotImageBatchRequest | None = None,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> dict:
    """Batch generate images for all pending shots in the latest storyboard."""
    service = ImageGenerationService(db)
    params = body.model_dump() if body else {}
    try:
        tasks = await service.generate_batch(
            project_id=project_id,
            params=params,
            arq_pool=arq_pool,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "tasks": [{"task_id": str(t.id), "status": t.status} for t in tasks],
        "count": len(tasks),
    }
