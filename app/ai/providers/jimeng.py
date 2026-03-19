"""
Jimeng T2I v4.0 Provider.

Wraps the vendor/jimeng text-to-image module into the ExternalAIProvider
interface using the same synchronous-in-submit pattern as QwenProvider:
all work happens in submit_job, poll_job returns the cached result.
"""

import base64
import logging
import uuid

from app.ai.base import ExternalAIProvider, JobState, JobStatus
from app.ai.providers import register_provider
from app.ai.providers.jimeng_utils import decode_image_result

logger = logging.getLogger(__name__)

# In-memory result store (for sync providers that complete during submit)
_results: dict[str, dict] = {}


class JimengProvider(ExternalAIProvider):

    @property
    def provider_name(self) -> str:
        return "jimeng"

    async def submit_job(self, params: dict) -> str:
        """
        Submit a text-to-image generation job to Jimeng and wait for the result.

        Expected params:
            - prompt: str          (required) English prompt for image generation
            - width: int           (default 1024)
            - height: int          (default 1024)
            - seed: int            (default -1, random)
            - scale: float         (default 0.5)

        Returns:
            Internal job ID (UUID).
        """
        from vendor.jimeng.t2i import submit_t2i_task, get_t2i_result

        prompt = params["prompt"]
        width = params.get("width", 1024)
        height = params.get("height", 1024)
        seed = params.get("seed", -1)
        scale = params.get("scale", 0.5)

        job_id = str(uuid.uuid4())

        try:
            # Step 1: submit task to Jimeng
            task_id = submit_t2i_task(
                prompt=prompt,
                width=width,
                height=height,
                seed=seed,
                scale=scale,
            )

            if task_id is None:
                _results[job_id] = {
                    "success": False,
                    "error": "Jimeng submit_t2i_task returned None (API rejected the request)",
                }
                return job_id

            # Step 2: poll until complete (vendor handles the loop)
            data = get_t2i_result(task_id)

            if data is None:
                _results[job_id] = {
                    "success": False,
                    "error": f"Jimeng get_t2i_result returned None for task_id={task_id}",
                }
                return job_id

            # Step 3: extract image bytes
            image_bytes = decode_image_result(data)

            _results[job_id] = {
                "success": True,
                "data": data,
                "image_bytes": image_bytes,
                "jimeng_task_id": task_id,
            }
            logger.info("Jimeng job %s completed (task_id=%s)", job_id, task_id)

        except Exception as e:
            logger.error("Jimeng job %s failed: %s", job_id, e)
            _results[job_id] = {"success": False, "error": str(e)}

        return job_id

    async def poll_job(self, external_job_id: str) -> JobStatus:
        """Return cached result (always completed for sync provider)."""
        result = _results.pop(external_job_id, None)

        if result is None:
            return JobStatus(state=JobState.FAILED, error="Job not found")

        if result["success"]:
            return JobStatus(
                state=JobState.COMPLETED,
                progress=1.0,
                result_data=result.get("image_bytes"),
                metadata={
                    "data": result["data"],
                    "jimeng_task_id": result.get("jimeng_task_id"),
                },
            )
        else:
            return JobStatus(
                state=JobState.FAILED,
                error=result["error"],
            )

    async def download_result(self, result_url: str) -> bytes:
        """Download image from URL or decode base64 data URI."""
        if result_url.startswith("data:"):
            # Handle base64 data URI
            _, _, b64_data = result_url.partition(",")
            return base64.b64decode(b64_data)
        return await super().download_result(result_url)


# Auto-register when module is imported
register_provider("jimeng", JimengProvider)
