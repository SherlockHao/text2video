"""
Narration utilities for TTS length control.

Ensures narration text fits within the target video duration.
If too long, calls LLM to shorten it.
"""

import logging

logger = logging.getLogger(__name__)

# Chinese speech rate: ~3-4 chars per second for natural reading
CHARS_PER_SECOND = 3.5


def estimate_tts_duration(text: str, speed: float = 1.0) -> float:
    """Estimate TTS duration in seconds for Chinese text."""
    if not text:
        return 0.0
    char_count = len(text.strip())
    return char_count / (CHARS_PER_SECOND * speed)


def is_narration_too_long(text: str, max_duration: float, speed: float = 1.0) -> bool:
    """Check if narration would exceed target duration."""
    est = estimate_tts_duration(text, speed)
    return est > max_duration


def shorten_narration_via_llm(
    text: str,
    max_chars: int,
    context: str = "",
) -> str:
    """Use LLM to shorten narration while preserving meaning.

    Args:
        text: Original narration text.
        max_chars: Target maximum character count.
        context: Scene context for better shortening.

    Returns:
        Shortened text.
    """
    from vendor.qwen.client import chat_with_system

    system_prompt = "你是一个文案精简专家。把给你的旁白文案缩短到指定字数以内，保留核心情感和画面感，不要改变人称视角。只输出缩短后的文案，不要输出其他内容。"

    user_prompt = f"请将以下旁白缩短到{max_chars}个汉字以内：\n\n{text}"
    if context:
        user_prompt += f"\n\n场景背景：{context}"

    try:
        result = chat_with_system(system_prompt, user_prompt, max_tokens=200)
        shortened = result.strip().strip('"').strip("'").strip("「」")
        if len(shortened) <= max_chars and len(shortened) > 0:
            logger.info("Shortened narration: %d → %d chars", len(text), len(shortened))
            return shortened
        # If still too long, hard truncate
        return shortened[:max_chars]
    except Exception as e:
        logger.error("Failed to shorten narration: %s", e)
        # Fallback: hard truncate
        return text[:max_chars]
