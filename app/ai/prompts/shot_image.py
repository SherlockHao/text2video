"""
Prompt template for storyboard shot image generation (manga style).

Enhances the LLM-generated image_prompt with character consistency
descriptions and quality keywords.
"""

from app.ai.prompts.base import register_template


def build_shot_image_prompt(
    base_prompt: str,
    character_appearances: list[str] | None = None,
    visual_style: str = "manga",
    aspect_ratio: str = "9:16",
) -> str:
    """
    Build an enhanced image prompt for a storyboard shot.

    Takes the LLM-generated image_prompt and enriches it with:
    - Character appearance details for consistency
    - Quality/style keywords if missing

    Args:
        base_prompt: The image_prompt from LLM storyboard output.
        character_appearances: List of English appearance descriptions
            for characters in this shot.
        visual_style: Visual style identifier.
        aspect_ratio: Target aspect ratio.

    Returns:
        Enhanced English prompt string for Jimeng T2I API.
    """
    style_keywords = {
        "manga": "anime style, manga style, cel shading, vibrant colors",
        "realistic": "photorealistic, cinematic, film grain",
        "pet": "anime style, chibi, cute, kawaii",
    }

    style = style_keywords.get(visual_style, style_keywords["manga"])
    quality = "masterpiece, best quality, highly detailed, 4K"

    # Start with quality and style if not already present
    parts = []
    if "masterpiece" not in base_prompt.lower():
        parts.append(quality)
    if "anime style" not in base_prompt.lower() and "manga style" not in base_prompt.lower():
        parts.append(style)

    parts.append(base_prompt)

    # Append character appearances for consistency (if not already in prompt)
    if character_appearances:
        for appearance in character_appearances:
            # Only add if the appearance description is not already in the prompt
            # Check by first 30 chars to avoid duplicates
            if appearance[:30].lower() not in base_prompt.lower():
                parts.append(appearance)

    return ", ".join(parts)


# Register
register_template("shot_image", "manga", build_shot_image_prompt)
register_template("shot_image", "realistic", build_shot_image_prompt)
