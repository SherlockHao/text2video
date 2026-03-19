"""
Tests for KlingProvider (stub — delegates to Seedance2).
"""

import base64

import pytest
from unittest.mock import patch, AsyncMock

from app.ai.base import JobState


@pytest.mark.asyncio
async def test_kling_provider_name():
    """provider_name returns 'kling'."""
    from app.ai.providers.kling import KlingProvider

    provider = KlingProvider()
    assert provider.provider_name == "kling"


@pytest.mark.asyncio
async def test_kling_fallback_to_seedance2():
    """Kling delegates submit_job and poll_job to Seedance2 as fallback."""
    fake_video = b"\x00\x00\x00\x1cftypisom" + b"\x00" * 50
    fake_b64 = base64.b64encode(fake_video).decode()
    fake_data = {
        "binary_data_base64": [fake_b64],
        "video_url": "",
    }

    with patch("vendor.jimeng.i2v.submit_i2v_task", return_value="i2v-task-fallback"), \
         patch("vendor.jimeng.i2v.get_i2v_result", return_value=fake_data):
        from app.ai.providers.kling import KlingProvider

        provider = KlingProvider()
        job_id = await provider.submit_job({
            "image_path": "/tmp/test_frame.png",
            "prompt": "gentle motion",
        })

        assert job_id is not None
        # Verify fallback was set
        assert hasattr(provider, "_fallback")
        assert provider._fallback.provider_name == "seedance2"

        status = await provider.poll_job(job_id)
        assert status.state == JobState.COMPLETED
        assert status.result_data == fake_video


@pytest.mark.asyncio
async def test_kling_poll_without_submit():
    """poll_job without prior submit returns FAILED (no fallback set)."""
    from app.ai.providers.kling import KlingProvider

    provider = KlingProvider()
    status = await provider.poll_job("some-job-id")
    assert status.state == JobState.FAILED
    assert "no fallback" in status.error.lower()


@pytest.mark.asyncio
async def test_kling_fallback_submit_failure():
    """Kling correctly surfaces Seedance2 failures."""
    with patch("vendor.jimeng.i2v.submit_i2v_task", return_value=None):
        from app.ai.providers.kling import KlingProvider

        provider = KlingProvider()
        job_id = await provider.submit_job({
            "image_path": "/tmp/frame.png",
        })

        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "None" in status.error


@pytest.mark.asyncio
async def test_kling_registered():
    """Kling provider is registered in the routing table."""
    from app.ai.providers import _PROVIDER_CLASSES
    import app.ai.providers.kling  # noqa: F401

    assert "kling" in _PROVIDER_CLASSES


@pytest.mark.asyncio
async def test_seedance2_registered():
    """Seedance2 provider is registered in the routing table."""
    from app.ai.providers import _PROVIDER_CLASSES
    import app.ai.providers.seedance2  # noqa: F401

    assert "seedance2" in _PROVIDER_CLASSES
