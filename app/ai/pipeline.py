import asyncio
import logging
from typing import List, Tuple

from app.ai.base import AIProvider, AIResult

logger = logging.getLogger(__name__)


class AIPipeline:
    """Orchestrates a sequence of AI provider stages."""

    MAX_RETRIES = 3
    BASE_BACKOFF = 1.0  # seconds

    def __init__(self, stages: List[Tuple[str, AIProvider]]) -> None:
        self.stages = stages

    async def run(self, params: dict) -> AIResult:
        """Execute all stages sequentially with retry and progress tracking."""
        total = len(self.stages)
        aggregated_metadata: dict = {}

        for idx, (name, provider) in enumerate(self.stages):
            progress = idx / total
            logger.info(
                "Pipeline stage [%s] starting (progress %.0f%%)",
                name,
                progress * 100,
            )

            result = await self._run_with_retry(name, provider, params)

            if not result.success:
                logger.error(
                    "Pipeline stage [%s] failed: %s", name, result.error
                )
                result.metadata["pipeline_progress"] = progress
                return result

            logger.info("Pipeline stage [%s] complete", name)
            aggregated_metadata[name] = result.metadata
            # Feed the output of the current stage into the next one
            params = {**params, f"{name}_output_url": result.output_url}

        final_progress = 1.0
        logger.info("Pipeline finished (progress %.0f%%)", final_progress * 100)
        return AIResult(
            success=True,
            output_url=result.output_url,
            metadata={
                "pipeline_progress": final_progress,
                "stages": aggregated_metadata,
            },
        )

    async def _run_with_retry(
        self, name: str, provider: AIProvider, params: dict
    ) -> AIResult:
        last_error: str | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = await provider.generate(params)
                if result.success:
                    return result
                last_error = result.error
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Pipeline stage [%s] attempt %d raised: %s",
                    name,
                    attempt,
                    last_error,
                )

            if attempt < self.MAX_RETRIES:
                backoff = self.BASE_BACKOFF * (2 ** (attempt - 1))
                logger.info(
                    "Retrying stage [%s] in %.1fs (attempt %d/%d)",
                    name,
                    backoff,
                    attempt + 1,
                    self.MAX_RETRIES,
                )
                await asyncio.sleep(backoff)

        return AIResult(
            success=False,
            error=f"Stage '{name}' failed after {self.MAX_RETRIES} retries: {last_error}",
        )
