"""
Seedance2 (Jimeng I2V 3.0 1080P) Provider — High Quality Video Generation.

Wraps vendor/jimeng/i2v.py into the ExternalAIProvider interface using the
same synchronous-in-submit pattern as JimengProvider: all work happens in
submit_job, poll_job returns the cached result.
"""

import base64
import logging
import uuid

import requests

from app.ai.base import ExternalAIProvider, JobState, JobStatus
from app.ai.providers import register_provider

logger = logging.getLogger(__name__)

# In-memory result store (for sync providers that complete during submit)
_results: dict[str, dict] = {}


def decode_video_result(data: dict) -> bytes | None:
    """Extract video bytes from a Jimeng I2V API response dict.

    Checks ``binary_data_base64`` first (preferred — no extra download).
    Falls back to ``video_url`` if base64 is absent.

    Args:
        data: The ``data`` dict returned by ``get_i2v_result``.

    Returns:
        Raw video bytes, or *None* if no video data could be extracted.
    """
    # Try base64 first
    for b64 in data.get("binary_data_base64", []):
        if b64:
            try:
                return base64.b64decode(b64)
            except Exception:
                logger.warning("Failed to decode base64 video data")
                continue

    # Fallback: download from URL
    video_url = data.get("video_url", "")
    if video_url:
        try:
            resp = requests.get(video_url, timeout=120)
            resp.raise_for_status()
            return resp.content
        except Exception:
            logger.warning("Failed to download video from %s", video_url)

    return None


class Seedance2Provider(ExternalAIProvider):
    """Seedance2 high-quality video generation via Jimeng I2V 3.0 1080P."""

    @property
    def provider_name(self) -> str:
        return "seedance2"

    async def submit_job(self, params: dict) -> str:
        """
        Submit an image-to-video generation job and wait for the result.

        Expected params:
            - image_path: str   (required) local path to the source image (first frame)
            - prompt: str       (optional) motion/action prompt
            - seed: int         (default -1, random)
            - frames: int       (default 121, ~5s @24fps)

        Returns:
            Internal job ID (UUID).
        """
        from vendor.jimeng.i2v import submit_i2v_task, get_i2v_result

        image_path = params["image_path"]
        prompt = params.get("prompt", "")
        seed = params.get("seed", -1)
        frames = params.get("frames", 121)

        job_id = str(uuid.uuid4())

        try:
            # Step 1: submit task to Jimeng I2V
            task_id = submit_i2v_task(
                image_path=image_path,
                prompt=prompt,
                seed=seed,
                frames=frames,
            )

            if task_id is None:
                _results[job_id] = {
                    "success": False,
                    "error": "Seedance2 submit_i2v_task returned None (API rejected the request)",
                }
                return job_id

            # Step 2: poll until complete (vendor handles the loop)
            data = get_i2v_result(task_id)

            if data is None:
                _results[job_id] = {
                    "success": False,
                    "error": f"Seedance2 get_i2v_result returned None for task_id={task_id}",
                }
                return job_id

            # Step 3: extract video bytes
            video_bytes = decode_video_result(data)

            _results[job_id] = {
                "success": True,
                "data": data,
                "video_bytes": video_bytes,
                "jimeng_task_id": task_id,
            }
            logger.info("Seedance2 job %s completed (task_id=%s)", job_id, task_id)

        except Exception as e:
            logger.error("Seedance2 job %s failed: %s", job_id, e)
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
                result_data=result.get("video_bytes"),
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


# Auto-register when module is imported
register_provider("seedance2", Seedance2Provider)
