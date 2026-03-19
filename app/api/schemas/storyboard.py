from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StoryboardGenerateRequest(BaseModel):
    source_text: Optional[str] = None


class ShotResponse(BaseModel):
    id: UUID
    sequence_number: int
    scene_number: int
    image_prompt: Optional[str] = None
    narration_text: Optional[str] = None
    scene_description: Optional[str] = None
    image_status: str
    video_status: str
    tts_status: str
    duration_seconds: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class StoryboardResponse(BaseModel):
    id: UUID
    project_id: UUID
    version: int
    scene_count: int
    status: str
    shots: list[ShotResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ShotUpdateRequest(BaseModel):
    image_prompt: Optional[str] = None
    narration_text: Optional[str] = None
    scene_description: Optional[str] = None
