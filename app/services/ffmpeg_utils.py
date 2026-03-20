"""
FFmpeg utilities for audio-video alignment and assembly.

Core logic:
- TTS audio length is the BASELINE for each shot
- If video is longer than audio: trim video to match
- If video is shorter than audio: freeze last frame to fill
- Concatenate all shots into final MP4
- Create ZIP asset package
"""

import logging
import os
import subprocess
import json
from pathlib import Path

logger = logging.getLogger(__name__)


def get_media_duration(file_path: str) -> float:
    """Get duration of a media file in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception as e:
        logger.warning("Could not get duration for %s: %s", file_path, e)
        return 0.0


def align_video_to_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
    fade_duration: float = 0.3,
) -> bool:
    """
    Align a video clip to match audio duration.

    - If video > audio: trim video
    - If video < audio: freeze last frame to fill
    - Overlay audio onto video

    Returns True on success.
    """
    audio_duration = get_media_duration(audio_path)
    video_duration = get_media_duration(video_path)

    if audio_duration <= 0:
        logger.error("Audio duration is 0 for %s", audio_path)
        return False

    if video_duration <= 0:
        logger.error("Video duration is 0 for %s", video_path)
        return False

    logger.info(
        "Aligning: video=%.2fs, audio=%.2fs, target=%.2fs",
        video_duration, audio_duration, audio_duration,
    )

    try:
        if video_duration >= audio_duration:
            # Video is longer — trim to audio length and overlay audio
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-t", str(audio_duration),
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                output_path,
            ]
        else:
            # Video is shorter — freeze last frame, then overlay audio
            # Use tpad filter to extend video by freezing last frame
            pad_duration = audio_duration - video_duration
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-filter_complex",
                f"[0:v]tpad=stop_mode=clone:stop_duration={pad_duration:.3f}[v]",
                "-map", "[v]",
                "-map", "1:a",
                "-t", str(audio_duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                output_path,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("FFmpeg align failed: %s", result.stderr[-500:])
            return False

        logger.info("Aligned clip saved to %s", output_path)
        return True

    except subprocess.TimeoutExpired:
        logger.error("FFmpeg align timed out for %s", output_path)
        return False
    except Exception as e:
        logger.error("FFmpeg align error: %s", e)
        return False


def concatenate_clips(
    clip_paths: list[str],
    output_path: str,
    transition: str = "none",
) -> bool:
    """
    Concatenate multiple video clips into one final video.
    Uses ffmpeg concat demuxer for frame-accurate concatenation.

    Returns True on success.
    """
    if not clip_paths:
        logger.error("No clips to concatenate")
        return False

    # Create concat list file
    list_path = output_path + ".txt"
    try:
        with open(list_path, "w") as f:
            for clip in clip_paths:
                # Use absolute paths for concat demuxer reliability
                abs_clip = os.path.abspath(clip)
                escaped = abs_clip.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error("FFmpeg concat failed: %s", result.stderr[-500:])
            return False

        logger.info("Concatenated %d clips to %s", len(clip_paths), output_path)
        return True

    except Exception as e:
        logger.error("FFmpeg concat error: %s", e)
        return False
    finally:
        # Clean up list file
        if os.path.exists(list_path):
            os.unlink(list_path)


def create_asset_package(
    files: dict[str, str],
    output_path: str,
) -> bool:
    """
    Create a ZIP asset package.

    Args:
        files: {archive_name: file_path} mapping
        output_path: output ZIP file path

    Returns True on success.
    """
    import zipfile

    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, path in files.items():
                if os.path.exists(path):
                    zf.write(path, name)
                else:
                    logger.warning("Skipping missing file: %s", path)

        logger.info("Created asset package: %s (%d files)", output_path, len(files))
        return True
    except Exception as e:
        logger.error("ZIP creation failed: %s", e)
        return False
