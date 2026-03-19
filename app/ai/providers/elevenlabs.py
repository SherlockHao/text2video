"""
ElevenLabs TTS Provider.

Wraps the ElevenLabs text-to-speech API into the ExternalAIProvider
interface using the same synchronous-in-submit pattern as QwenProvider:
all work happens in submit_job, poll_job returns the cached result.
"""

import logging
import uuid

import httpx

from app.ai.base import ExternalAIProvider, JobState, JobStatus
from app.ai.providers import register_provider

logger = logging.getLogger(__name__)

# In-memory result store (for sync providers that complete during submit)
_results: dict[str, dict] = {}


class ElevenLabsProvider(ExternalAIProvider):

    @property
    def provider_name(self) -> str:
        return "elevenlabs"

    async def submit_job(self, params: dict) -> str:
        """
        Call ElevenLabs TTS API and return result immediately.

        Expected params:
            - text: str              (required) Text to synthesize
            - voice_id: str          (required) ElevenLabs voice ID
            - model_id: str          (default "eleven_multilingual_v2")
            - stability: float       (default 0.5)
            - similarity_boost: float (default 0.75)
            - speed: float           (default 1.0)
        """
        from app.core.config import settings

        text = params["text"]
        voice_id = params["voice_id"]
        model_id = params.get("model_id", "eleven_multilingual_v2")
        stability = params.get("stability", 0.5)
        similarity_boost = params.get("similarity_boost", 0.75)
        speed = params.get("speed", 1.0)

        job_id = str(uuid.uuid4())

        try:
            base_url = settings.ELEVENLABS_BASE_URL.rstrip("/")
            url = f"{base_url}/v1/text-to-speech/{voice_id}"

            headers = {
                "xi-api-key": settings.ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }

            payload = {
                "text": text,
                "model_id": model_id,
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": similarity_boost,
                    "speed": speed,
                },
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                audio_bytes = response.content

            _results[job_id] = {
                "success": True,
                "audio_bytes": audio_bytes,
                "voice_id": voice_id,
                "model_id": model_id,
                "text_length": len(text),
            }
            logger.info(
                "ElevenLabs job %s completed (voice=%s, %d bytes audio)",
                job_id, voice_id, len(audio_bytes),
            )

        except httpx.TimeoutException as e:
            logger.error("ElevenLabs job %s timed out: %s", job_id, e)
            _results[job_id] = {"success": False, "error": f"Request timed out: {e}"}

        except httpx.HTTPStatusError as e:
            logger.error(
                "ElevenLabs job %s HTTP error %d: %s",
                job_id, e.response.status_code, e,
            )
            _results[job_id] = {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e}",
            }

        except Exception as e:
            logger.error("ElevenLabs job %s failed: %s", job_id, e)
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
                result_data=result.get("audio_bytes"),
                metadata={
                    "voice_id": result.get("voice_id"),
                    "model_id": result.get("model_id"),
                    "text_length": result.get("text_length"),
                },
            )
        else:
            return JobStatus(
                state=JobState.FAILED,
                error=result["error"],
            )


async def list_voices() -> list[dict]:
    """
    Fetch available voices from ElevenLabs API.

    GET https://api.elevenlabs.io/v1/voices

    Returns:
        List of dicts with keys: voice_id, name, labels, preview_url
    """
    from app.core.config import settings

    base_url = settings.ELEVENLABS_BASE_URL.rstrip("/")
    url = f"{base_url}/v1/voices"

    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    voices = []
    for voice in data.get("voices", []):
        voices.append({
            "voice_id": voice.get("voice_id"),
            "name": voice.get("name"),
            "labels": voice.get("labels", {}),
            "preview_url": voice.get("preview_url"),
        })

    return voices


# Auto-register when module is imported
register_provider("elevenlabs", ElevenLabsProvider)
