"""Tests for app.services.ffmpeg_utils."""

import json
import os
import tempfile
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from app.services.ffmpeg_utils import (
    align_video_to_audio,
    concatenate_clips,
    create_asset_package,
    get_media_duration,
)


# ---------------------------------------------------------------------------
# get_media_duration
# ---------------------------------------------------------------------------


def test_get_media_duration():
    """ffprobe JSON output is parsed correctly."""
    ffprobe_output = json.dumps({"format": {"duration": "12.345"}})
    mock_result = MagicMock(stdout=ffprobe_output, returncode=0)

    with patch("app.services.ffmpeg_utils.subprocess.run", return_value=mock_result) as mock_run:
        duration = get_media_duration("/tmp/test.mp4")

    assert duration == pytest.approx(12.345)
    mock_run.assert_called_once()
    # Verify ffprobe was called with the right file
    args = mock_run.call_args[0][0]
    assert args[0] == "ffprobe"
    assert "/tmp/test.mp4" in args


def test_get_media_duration_failure():
    """Returns 0.0 when ffprobe fails or output is unparseable."""
    mock_result = MagicMock(stdout="not json", returncode=1)

    with patch("app.services.ffmpeg_utils.subprocess.run", return_value=mock_result):
        duration = get_media_duration("/tmp/bad.mp4")

    assert duration == 0.0


def test_get_media_duration_timeout():
    """Returns 0.0 when ffprobe times out."""
    import subprocess

    with patch(
        "app.services.ffmpeg_utils.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=10),
    ):
        duration = get_media_duration("/tmp/slow.mp4")

    assert duration == 0.0


# ---------------------------------------------------------------------------
# align_video_to_audio
# ---------------------------------------------------------------------------


def _mock_duration(durations: dict[str, float]):
    """Return a side_effect function for get_media_duration."""
    def _side_effect(path):
        return durations.get(path, 0.0)
    return _side_effect


def test_align_video_longer():
    """When video > audio, ffmpeg trims the video."""
    durations = {"/tmp/video.mp4": 10.0, "/tmp/audio.mp3": 5.0}
    mock_result = MagicMock(returncode=0, stderr="")

    with (
        patch("app.services.ffmpeg_utils.get_media_duration", side_effect=_mock_duration(durations)),
        patch("app.services.ffmpeg_utils.subprocess.run", return_value=mock_result) as mock_run,
    ):
        result = align_video_to_audio("/tmp/video.mp4", "/tmp/audio.mp3", "/tmp/out.mp4")

    assert result is True
    # Should call ffmpeg with -t for trimming, and -shortest flag
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-t" in cmd
    assert "-shortest" in cmd
    # tpad should NOT be used when video is longer
    assert "tpad" not in " ".join(cmd)


def test_align_video_shorter():
    """When video < audio, ffmpeg freezes last frame with tpad."""
    durations = {"/tmp/video.mp4": 3.0, "/tmp/audio.mp3": 7.0}
    mock_result = MagicMock(returncode=0, stderr="")

    with (
        patch("app.services.ffmpeg_utils.get_media_duration", side_effect=_mock_duration(durations)),
        patch("app.services.ffmpeg_utils.subprocess.run", return_value=mock_result) as mock_run,
    ):
        result = align_video_to_audio("/tmp/video.mp4", "/tmp/audio.mp3", "/tmp/out.mp4")

    assert result is True
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    # Should use tpad filter for freeze-frame
    cmd_str = " ".join(cmd)
    assert "tpad" in cmd_str
    assert "stop_mode=clone" in cmd_str


def test_align_zero_audio_duration():
    """Returns False when audio duration is 0."""
    durations = {"/tmp/video.mp4": 5.0, "/tmp/audio.mp3": 0.0}

    with patch("app.services.ffmpeg_utils.get_media_duration", side_effect=_mock_duration(durations)):
        result = align_video_to_audio("/tmp/video.mp4", "/tmp/audio.mp3", "/tmp/out.mp4")

    assert result is False


def test_align_zero_video_duration():
    """Returns False when video duration is 0."""
    durations = {"/tmp/video.mp4": 0.0, "/tmp/audio.mp3": 5.0}

    with patch("app.services.ffmpeg_utils.get_media_duration", side_effect=_mock_duration(durations)):
        result = align_video_to_audio("/tmp/video.mp4", "/tmp/audio.mp3", "/tmp/out.mp4")

    assert result is False


def test_align_ffmpeg_failure():
    """Returns False when ffmpeg returns non-zero exit code."""
    durations = {"/tmp/video.mp4": 10.0, "/tmp/audio.mp3": 5.0}
    mock_result = MagicMock(returncode=1, stderr="Error encoding")

    with (
        patch("app.services.ffmpeg_utils.get_media_duration", side_effect=_mock_duration(durations)),
        patch("app.services.ffmpeg_utils.subprocess.run", return_value=mock_result),
    ):
        result = align_video_to_audio("/tmp/video.mp4", "/tmp/audio.mp3", "/tmp/out.mp4")

    assert result is False


# ---------------------------------------------------------------------------
# concatenate_clips
# ---------------------------------------------------------------------------


def test_concatenate_clips():
    """Successful concatenation calls ffmpeg concat demuxer."""
    mock_result = MagicMock(returncode=0, stderr="")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "final.mp4")

        with patch("app.services.ffmpeg_utils.subprocess.run", return_value=mock_result) as mock_run:
            result = concatenate_clips(
                ["/tmp/clip1.mp4", "/tmp/clip2.mp4"],
                output_path,
            )

        assert result is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-f" in cmd
        assert "concat" in cmd
        # Concat list file should be cleaned up
        assert not os.path.exists(output_path + ".txt")


def test_concatenate_no_clips():
    """Returns False when clip list is empty."""
    result = concatenate_clips([], "/tmp/out.mp4")
    assert result is False


def test_concatenate_ffmpeg_failure():
    """Returns False when ffmpeg concat fails."""
    mock_result = MagicMock(returncode=1, stderr="concat error")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "final.mp4")

        with patch("app.services.ffmpeg_utils.subprocess.run", return_value=mock_result):
            result = concatenate_clips(["/tmp/clip1.mp4"], output_path)

        assert result is False
        # Concat list file should still be cleaned up
        assert not os.path.exists(output_path + ".txt")


# ---------------------------------------------------------------------------
# create_asset_package
# ---------------------------------------------------------------------------


def test_create_asset_package():
    """Creates a ZIP file containing the specified files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        file_a = os.path.join(tmpdir, "a.txt")
        file_b = os.path.join(tmpdir, "b.txt")
        with open(file_a, "w") as f:
            f.write("content A")
        with open(file_b, "w") as f:
            f.write("content B")

        zip_path = os.path.join(tmpdir, "package.zip")
        result = create_asset_package(
            {"folder/a.txt": file_a, "folder/b.txt": file_b},
            zip_path,
        )

        assert result is True
        assert os.path.exists(zip_path)

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "folder/a.txt" in names
            assert "folder/b.txt" in names
            assert zf.read("folder/a.txt") == b"content A"
            assert zf.read("folder/b.txt") == b"content B"


def test_create_asset_package_missing_file():
    """Skips missing files but still creates ZIP."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_a = os.path.join(tmpdir, "a.txt")
        with open(file_a, "w") as f:
            f.write("content A")

        zip_path = os.path.join(tmpdir, "package.zip")
        result = create_asset_package(
            {"a.txt": file_a, "missing.txt": "/nonexistent/path.txt"},
            zip_path,
        )

        assert result is True
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "a.txt" in names
            assert "missing.txt" not in names
