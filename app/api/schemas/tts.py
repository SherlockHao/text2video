from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TTSConfigUpdate(BaseModel):
    voice_id: str = ""
    speed: float = 1.0
    stability: float = 0.5
    similarity_boost: float = 0.75
    language: str = "zh"


class TTSConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    voice_id: str
    speed: float
    stability: float
    similarity_boost: float
    language: str
    created_at: datetime
    updated_at: datetime


class TTSPreviewRequest(BaseModel):
    text: str
    voice_id: str = ""
    speed: float = 1.0
    stability: float = 0.5
    similarity_boost: float = 0.75


class TTSPreviewResponse(BaseModel):
    audio_url: str | None = None
    duration_estimate: float  # estimated seconds
    char_count: int


class VoiceInfo(BaseModel):
    voice_id: str
    name: str
    labels: dict = {}
    preview_url: str | None = None


class TTSBatchResponse(BaseModel):
    total_shots: int
    tasks_created: int
    task_ids: list[str]
