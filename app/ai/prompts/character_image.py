"""
Prompt template for character reference image generation (manga style).

Generates a full-body character portrait suitable for use as a reference
across multiple storyboard shots.
"""

from app.ai.prompts.base import register_template


def build_character_image_prompt(
    character_name: str,
    appearance_en: str,
    visual_style: str = "manga",
    aspect_ratio: str = "9:16",
) -> str:
    """
    Build an image generation prompt for a character reference portrait.

    Args:
        character_name: Character name (for logging only, not in prompt).
        appearance_en: English appearance description from LLM output.
        visual_style: Visual style (manga/realistic/pet).
        aspect_ratio: Target aspect ratio.

    Returns:
        English prompt string for Jimeng T2I API.
    """
    style_keywords = {
        "manga": "anime style, manga style, cel shading, vibrant colors",
        "realistic": "photorealistic, cinematic, film grain, dramatic lighting",
        "pet": "anime style, chibi, cute, kawaii, soft colors",
    }

    style = style_keywords.get(visual_style, style_keywords["manga"])

    prompt = (
        f"{style}, masterpiece, best quality, highly detailed, "
        f"character portrait, full body shot, "
        f"{appearance_en}, "
        f"simple clean background, soft studio lighting, "
        f"standing pose, looking at viewer"
    )

    return prompt


# Register for character image generation
register_template("character_image", "manga", build_character_image_prompt)
register_template("character_image", "realistic", build_character_image_prompt)
