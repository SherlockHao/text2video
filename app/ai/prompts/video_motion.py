"""
Prompt template for video motion generation (image-to-video).

Generates motion prompts for Jimeng I2V API based on shot description
and camera movement instructions.
"""

from app.ai.prompts.base import register_template

# Camera movement mapping: storyboard terms → I2V prompt keywords
_CAMERA_MOVEMENTS = {
    "static": "static shot, minimal camera movement",
    "pan left": "camera slowly pans left, smooth horizontal movement",
    "pan right": "camera slowly pans right, smooth horizontal movement",
    "zoom in": "camera slowly zooms in, focus tightening",
    "zoom out": "camera slowly zooms out, revealing wider scene",
    "tilt up": "camera tilts upward, revealing from bottom to top",
    "tilt down": "camera tilts downward, revealing from top to bottom",
    "tracking": "camera tracking shot, following the subject's movement",
    "dolly": "camera dolly forward, smooth approach",
}

# Common anime motion keywords
_ANIME_MOTION = "subtle animation, hair flowing gently, cloth physics, ambient particles"


def build_video_motion_prompt(
    scene_description: str = "",
    camera_movement: str = "static",
    visual_style: str = "manga",
    narration_text: str = "",
) -> str:
    """
    Build a motion prompt for I2V (image-to-video) generation.

    The I2V model already has the image as visual input, so the prompt
    focuses on MOTION and CAMERA rather than appearance.

    Args:
        scene_description: Scene context from storyboard.
        camera_movement: Camera movement type from storyboard.
        visual_style: Visual style for style-specific motion keywords.
        narration_text: Optional narration for context (not directly used in prompt).

    Returns:
        English motion prompt string for Jimeng I2V API.
    """
    parts = []

    # Camera movement
    cam = _CAMERA_MOVEMENTS.get(camera_movement.lower().strip(), _CAMERA_MOVEMENTS["static"])
    parts.append(cam)

    # Style-specific motion
    if visual_style == "manga":
        parts.append(_ANIME_MOTION)
    elif visual_style == "realistic":
        parts.append("natural movement, cinematic motion, film-like quality")

    # Scene-based motion hints (extract action keywords from description)
    if scene_description:
        # Keep it brief — I2V prompts should focus on motion, not scene description
        # The image already establishes the scene
        desc_lower = scene_description.lower()
        if any(w in desc_lower for w in ["走", "跑", "行走", "walking", "running"]):
            parts.append("walking motion, footsteps")
        elif any(w in desc_lower for w in ["站", "伫立", "standing"]):
            parts.append("gentle breathing, subtle body sway")
        elif any(w in desc_lower for w in ["坐", "sitting"]):
            parts.append("subtle hand movement, turning pages")
        elif any(w in desc_lower for w in ["回头", "转身", "turning"]):
            parts.append("head turning, dramatic reveal")

    parts.append("anime style, smooth animation, high quality")

    return ", ".join(parts)


# Register
register_template("video_motion", "manga", build_video_motion_prompt)
register_template("video_motion", "realistic", build_video_motion_prompt)
