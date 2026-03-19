from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ShotImageGenerateRequest(BaseModel):
    """Request to generate an image for a shot."""
    character_ids: list[UUID] = []  # character references for consistency
    seed: int = -1
    width: int = 1024
    height: int = 1024


class ShotImageBatchRequest(BaseModel):
    """Request to batch-generate images for all pending shots."""
    character_ids: list[UUID] = []
    seed: int = -1


class ShotImageCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    storage_path: str | None = None
    oss_url: str | None = None
    asset_category: str | None = None
    created_at: datetime


class ShotDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence_number: int
    scene_number: int
    image_prompt: str | None = None
    narration_text: str | None = None
    scene_description: str | None = None
    image_status: str
    video_status: str
    tts_status: str
    duration_seconds: float | None = None
    selected_image_id: UUID | None = None
    generated_video_id: UUID | None = None
    tts_audio_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
