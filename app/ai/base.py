from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AIResult:
    success: bool
    output_url: Optional[str] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class AIProvider(ABC):
    @abstractmethod
    async def generate(self, params: dict) -> AIResult:
        """Execute AI generation task."""
        ...

    @abstractmethod
    async def check_status(self, job_id: str) -> AIResult:
        """Check status of an async AI job."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...
