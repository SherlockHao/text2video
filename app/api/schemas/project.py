from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.constants import ProjectStatus


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    content_type: str = "narration"
    visual_style: str = "manga"
    aspect_ratio: str = "16:9"
    duration_target: int = 60
    quality_tier: str = "normal"
    source_text: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content_type: Optional[str] = None
    visual_style: Optional[str] = None
    aspect_ratio: Optional[str] = None
    duration_target: Optional[int] = None
    quality_tier: Optional[str] = None
    source_text: Optional[str] = None
    status: Optional[ProjectStatus] = None


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str
    content_type: str
    visual_style: str
    aspect_ratio: str
    duration_target: int
    quality_tier: str
    source_text: Optional[str] = None
    current_step: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
