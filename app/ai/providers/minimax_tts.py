"""
MiniMax TTS Provider (speech-02-hd).

Uses MiniMax T2A v2 API for Chinese text-to-speech synthesis.
API docs: https://platform.minimax.io/docs/api-reference/speech-t2a-http
"""

import logging
import uuid

import httpx

from app.ai.base import ExternalAIProvider, JobState, JobStatus
from app.ai.providers import register_provider
from app.core.config import settings

logger = logging.getLogger(__name__)

# In-memory result cache (sync provider pattern)
_results: dict[str, dict] = {}

# Default Chinese voices
DEFAULT_VOICES = [
    {"voice_id": "male-qn-qingse", "name": "青涩青年-值得推荐"},
    {"voice_id": "female-shaonv", "name": "少女音-值得推荐"},
    {"voice_id": "male-qn-jingying", "name": "精英青年"},
    {"voice_id": "female-yujie", "name": "御姐音"},
    {"voice_id": "presenter_male", "name": "男性主持人"},
    {"voice_id": "presenter_female", "name": "女性主持人"},
    {"voice_id": "audiobook_male_1", "name": "男性有声书1"},
    {"voice_id": "audiobook_female_1", "name": "女性有声书1"},
]

# API config
_BASE_URL = "https://api.minimax.io/v1/t2a_v2"
_DEFAULT_MODEL = "speech-02-hd"


class MiniMaxTTSProvider(ExternalAIProvider):
    """MiniMax TTS provider using T2A v2 API."""

    @property
    def provider_name(self) -> str:
        return "minimax_tts"

    async def submit_job(self, params: dict) -> str:
        """
        Call MiniMax TTS API and cache the audio result.

        Expected params:
            - text: str (required, up to 10000 chars)
            - voice_id: str (default "male-qn-qingse")
            - model: str (default "speech-02-hd")
            - speed: float (default 1.0)
            - pitch: int (default 0, range -12 to 12)
            - emotion: str (default "neutral")
            - output_format: str (default "mp3")
        """
        text = params.get("text", "")
        voice_id = params.get("voice_id", "male-qn-qingse")
        model = params.get("model", _DEFAULT_MODEL)
        speed = params.get("speed", 1.0)
        pitch = params.get("pitch", 0)
        emotion = params.get("emotion", "neutral")
        output_format = params.get("output_format", "mp3")

        api_key = settings.MINIMAX_API_KEY
        if not api_key:
            job_id = str(uuid.uuid4())
            _results[job_id] = {"success": False, "error": "MINIMAX_API_KEY not configured"}
            return job_id

        job_id = str(uuid.uuid4())

        request_body = {
            "model": model,
            "text": text,
            "voice_setting": {
                "voice_id": voice_id,
                "speed": speed,
                "pitch": pitch,
                "emotion": emotion,
            },
            "audio_setting": {
                "format": output_format,
                "sample_rate": 32000,
            },
            "language_boost": "Chinese",
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    _BASE_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                )
                response.raise_for_status()
                data = response.json()

            # Check API response status
            base_resp = data.get("base_resp", {})
            status_code = base_resp.get("status_code", -1)
            if status_code != 0:
                error_msg = base_resp.get("status_msg", f"API error code: {status_code}")
                logger.error("MiniMax TTS job %s API error: %s", job_id, error_msg)
                _results[job_id] = {"success": False, "error": error_msg}
                return job_id

            # Extract audio data
            audio_hex = data.get("data", {}).get("audio", "")
            if not audio_hex:
                _results[job_id] = {"success": False, "error": "No audio data in response"}
                return job_id

            audio_bytes = bytes.fromhex(audio_hex)
            logger.info(
                "MiniMax TTS job %s completed: %d bytes audio, voice=%s",
                job_id, len(audio_bytes), voice_id,
            )

            _results[job_id] = {
                "success": True,
                "audio_bytes": audio_bytes,
                "metadata": {
                    "voice_id": voice_id,
                    "model": model,
                    "text_length": len(text),
                    "audio_size": len(audio_bytes),
                    "trace_id": data.get("trace_id"),
                },
            }

        except httpx.TimeoutException:
            logger.error("MiniMax TTS job %s timed out", job_id)
            _results[job_id] = {"success": False, "error": "Request timed out"}
        except httpx.HTTPStatusError as e:
            logger.error("MiniMax TTS job %s HTTP error: %s", job_id, e.response.status_code)
            _results[job_id] = {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except Exception as e:
            logger.error("MiniMax TTS job %s failed: %s", job_id, e)
            _results[job_id] = {"success": False, "error": str(e)}

        return job_id

    async def poll_job(self, external_job_id: str) -> JobStatus:
        """Return cached result (sync provider)."""
        result = _results.pop(external_job_id, None)
        if result is None:
            return JobStatus(state=JobState.FAILED, error="Job not found")

        if result["success"]:
            return JobStatus(
                state=JobState.COMPLETED,
                progress=1.0,
                result_data=result["audio_bytes"],
                metadata=result["metadata"],
            )
        else:
            return JobStatus(state=JobState.FAILED, error=result["error"])


def get_available_voices() -> list[dict]:
    """Return list of available MiniMax Chinese voices."""
    return DEFAULT_VOICES


# Auto-register
register_provider("minimax_tts", MiniMaxTTSProvider)
