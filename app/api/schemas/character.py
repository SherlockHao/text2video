from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CharacterCreate(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = []
    visual_style: str = "manga"


class CharacterUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class CharacterImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    asset_id: UUID | None = None
    generation_seed: int | None = None
    is_selected: bool
    attempt_number: int
    created_at: datetime


class CharacterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: str
    tags: list
    visual_style: str
    reference_image_id: UUID | None = None
    seed_value: int | None = None
    created_at: datetime
    updated_at: datetime
