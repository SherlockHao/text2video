from uuid import UUID

from pydantic import BaseModel


class AssemblyTriggerResponse(BaseModel):
    task_id: str
    status: str
    message: str = ""


class AssemblyStatusResponse(BaseModel):
    status: str  # pending, running, completed, failed
    progress: float  # 0.0 to 1.0
    final_video_url: str | None = None
    asset_package_url: str | None = None
    error: str | None = None
    shots_ready: int  # shots with both video + tts completed
    shots_total: int


class ProjectOutputResponse(BaseModel):
    project_id: UUID
    project_name: str
    status: str
    final_video: dict | None = None  # {asset_id, storage_path, file_size}
    asset_package: dict | None = None  # {asset_id, storage_path, file_size}
    shots: list[dict] = []  # per-shot output info
