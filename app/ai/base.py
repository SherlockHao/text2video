"""
External AI Provider base classes.

All external AI integrations (LLM, image gen, video gen, TTS) implement
the ExternalAIProvider interface. This supports async submit-then-poll
patterns used by most AI APIs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class JobState(str, Enum):
    """State of an external AI job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobStatus:
    """Status of an external AI job."""
    state: JobState
    result_url: Optional[str] = None
    result_data: Optional[bytes] = None
    error: Optional[str] = None
    progress: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class AIResult:
    """Final result of an AI operation."""
    success: bool
    output_url: Optional[str] = None
    output_data: Optional[bytes] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class ExternalAIProvider(ABC):
    """
    Abstract base for all external AI API integrations.

    Supports two patterns:
    1. Submit-then-poll (async): submit_job() -> poll_job() loop -> download_result()
    2. Sync call: submit_job() returns result directly (poll_job returns completed immediately)
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier."""
        ...

    @abstractmethod
    async def submit_job(self, params: dict) -> str:
        """
        Submit a job to the external API.

        Args:
            params: Provider-specific parameters.

        Returns:
            External job ID (or internal tracking ID for sync providers).
        """
        ...

    @abstractmethod
    async def poll_job(self, external_job_id: str) -> JobStatus:
        """
        Poll the status of a submitted job.

        Args:
            external_job_id: The ID returned by submit_job().

        Returns:
            Current job status with state, progress, and optional result.
        """
        ...

    async def cancel_job(self, external_job_id: str) -> bool:
        """Best-effort job cancellation. Default: no-op."""
        return False

    async def download_result(self, result_url: str) -> bytes:
        """
        Download the generated artifact from a URL.

        Default implementation uses httpx.
        """
        import httpx
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(result_url)
            response.raise_for_status()
            return response.content
