"""
Tests for QwenProvider and narration_manga prompt template.
"""

import json
import pytest
from unittest.mock import patch

from app.ai.base import JobState


# ---------------------------------------------------------------------------
# QwenProvider tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_qwen_submit_and_poll():
    """submit_job calls chat_with_system, poll_job returns COMPLETED with data."""
    fake_json = {"title": "Test", "storyboards": [{"shot_number": 1}]}
    fake_raw = json.dumps(fake_json)

    with patch("vendor.qwen.client.chat_with_system", return_value=fake_raw):
        from app.ai.providers.qwen import QwenProvider, _results

        provider = QwenProvider()
        job_id = await provider.submit_job({
            "system_prompt": "You are a storyboard artist.",
            "user_prompt": "Break down this text.",
            "response_format": "json",
        })

        assert job_id is not None
        status = await provider.poll_job(job_id)
        assert status.state == JobState.COMPLETED
        assert status.metadata["data"]["title"] == "Test"


@pytest.mark.asyncio
async def test_qwen_submit_text_format():
    """submit_job with text format returns raw text."""
    with patch("vendor.qwen.client.chat_with_system", return_value="Hello world"):
        from app.ai.providers.qwen import QwenProvider

        provider = QwenProvider()
        job_id = await provider.submit_job({
            "system_prompt": "sys",
            "user_prompt": "user",
            "response_format": "text",
        })
        status = await provider.poll_job(job_id)
        assert status.state == JobState.COMPLETED
        assert status.metadata["data"] == "Hello world"


@pytest.mark.asyncio
async def test_qwen_submit_failure():
    """submit_job handles exceptions gracefully."""
    with patch("vendor.qwen.client.chat_with_system", side_effect=Exception("API error")):
        from app.ai.providers.qwen import QwenProvider

        provider = QwenProvider()
        job_id = await provider.submit_job({
            "system_prompt": "sys",
            "user_prompt": "user",
            "response_format": "text",
        })
        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "API error" in status.error


@pytest.mark.asyncio
async def test_qwen_poll_missing_job():
    """poll_job returns FAILED for unknown job_id."""
    from app.ai.providers.qwen import QwenProvider

    provider = QwenProvider()
    status = await provider.poll_job("nonexistent-id")
    assert status.state == JobState.FAILED


@pytest.mark.asyncio
async def test_qwen_poll_consumes_result():
    """poll_job removes the result after first call."""
    fake_json = {"ok": True}
    with patch("vendor.qwen.client.chat_with_system", return_value=json.dumps(fake_json)):
        from app.ai.providers.qwen import QwenProvider

        provider = QwenProvider()
        job_id = await provider.submit_job({
            "system_prompt": "s",
            "user_prompt": "u",
            "response_format": "json",
        })
        status1 = await provider.poll_job(job_id)
        assert status1.state == JobState.COMPLETED

        status2 = await provider.poll_job(job_id)
        assert status2.state == JobState.FAILED


@pytest.mark.asyncio
async def test_qwen_json_retry():
    """submit_job retries on JSON parse failure."""
    call_count = 0

    def mock_chat(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "This is not JSON at all"
        return '{"title": "retry success"}'

    with patch("vendor.qwen.client.chat_with_system", side_effect=mock_chat):
        from app.ai.providers.qwen import QwenProvider

        provider = QwenProvider()
        job_id = await provider.submit_job({
            "system_prompt": "s",
            "user_prompt": "u",
            "response_format": "json",
        })
        status = await provider.poll_job(job_id)
        assert status.state == JobState.COMPLETED
        assert status.metadata["data"]["title"] == "retry success"
        assert call_count == 2


# ---------------------------------------------------------------------------
# Prompt template tests
# ---------------------------------------------------------------------------

def test_prompt_template_basic():
    """build_storyboard_prompt returns system and user prompts."""
    from app.ai.prompts.narration_manga import build_storyboard_prompt

    result = build_storyboard_prompt(
        source_text="A hero fights.",
        content_type="narration",
        visual_style="manga",
        duration_target=60,
        quality_tier="normal",
        aspect_ratio="16:9",
    )
    assert "system_prompt" in result
    assert "user_prompt" in result
    assert "A hero fights" in result["user_prompt"]
    assert "manga" in result["system_prompt"].lower() or "漫画" in result["system_prompt"]


def test_prompt_template_high_quality():
    """High quality tier produces more shots per minute."""
    from app.ai.prompts.narration_manga import build_storyboard_prompt

    normal = build_storyboard_prompt("text", "narration", "manga", 60, "normal", "16:9")
    high = build_storyboard_prompt("text", "narration", "manga", 60, "high", "16:9")

    # high quality should mention more shots
    assert "15" in high["system_prompt"] or "20" in high["system_prompt"]
    assert "8" in normal["system_prompt"] or "12" in normal["system_prompt"]


def test_prompt_registry():
    """get_template returns the correct function."""
    import app.ai.prompts.narration_manga  # noqa: F401
    from app.ai.prompts.base import get_template

    fn = get_template("narration", "manga")
    assert callable(fn)


def test_prompt_registry_missing():
    """get_template raises for unregistered template."""
    from app.ai.prompts.base import get_template

    with pytest.raises(ValueError, match="No prompt template"):
        get_template("nonexistent", "style")
