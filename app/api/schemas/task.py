from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.constants import TaskType


class TaskCreate(BaseModel):
    project_id: UUID
    task_type: TaskType
    input_params: dict = Field(default_factory=dict)


class TaskResponse(BaseModel):
    id: UUID
    project_id: UUID
    task_type: str
    status: str
    progress: float
    created_at: datetime

    model_config = {"from_attributes": True}
