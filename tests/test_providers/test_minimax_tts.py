"""Tests for MiniMaxTTSProvider."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.ai.base import JobState


@pytest.mark.asyncio
async def test_minimax_submit_and_poll():
    """submit_job calls MiniMax API, poll returns COMPLETED with audio bytes."""
    fake_audio_hex = b"hello audio".hex()
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "data": {"audio": fake_audio_hex},
        "base_resp": {"status_code": 0, "status_msg": ""},
        "trace_id": "test-trace",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=fake_response)

    with patch("httpx.AsyncClient", return_value=mock_client), \
         patch("app.core.config.settings") as mock_settings:
        mock_settings.MINIMAX_API_KEY = "test-key"

        from app.ai.providers.minimax_tts import MiniMaxTTSProvider
        provider = MiniMaxTTSProvider()

        job_id = await provider.submit_job({
            "text": "测试文本",
            "voice_id": "male-qn-qingse",
        })
        assert job_id is not None

        status = await provider.poll_job(job_id)
        assert status.state == JobState.COMPLETED
        assert status.result_data == b"hello audio"
        assert status.metadata["voice_id"] == "male-qn-qingse"


@pytest.mark.asyncio
async def test_minimax_no_api_key():
    """submit_job fails gracefully when no API key configured."""
    with patch("app.ai.providers.minimax_tts.settings") as mock_settings:
        mock_settings.MINIMAX_API_KEY = ""

        from app.ai.providers.minimax_tts import MiniMaxTTSProvider
        provider = MiniMaxTTSProvider()

        job_id = await provider.submit_job({"text": "test"})
        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "not configured" in status.error


@pytest.mark.asyncio
async def test_minimax_api_error():
    """submit_job handles API error response."""
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "data": {},
        "base_resp": {"status_code": 1000, "status_msg": "Invalid voice"},
        "trace_id": "err-trace",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=fake_response)

    with patch("httpx.AsyncClient", return_value=mock_client), \
         patch("app.core.config.settings") as mock_settings:
        mock_settings.MINIMAX_API_KEY = "test-key"

        from app.ai.providers.minimax_tts import MiniMaxTTSProvider
        provider = MiniMaxTTSProvider()

        job_id = await provider.submit_job({"text": "test"})
        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "Invalid voice" in status.error


@pytest.mark.asyncio
async def test_minimax_poll_missing_job():
    """poll_job returns FAILED for unknown job_id."""
    from app.ai.providers.minimax_tts import MiniMaxTTSProvider
    provider = MiniMaxTTSProvider()
    status = await provider.poll_job("nonexistent")
    assert status.state == JobState.FAILED


def test_minimax_provider_name():
    from app.ai.providers.minimax_tts import MiniMaxTTSProvider
    assert MiniMaxTTSProvider().provider_name == "minimax_tts"


def test_get_available_voices():
    from app.ai.providers.minimax_tts import get_available_voices
    voices = get_available_voices()
    assert len(voices) > 0
    assert all("voice_id" in v and "name" in v for v in voices)
