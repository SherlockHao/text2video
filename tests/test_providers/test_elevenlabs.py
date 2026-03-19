"""
Tests for ElevenLabsProvider.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.ai.base import JobState


@pytest.mark.asyncio
async def test_elevenlabs_submit_and_poll():
    """submit_job calls ElevenLabs API, poll_job returns COMPLETED with audio data."""
    fake_audio = b"\xff\xfb\x90\x00" + b"\x00" * 200  # fake MP3 header bytes

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = fake_audio
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response), \
         patch("app.core.config.settings") as mock_settings:
        mock_settings.ELEVENLABS_API_KEY = "test-api-key"
        mock_settings.ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"

        from app.ai.providers.elevenlabs import ElevenLabsProvider

        provider = ElevenLabsProvider()
        job_id = await provider.submit_job({
            "text": "Hello, this is a test.",
            "voice_id": "voice-abc-123",
            "model_id": "eleven_multilingual_v2",
            "stability": 0.5,
            "similarity_boost": 0.75,
            "speed": 1.0,
        })

        assert job_id is not None

        status = await provider.poll_job(job_id)
        assert status.state == JobState.COMPLETED
        assert status.progress == 1.0
        assert status.result_data == fake_audio
        assert status.metadata["voice_id"] == "voice-abc-123"
        assert status.metadata["model_id"] == "eleven_multilingual_v2"
        assert status.metadata["text_length"] == len("Hello, this is a test.")


@pytest.mark.asyncio
async def test_elevenlabs_submit_failure():
    """submit_job handles HTTP 401 (unauthorized) response."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Unauthorized",
        request=MagicMock(),
        response=mock_response,
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response), \
         patch("app.core.config.settings") as mock_settings:
        mock_settings.ELEVENLABS_API_KEY = "bad-key"
        mock_settings.ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"

        from app.ai.providers.elevenlabs import ElevenLabsProvider

        provider = ElevenLabsProvider()
        job_id = await provider.submit_job({
            "text": "Test text",
            "voice_id": "voice-123",
        })

        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "401" in status.error


@pytest.mark.asyncio
async def test_elevenlabs_submit_timeout():
    """submit_job handles timeout exception."""
    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        side_effect=httpx.TimeoutException("Connection timed out"),
    ), \
         patch("app.core.config.settings") as mock_settings:
        mock_settings.ELEVENLABS_API_KEY = "test-key"
        mock_settings.ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"

        from app.ai.providers.elevenlabs import ElevenLabsProvider

        provider = ElevenLabsProvider()
        job_id = await provider.submit_job({
            "text": "Test text",
            "voice_id": "voice-123",
        })

        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "timed out" in status.error.lower()


@pytest.mark.asyncio
async def test_list_voices():
    """list_voices fetches and parses voice list from API."""
    fake_voices_response = {
        "voices": [
            {
                "voice_id": "v1",
                "name": "Alice",
                "labels": {"accent": "british"},
                "preview_url": "https://example.com/alice.mp3",
            },
            {
                "voice_id": "v2",
                "name": "Bob",
                "labels": {"accent": "american"},
                "preview_url": "https://example.com/bob.mp3",
            },
        ]
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = fake_voices_response
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response), \
         patch("app.core.config.settings") as mock_settings:
        mock_settings.ELEVENLABS_API_KEY = "test-key"
        mock_settings.ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"

        from app.ai.providers.elevenlabs import list_voices

        voices = await list_voices()

        assert len(voices) == 2
        assert voices[0]["voice_id"] == "v1"
        assert voices[0]["name"] == "Alice"
        assert voices[0]["labels"] == {"accent": "british"}
        assert voices[0]["preview_url"] == "https://example.com/alice.mp3"
        assert voices[1]["voice_id"] == "v2"
        assert voices[1]["name"] == "Bob"


@pytest.mark.asyncio
async def test_elevenlabs_provider_name():
    """Verify provider_name property returns 'elevenlabs'."""
    from app.ai.providers.elevenlabs import ElevenLabsProvider

    provider = ElevenLabsProvider()
    assert provider.provider_name == "elevenlabs"
