"""
Tests for JimengProvider and jimeng_utils helpers.
"""

import base64
import json

import pytest
from unittest.mock import patch, MagicMock

from app.ai.base import JobState


# ---------------------------------------------------------------------------
# JimengProvider tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jimeng_submit_and_poll():
    """submit_job calls vendor functions, poll_job returns COMPLETED with image data."""
    fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG header
    fake_b64 = base64.b64encode(fake_image).decode()
    fake_data = {
        "binary_data_base64": [fake_b64],
        "image_urls": [],
    }

    with patch("vendor.jimeng.t2i.submit_t2i_task", return_value="jimeng-task-123"), \
         patch("vendor.jimeng.t2i.get_t2i_result", return_value=fake_data):
        from app.ai.providers.jimeng import JimengProvider

        provider = JimengProvider()
        job_id = await provider.submit_job({
            "prompt": "a beautiful sunset over mountains",
            "width": 1280,
            "height": 720,
        })

        assert job_id is not None

        status = await provider.poll_job(job_id)
        assert status.state == JobState.COMPLETED
        assert status.progress == 1.0
        assert status.result_data == fake_image
        assert status.metadata["jimeng_task_id"] == "jimeng-task-123"
        assert status.metadata["data"]["binary_data_base64"] == [fake_b64]


@pytest.mark.asyncio
async def test_jimeng_submit_failure():
    """submit_job handles submit_t2i_task returning None."""
    with patch("vendor.jimeng.t2i.submit_t2i_task", return_value=None):
        from app.ai.providers.jimeng import JimengProvider

        provider = JimengProvider()
        job_id = await provider.submit_job({
            "prompt": "test prompt",
        })

        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "None" in status.error


@pytest.mark.asyncio
async def test_jimeng_submit_poll_result_none():
    """submit_job handles get_t2i_result returning None (timeout)."""
    with patch("vendor.jimeng.t2i.submit_t2i_task", return_value="task-456"), \
         patch("vendor.jimeng.t2i.get_t2i_result", return_value=None):
        from app.ai.providers.jimeng import JimengProvider

        provider = JimengProvider()
        job_id = await provider.submit_job({"prompt": "test"})

        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "task-456" in status.error


@pytest.mark.asyncio
async def test_jimeng_submit_exception():
    """submit_job handles unexpected exceptions gracefully."""
    with patch("vendor.jimeng.t2i.submit_t2i_task", side_effect=Exception("network error")):
        from app.ai.providers.jimeng import JimengProvider

        provider = JimengProvider()
        job_id = await provider.submit_job({"prompt": "test"})

        status = await provider.poll_job(job_id)
        assert status.state == JobState.FAILED
        assert "network error" in status.error


@pytest.mark.asyncio
async def test_jimeng_poll_missing_job():
    """poll_job returns FAILED for an unknown job_id."""
    from app.ai.providers.jimeng import JimengProvider

    provider = JimengProvider()
    status = await provider.poll_job("nonexistent-id")
    assert status.state == JobState.FAILED
    assert "not found" in status.error.lower()


@pytest.mark.asyncio
async def test_jimeng_poll_consumes_result():
    """poll_job removes the cached result after first call."""
    fake_b64 = base64.b64encode(b"img").decode()
    fake_data = {"binary_data_base64": [fake_b64], "image_urls": []}

    with patch("vendor.jimeng.t2i.submit_t2i_task", return_value="t1"), \
         patch("vendor.jimeng.t2i.get_t2i_result", return_value=fake_data):
        from app.ai.providers.jimeng import JimengProvider

        provider = JimengProvider()
        job_id = await provider.submit_job({"prompt": "test"})

        status1 = await provider.poll_job(job_id)
        assert status1.state == JobState.COMPLETED

        status2 = await provider.poll_job(job_id)
        assert status2.state == JobState.FAILED


# ---------------------------------------------------------------------------
# jimeng_utils tests
# ---------------------------------------------------------------------------

def test_calculate_dimensions_16_9():
    from app.ai.providers.jimeng_utils import calculate_dimensions

    assert calculate_dimensions("16:9") == (1280, 720)


def test_calculate_dimensions_9_16():
    from app.ai.providers.jimeng_utils import calculate_dimensions

    assert calculate_dimensions("9:16") == (720, 1280)


def test_calculate_dimensions_1_1():
    from app.ai.providers.jimeng_utils import calculate_dimensions

    assert calculate_dimensions("1:1") == (1024, 1024)


def test_calculate_dimensions_4_3():
    from app.ai.providers.jimeng_utils import calculate_dimensions

    assert calculate_dimensions("4:3") == (1152, 864)


def test_calculate_dimensions_3_4():
    from app.ai.providers.jimeng_utils import calculate_dimensions

    assert calculate_dimensions("3:4") == (864, 1152)


def test_calculate_dimensions_unknown():
    from app.ai.providers.jimeng_utils import calculate_dimensions

    assert calculate_dimensions("21:9") == (1024, 1024)


def test_decode_image_result_base64():
    """Extracts image bytes from binary_data_base64."""
    from app.ai.providers.jimeng_utils import decode_image_result

    raw = b"hello image bytes"
    b64 = base64.b64encode(raw).decode()
    data = {"binary_data_base64": [b64], "image_urls": []}

    result = decode_image_result(data)
    assert result == raw


def test_decode_image_result_base64_skips_empty():
    """Skips empty base64 entries and falls through."""
    from app.ai.providers.jimeng_utils import decode_image_result

    raw = b"actual data"
    b64 = base64.b64encode(raw).decode()
    data = {"binary_data_base64": ["", b64], "image_urls": []}

    result = decode_image_result(data)
    assert result == raw


def test_decode_image_result_url():
    """Falls back to image_urls when no base64 data."""
    from app.ai.providers.jimeng_utils import decode_image_result

    fake_content = b"downloaded image"
    mock_resp = MagicMock()
    mock_resp.content = fake_content
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp) as mock_get:
        data = {"binary_data_base64": [], "image_urls": ["https://example.com/img.png"]}
        result = decode_image_result(data)

        assert result == fake_content
        mock_get.assert_called_once_with("https://example.com/img.png", timeout=30)


def test_decode_image_result_empty():
    """Returns None when no image data is available."""
    from app.ai.providers.jimeng_utils import decode_image_result

    data = {"binary_data_base64": [], "image_urls": []}
    assert decode_image_result(data) is None


def test_decode_image_result_no_keys():
    """Returns None when response dict has no image keys."""
    from app.ai.providers.jimeng_utils import decode_image_result

    assert decode_image_result({}) is None
