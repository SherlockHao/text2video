import asyncio
import logging

from app.ai.base import AIProvider, AIResult

logger = logging.getLogger(__name__)


class TextToVideoProvider(AIProvider):
    """Stub text-to-video provider for development."""

    @property
    def provider_name(self) -> str:
        return "text_to_video"

    async def generate(self, params: dict) -> AIResult:
        logger.info("[%s] generate called with params: %s", self.provider_name, params)
        await asyncio.sleep(2)  # simulate processing
        logger.info("[%s] generate complete", self.provider_name)
        return AIResult(
            success=True,
            output_url="/mock/video.mp4",
            metadata={"provider": self.provider_name},
        )

    async def check_status(self, job_id: str) -> AIResult:
        logger.info("[%s] check_status called for job: %s", self.provider_name, job_id)
        return AIResult(
            success=True,
            metadata={"provider": self.provider_name, "job_id": job_id, "status": "complete"},
        )
