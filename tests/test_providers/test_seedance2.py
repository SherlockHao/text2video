"""
Tests for Seedance2Provider (Jimeng I2V video generation).
"""

import base64

import pytest
from unittest.mock import patch, MagicMock

from app.ai.base import JobState


# ---------------------------------------------------------------------------
# Seedance2Provider tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seedance2_provider_name():
    """provider_name returns 'seedance2'."""
    from app.ai.providers.seedance2 import Seedance2Provider

    provider = Seedance2Provider()
    assert provider.provider_name == "seedance2"


@pytest.mark.asyncio
async def test_seedance2_submit_and_poll():
    """submit_job calls vendor i2v functions, poll_job returns COMPLETED with video data."""
    fake_video = b"\x00\x00\x00\x1cftypisom" + b"\x00" * 100  # fake MP4 header
    fake_b64 = base64.b64encode(fake_video).decode()
    fake_data = {
        "binary_data_base64": [fake_b64],
        "video_url": "",
    }

    with patch("vendor.jimeng.i2v.submit_i2v_task", return_value="i2v-task-123") as mock_submit, \
         patch("vendor.jimeng.i2v.get_i2v_result", return_value=fake_data) as mock_result:
        from app.ai.providers.seedance2 import Seedance2Provider

        provider = Seedance2Provider()
        job_id = await provider.submit_job({
            "image_path": "/tmp/test_frame.png",
            "prompt": "camera slowly pans right",
            "seed": 42,
            "frames": 121,
        })

        assert job_id is not None

        # Verify vendor calls
        mock_submit.assert_called_once_with(
            image_path="/tmp/test_frame.png",
            prompt="camera slowly pans right",
            seed=42,
            frames=121,
        )
        mock_result.assert_called_once_with("i2v-task-123")

        status = await provider.poll_job(job_id)
        assert status.state == JobState.COMPLETED
        assert status.progress == 1.0
        assert status.result_data == fake_video
        assert status.metadata["jimeng_task_id"] == "i2v-task-123"
        assert status.metadata["data"]["binary_data_base64"] == [fake_b64]


@pytest.mark.asyncio
async def test_seedance2_submit_with_video_url():
    """submit_job falls back to video_url when no base64 data."""
    fake_video = b"downloaded video content"
    fake_data = {
        "binary_data_base64": [],
        "video_url": "https://example.com/video.mp4",
    }

    mock_resp = MagicMock()
    mock_resp.content = fake_video
    mock_resp.raise_for_status = MagicMock()

    with patch("vendor.jimeng.i2v.submit_i2v_task", return_value="i2v-task-456"), \
         patch("vendor.jimeng.i2v.get_i2v_result", return_value=fake_data), \
         patch("requests.get", return_value=mock_resp):
        from app.ai.providers.seedance2 import Seedance2Provider

        provider = Seedance2Provider()
        job_id = await provider.submit_job({
            "image_path": "/tmp/frame.png",
        })

        status = await provider.poll_job(job_id)
        assert status.state == JobState.COMPLETED
        assert status.result_data == fake_video


@pytest.mark.asyncio
async def test_seedance2_submit_failure():
    """submit_job handles submit_i2v_task returning None."""
    with patch("vendor.jimeng.i2v.submit_i2v_task", return_value=None):
        from app.ai.providers.seedance2 import Seedance2Provider

        provider = Seedance2Provider()
        job_id = await provider.submit_job({
            "image_path": "/tmp/frame.png",
        })

        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "None" in status.error


@pytest.mark.asyncio
async def test_seedance2_poll_result_none():
    """submit_job handles get_i2v_result returning None (timeout)."""
    with patch("vendor.jimeng.i2v.submit_i2v_task", return_value="task-789"), \
         patch("vendor.jimeng.i2v.get_i2v_result", return_value=None):
        from app.ai.providers.seedance2 import Seedance2Provider

        provider = Seedance2Provider()
        job_id = await provider.submit_job({"image_path": "/tmp/frame.png"})

        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "task-789" in status.error


@pytest.mark.asyncio
async def test_seedance2_submit_exception():
    """submit_job handles unexpected exceptions gracefully."""
    with patch("vendor.jimeng.i2v.submit_i2v_task", side_effect=Exception("network error")):
        from app.ai.providers.seedance2 import Seedance2Provider

        provider = Seedance2Provider()
        job_id = await provider.submit_job({"image_path": "/tmp/frame.png"})

        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "network error" in status.error


@pytest.mark.asyncio
async def test_seedance2_poll_missing_job():
    """poll_job returns FAILED for an unknown job_id."""
    from app.ai.providers.seedance2 import Seedance2Provider

    provider = Seedance2Provider()
    status = await provider.poll_job("nonexistent-id")
    assert status.state == JobState.FAILED
    assert "not found" in status.error.lower()


@pytest.mark.asyncio
async def test_seedance2_poll_consumes_result():
    """poll_job removes the cached result after first call."""
    fake_b64 = base64.b64encode(b"vid").decode()
    fake_data = {"binary_data_base64": [fake_b64], "video_url": ""}

    with patch("vendor.jimeng.i2v.submit_i2v_task", return_value="t1"), \
         patch("vendor.jimeng.i2v.get_i2v_result", return_value=fake_data):
        from app.ai.providers.seedance2 import Seedance2Provider

        provider = Seedance2Provider()
        job_id = await provider.submit_job({"image_path": "/tmp/frame.png"})

        status1 = await provider.poll_job(job_id)
        assert status1.state == JobState.COMPLETED

        status2 = await provider.poll_job(job_id)
        assert status2.state == JobState.FAILED


# ---------------------------------------------------------------------------
# decode_video_result tests
# ---------------------------------------------------------------------------

def test_decode_video_result_base64():
    """Extracts video bytes from binary_data_base64."""
    from app.ai.providers.seedance2 import decode_video_result

    raw = b"video bytes content"
    b64 = base64.b64encode(raw).decode()
    data = {"binary_data_base64": [b64], "video_url": ""}

    result = decode_video_result(data)
    assert result == raw


def test_decode_video_result_url():
    """Falls back to video_url when no base64 data."""
    from app.ai.providers.seedance2 import decode_video_result

    fake_content = b"downloaded video"
    mock_resp = MagicMock()
    mock_resp.content = fake_content
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp) as mock_get:
        data = {"binary_data_base64": [], "video_url": "https://example.com/video.mp4"}
        result = decode_video_result(data)

        assert result == fake_content
        mock_get.assert_called_once_with("https://example.com/video.mp4", timeout=120)


def test_decode_video_result_empty():
    """Returns None when no video data is available."""
    from app.ai.providers.seedance2 import decode_video_result

    data = {"binary_data_base64": [], "video_url": ""}
    assert decode_video_result(data) is None


def test_decode_video_result_no_keys():
    """Returns None when response dict has no video keys."""
    from app.ai.providers.seedance2 import decode_video_result

    assert decode_video_result({}) is None
