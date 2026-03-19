import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.tts import (
    TTSBatchResponse,
    TTSConfigResponse,
    TTSConfigUpdate,
    TTSPreviewRequest,
    TTSPreviewResponse,
    VoiceInfo,
)
from app.core.config import settings
from app.dependencies import get_arq_pool, get_db
from app.services.tts_service import TTSService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tts"])

# Hardcoded Chinese voices for MVP (used when no ElevenLabs API key is configured)
_DEFAULT_VOICES: list[dict] = [
    {
        "voice_id": "pNInz6obpgDQGcFmaJgB",
        "name": "Adam",
        "labels": {"accent": "american", "gender": "male"},
        "preview_url": None,
    },
    {
        "voice_id": "EXAVITQu4vr4xnSDxMaL",
        "name": "Bella",
        "labels": {"accent": "american", "gender": "female"},
        "preview_url": None,
    },
    {
        "voice_id": "jBpfuIE2acCO8z3wKNLl",
        "name": "Gigi",
        "labels": {"accent": "american", "gender": "female", "use_case": "animation"},
        "preview_url": None,
    },
    {
        "voice_id": "onwK4e9ZLuTAKqWW03F9",
        "name": "Daniel",
        "labels": {"accent": "british", "gender": "male"},
        "preview_url": None,
    },
    {
        "voice_id": "XB0fDUnXU5powFXDhCwa",
        "name": "Charlotte",
        "labels": {"accent": "english-swedish", "gender": "female"},
        "preview_url": None,
    },
]


@router.get("/tts/voices", response_model=list[VoiceInfo])
async def list_voices() -> list[VoiceInfo]:
    """List available ElevenLabs voices.

    Returns a hardcoded list of common voices if no API key is configured.
    If API key is set, calls ElevenLabs API.
    """
    if settings.ELEVENLABS_API_KEY:
        # TODO: Call ElevenLabs API when key is configured
        # For now, fall through to default list
        pass

    return [VoiceInfo(**v) for v in _DEFAULT_VOICES]


@router.get(
    "/projects/{project_id}/tts/config",
    response_model=TTSConfigResponse,
)
async def get_tts_config(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> TTSConfigResponse:
    """Get TTS config for a project (creates default if not exists)."""
    service = TTSService(db)
    config = await service.get_or_create_config(project_id)
    return TTSConfigResponse.model_validate(config)


@router.put(
    "/projects/{project_id}/tts/config",
    response_model=TTSConfigResponse,
)
async def update_tts_config(
    project_id: UUID,
    body: TTSConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> TTSConfigResponse:
    """Update TTS config for a project."""
    service = TTSService(db)
    config = await service.update_config(project_id, body.model_dump(exclude_unset=True))
    return TTSConfigResponse.model_validate(config)


@router.post(
    "/projects/{project_id}/tts/preview",
    response_model=TTSPreviewResponse,
)
async def preview_tts(
    project_id: UUID,
    body: TTSPreviewRequest,
    db: AsyncSession = Depends(get_db),
) -> TTSPreviewResponse:
    """Generate a TTS preview (returns duration estimate for MVP)."""
    service = TTSService(db)
    result = await service.preview(
        text=body.text,
        voice_id=body.voice_id,
        speed=body.speed,
        stability=body.stability,
        similarity_boost=body.similarity_boost,
    )
    return TTSPreviewResponse(**result)


@router.post(
    "/projects/{project_id}/tts/generate-batch",
    status_code=201,
    response_model=TTSBatchResponse,
)
async def generate_batch_tts(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    arq_pool=Depends(get_arq_pool),
) -> TTSBatchResponse:
    """Trigger batch TTS generation for all shots with pending TTS status."""
    service = TTSService(db)
    try:
        result = await service.generate_batch(project_id=project_id, arq_pool=arq_pool)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return TTSBatchResponse(**result)


@router.get(
    "/projects/{project_id}/tts/status",
)
async def get_tts_status(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get per-shot TTS generation status for a project."""
    service = TTSService(db)
    return await service.get_shot_tts_status(project_id)
