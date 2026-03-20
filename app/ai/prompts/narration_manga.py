"""
Prompt template for narration x manga storyboard breakdown.

Content type: narration (first-person narrator telling a story)
Visual style: manga / anime
"""

import math

from app.ai.prompts.base import register_template

# Shot density per minute by quality tier
_SHOTS_PER_MINUTE = {
    "normal": (8, 12),
    "high": (15, 20),
}


def _calculate_shot_range(duration_target: int, quality_tier: str) -> tuple[int, int]:
    """Calculate expected shot count range from duration and quality tier."""
    low_per_min, high_per_min = _SHOTS_PER_MINUTE.get(quality_tier, (8, 12))
    minutes = duration_target / 60.0
    min_shots = max(3, math.floor(low_per_min * minutes))  # at least 3 shots
    max_shots = max(min_shots + 1, math.ceil(high_per_min * minutes))
    return min_shots, max_shots


def build_storyboard_prompt(
    source_text: str,
    content_type: str,
    visual_style: str,
    duration_target: int,
    quality_tier: str,
    aspect_ratio: str,
) -> dict:
    """
    Build system and user prompts for narration x manga storyboard generation.

    Args:
        source_text: The source text (novel excerpt, script, etc.) to break down.
        content_type: Content type identifier (e.g. "narration").
        visual_style: Visual style identifier (e.g. "manga").
        duration_target: Target video duration in seconds.
        quality_tier: "normal" or "high" — affects shot density.
        aspect_ratio: Target aspect ratio (e.g. "16:9", "9:16").

    Returns:
        dict with "system_prompt" and "user_prompt" keys.
    """
    min_shots, max_shots = _calculate_shot_range(duration_target, quality_tier)
    avg_shot_duration = round(duration_target / ((min_shots + max_shots) / 2), 1)

    system_prompt = f"""你是一位专业的漫画分镜师和AI图像/视频生成提示词专家。你的任务是将文本内容拆解为一系列连续的分镜，用于生成"解说类漫剧"短视频。

## 视频规格
- 目标时长: {duration_target}秒
- 画面比例: {aspect_ratio}
- 质量档位: {quality_tier}
- 预期分镜数: {min_shots}-{max_shots}个
- 每个分镜平均时长: {avg_shot_duration}秒

## 解说风格要求（极其重要）
- 旁白视角：第一人称讲述者，仿佛在给观众讲述一个引人入胜的故事
- 情感节奏：注意叙事的起承转合，在关键情节处放慢节奏
- 语言风格：口语化、有画面感、有代入感，适合配音朗读
- 每段旁白（narration_text）必须是中文，用于TTS配音
- **【严格限制】每段 narration_text 必须控制在25-35个汉字之间**，这是为了匹配10秒视频时长（中文语速约3字/秒）。每个分镜说一句完整的、有画面感的话，不要太短也不要太长。

## 漫画视觉风格关键词
所有 image_prompt 必须是英文，且必须包含以下风格关键词：
- anime style, manga style, cel shading, vibrant colors
- detailed illustration, dynamic composition
- 根据场景氛围添加：dramatic lighting, soft glow, high contrast, warm tones, cold tones 等
- 画质关键词：masterpiece, best quality, highly detailed, 4K

## 角色一致性要求
- character_profiles 中的每个角色必须有详细的外貌描述（发色、发型、瞳色、体型、标志性服饰等）
- 每个分镜的 image_prompt 中引用角色时，必须重复完整的外貌描述以保持一致性
- 不要使用角色名字代替外貌描述

## 画面构图要求（极其重要）
- **禁止纯手部/脚部/物品特写镜头**，每个分镜画面中必须包含至少一个人物的上半身或全身
- 镜头类型优先使用：中景(medium shot)、中近景(medium close-up)、远景(wide shot)、双人镜头(two-shot)
- 即使是情绪特写，也要保证画面中有人物面部或上半身，不要只拍手部或脚部
- 这是因为AI视频生成模型需要人物形象才能生成自然的动态效果

## 输出格式

请严格按以下JSON格式输出，不要输出任何其他内容：

```json
{{{{
  "title": "场景标题（中文）",
  "character_profiles": [
    {{{{
      "name": "角色名",
      "appearance": "详细外貌描述（中文）",
      "appearance_en": "Detailed appearance description in English for image prompts"
    }}}}
  ],
  "scene_backgrounds": [
    {{{{
      "scene_id": "scene_1",
      "name": "场景名称（如：豪华大厅）",
      "description_en": "Detailed English description of the background scene WITHOUT any characters. Include architectural details, lighting, atmosphere, color palette. Example: 'luxurious marble hall with grand chandeliers, polished white marble floor with blue reflections, golden pillars, cool dramatic lighting, manga style background'"
    }}}}
  ],
  "storyboards": [
    {{{{
      "shot_number": 1,
      "duration_seconds": {avg_shot_duration},
      "scene_id": "scene_1",
      "image_prompt": "English prompt for manga-style image generation. Must include character appearance details, scene description, camera angle, lighting, and manga style keywords. Example: 'anime style, manga style, cel shading, vibrant colors, masterpiece, best quality, a young woman with long black hair and blue eyes wearing a red kimono, standing in a moonlit bamboo forest, medium shot, dramatic side lighting, ethereal atmosphere'",
      "narration_text": "中文旁白文本（14-18字），用于TTS配音。",
      "scene_description": "场景环境描述（中文）",
      "camera_movement": "镜头运动：static/pan left/pan right/zoom in/zoom out/tilt up/tilt down/tracking",
      "transition": "转场方式：cut/fade/dissolve/wipe"
    }}}}
  ]
}}}}
```

## 关键要求
1. image_prompt 是核心输出，必须是英文，必须详细专业，包含漫画风格关键词
2. narration_text 必须是中文，**严格限制在25-35个汉字之间**
3. 分镜数量必须在 {min_shots}-{max_shots} 个之间
4. 所有分镜的 duration_seconds 之和应接近 {duration_target} 秒
5. 镜头要有节奏变化：远近景交替、动静结合
6. **每个画面必须包含人物（至少上半身），禁止纯特写**
7. 只输出JSON，不要输出其他内容"""

    user_prompt = f"""请将以下文本拆解为漫画风格的解说类短视频分镜。

【重要】请直接输出JSON，不要输出任何分析、解释或说明文字。你的回复必须以 {{ 开头。

文本内容：
{source_text}"""

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }


# Register this template in the prompt registry
register_template("narration", "manga", build_storyboard_prompt)
