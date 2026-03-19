from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.video import (
    VideoBatchRequest,
    VideoBatchResponse,
    VideoGenerateRequest,
    VideoProgressResponse,
)
from app.dependencies import get_arq_pool, get_db
from app.services.video_generation_service import VideoGenerationService

router = APIRouter(prefix="/projects", tags=["videos"])


@router.post(
    "/{project_id}/shots/{shot_id}/generate-video",
    status_code=201,
)
async def generate_shot_video(
    project_id: UUID,
    shot_id: UUID,
    body: VideoGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> dict:
    """Generate video for a specific shot."""
    service = VideoGenerationService(db)
    params = body.model_dump() if body else {}
    try:
        task = await service.generate_shot_video(
            project_id=project_id,
            shot_id=shot_id,
            params=params,
            arq_pool=arq_pool,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"task_id": str(task.id), "status": task.status}


@router.post(
    "/{project_id}/video/generate-batch",
    status_code=201,
    response_model=VideoBatchResponse,
)
async def generate_video_batch(
    project_id: UUID,
    body: VideoBatchRequest | None = None,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> VideoBatchResponse:
    """Batch generate videos for all shots with selected images."""
    service = VideoGenerationService(db)
    params = body.model_dump() if body else {}
    try:
        result = await service.generate_batch(
            project_id=project_id,
            params=params,
            arq_pool=arq_pool,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return VideoBatchResponse(**result)


@router.get(
    "/{project_id}/video/progress",
    response_model=VideoProgressResponse,
)
async def get_video_progress(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> VideoProgressResponse:
    """Get aggregate video generation progress for a project."""
    service = VideoGenerationService(db)
    result = await service.get_progress(project_id)
    return VideoProgressResponse(**result)
