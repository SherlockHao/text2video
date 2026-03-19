from uuid import UUID

from pydantic import BaseModel


class VideoGenerateRequest(BaseModel):
    """Request to generate video for a shot."""
    prompt: str = ""  # optional motion prompt
    seed: int = -1
    frames: int = 121  # ~5s @24fps


class VideoBatchRequest(BaseModel):
    """Request to batch-generate videos for all shots with selected images."""
    prompt: str = ""
    seed: int = -1
    frames: int = 121


class VideoProgressResponse(BaseModel):
    total_shots: int
    completed: int
    failed: int
    pending: int
    running: int
    progress: float  # 0.0 to 1.0


class VideoBatchResponse(BaseModel):
    total_shots: int
    tasks_created: int
    task_ids: list[str]
    skipped: int  # shots without selected images
