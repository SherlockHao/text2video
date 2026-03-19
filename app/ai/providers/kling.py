"""
Kling video generation (normal quality) — STUB.

Will be implemented when Kling API credentials are provided.
Currently falls back to Seedance2 for all video generation.
"""

import logging

from app.ai.base import ExternalAIProvider, JobState, JobStatus
from app.ai.providers import register_provider

logger = logging.getLogger(__name__)


class KlingProvider(ExternalAIProvider):
    """Kling video generation (normal quality) — STUB.

    Will be implemented when Kling API credentials are provided.
    Currently falls back to Seedance2 for all video generation.
    """

    @property
    def provider_name(self) -> str:
        return "kling"

    async def submit_job(self, params: dict) -> str:
        """Delegate to Seedance2 provider as fallback."""
        from app.ai.providers.seedance2 import Seedance2Provider

        logger.info("Kling stub: delegating to Seedance2 fallback")
        self._fallback = Seedance2Provider()
        return await self._fallback.submit_job(params)

    async def poll_job(self, external_job_id: str) -> JobStatus:
        """Poll the fallback provider, or fail if no fallback is set."""
        if hasattr(self, "_fallback"):
            return await self._fallback.poll_job(external_job_id)
        return JobStatus(
            state=JobState.FAILED, error="Kling not configured, no fallback"
        )


# Auto-register when module is imported
register_provider("kling", KlingProvider)
