"""
Qwen 3.5-Plus LLM Provider.
Used for script breakdown (storyboard generation).
"""

import json
import logging
import uuid
from typing import Optional

from app.ai.base import ExternalAIProvider, JobStatus, JobState, AIResult
from app.ai.providers import register_provider

logger = logging.getLogger(__name__)

# In-memory result store (for sync providers that complete during submit)
_results: dict[str, dict] = {}


class QwenProvider(ExternalAIProvider):

    @property
    def provider_name(self) -> str:
        return "qwen"

    async def submit_job(self, params: dict) -> str:
        """
        Call Qwen LLM and return result immediately.

        Expected params:
            - system_prompt: str
            - user_prompt: str
            - temperature: float (default 0.7)
            - max_tokens: int (default 8192)
            - response_format: str "json" or "text" (default "json")
        """
        from vendor.qwen.client import chat_with_system, chat_json

        system_prompt = params["system_prompt"]
        user_prompt = params["user_prompt"]
        temperature = params.get("temperature", 0.7)
        max_tokens = params.get("max_tokens", 8192)
        response_format = params.get("response_format", "json")  # "json" or "text"

        job_id = str(uuid.uuid4())

        try:
            if response_format == "json":
                from vendor.qwen.client import _extract_json
                import json as _json

                max_attempts = 3
                last_error = None

                for attempt in range(1, max_attempts + 1):
                    raw = chat_with_system(system_prompt, user_prompt, temperature, max_tokens)
                    print(f"[QWEN] job={job_id} attempt={attempt} raw_len={len(raw) if raw else 0}", flush=True)

                    try:
                        json_str = _extract_json(raw)
                        result = _json.loads(json_str)
                        _results[job_id] = {"success": True, "data": result}
                        last_error = None
                        break
                    except (_json.JSONDecodeError, ValueError) as parse_err:
                        last_error = str(parse_err)
                        print(f"[QWEN] job={job_id} attempt={attempt} JSON parse failed: {last_error}", flush=True)
                        if attempt < max_attempts:
                            print(f"[QWEN] Retrying...", flush=True)

                if last_error:
                    _results[job_id] = {"success": False, "error": f"JSON parse failed after {max_attempts} attempts: {last_error}"}
            else:
                result = chat_with_system(system_prompt, user_prompt, temperature, max_tokens)
                _results[job_id] = {"success": True, "data": result}

            if job_id in _results and _results[job_id]["success"]:
                logger.info("Qwen job %s completed successfully", job_id)
        except Exception as e:
            logger.error("Qwen job %s failed: %s", job_id, e)
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
                metadata={"data": result["data"]},
            )
        else:
            return JobStatus(
                state=JobState.FAILED,
                error=result["error"],
            )


# Auto-register when module is imported
register_provider("qwen", QwenProvider)
