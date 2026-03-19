from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import TaskType


class TaskCreate(BaseModel):
    project_id: UUID
    task_type: TaskType
    input_params: dict = Field(default_factory=dict)


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    task_type: str
    status: str
    progress: float
    provider_name: Optional[str] = None
    error_message: Optional[str] = None
    step_name: Optional[str] = None
    retry_count: int = 0
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
