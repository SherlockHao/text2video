"""
漫剧 (Manga Short Drama) Production Pipeline v9 — Complete Design
=================================================================

Target: 40-second 9:16 vertical manga-style short drama
Genre:  女频 豪门总裁/青春甜宠
Stack:  Qwen 3.5-Plus → Jimeng T2I 4.0 → Kling V3 I2V → MiniMax TTS → FFmpeg

This file is EXECUTABLE PSEUDOCODE. Every function signature, JSON schema,
and prompt string is copy-paste ready for implementation.
"""

# =============================================================================
# PIPELINE OVERVIEW (8 stages, strict sequential dependencies)
# =============================================================================
#
# Stage 0: Input validation
# Stage 1: LLM storyboard generation (Qwen 3.5-Plus)
# Stage 2: Character reference image generation (Jimeng T2I)
# Stage 3: Scene background generation (Jimeng T2I)
# Stage 4: Shot first-frame generation (Jimeng T2I, with char appearance baked in)
# Stage 5: Video generation (Kling V3 I2V, sequential within scene for last-frame continuity)
# Stage 6: TTS narration (MiniMax, parallel)
# Stage 7: Assembly (FFmpeg: align → concat → BGM overlay)
# Stage 8: Quality gate (automated checks)
#
# Key change from v7/v8: Stages 4+5 use Kling V3 (not Jimeng I2V).
# Kling V3 supports 3-15s duration, pro mode, and produces much better anime motion.

import json


# =============================================================================
# STAGE 1: LLM STORYBOARD — EXACT JSON SCHEMA
# =============================================================================

STORYBOARD_OUTPUT_SCHEMA = {
    "title": "str — 场景标题（中文）",
    "character_profiles": [
        {
            "char_id": "str — unique ID like 'char_su_niannian'",
            "name": "str — 角色名（中文）",
            "appearance": "str — 详细外貌描述（中文）",
            "appearance_en": (
                "str — FROZEN English appearance tag. "
                "This exact string is pasted into every image prompt. "
                "Must include: hair color+style, eye color, skin tone, "
                "body type, outfit with colors+materials, accessories. "
                "Example: 'young woman, long straight black hair with blunt bangs, "
                "large dark brown eyes, fair skin, slender figure, wearing a white "
                "cotton blouse with pearl buttons tucked into a black high-waisted "
                "pencil skirt, small silver wristwatch on left wrist'"
            ),
            "voice_id": "str — MiniMax voice ID, e.g. 'female-shaonv'",
        }
    ],
    "scene_backgrounds": [
        {
            "scene_id": "str — unique ID like 'scene_lobby'",
            "name": "str — 场景名称（中文）",
            "description_en": (
                "str — Detailed English background description WITHOUT characters. "
                "Include: architecture, materials, lighting, color palette, atmosphere. "
                "Always end with 'manga style background, no characters, no people'"
            ),
        }
    ],
    "storyboards": [
        {
            "shot_number": "int — 1-indexed",
            "duration_seconds": "float — target duration, 5-10 for Kling V3",
            "scene_id": "str — references scene_backgrounds[].scene_id",
            "characters_in_shot": ["str — char_id references, e.g. 'char_su_niannian'"],
            "shot_type": "str — wide/medium/medium_closeup/closeup/two_shot",
            "image_prompt": (
                "str — English. Static frame description. "
                "MUST contain the FULL appearance_en of every character in the shot. "
                "MUST contain the scene background description. "
                "MUST contain style keywords. "
                "Structure: [quality] + [style] + [shot_type] + [character(s) with FULL appearance] + "
                "[pose/expression] + [background] + [lighting/atmosphere]"
            ),
            "video_prompt": (
                "str — English. Motion-only description for Kling V3 I2V. "
                "Describes WHAT HAPPENS: character actions, facial expressions, "
                "object interactions, camera movement. "
                "DO NOT repeat appearance or background (the image already has those). "
                "Be specific: 'woman turns head slowly to the left, hair sways, "
                "eyes widen slightly, camera slowly dollies forward' — NOT 'subtle animation'"
            ),
            "narration_text": (
                "str — 中文旁白, 25-35 characters. "
                "At 3.5 chars/sec with speed=0.9, 25 chars ≈ 7.9s, 35 chars ≈ 11.1s. "
                "For a 10s shot, aim for 28-32 chars."
            ),
            "scene_description": "str — 场景环境描述（中文）",
            "camera_movement": "str — static/pan_left/pan_right/zoom_in/zoom_out/tilt_up/tilt_down/tracking/dolly_in",
            "transition": "str — cut/fade/dissolve",
        }
    ],
}


# =============================================================================
# STAGE 1: LLM STORYBOARD PROMPT (for Qwen 3.5-Plus)
# =============================================================================

def build_storyboard_prompt_v9(
    source_text: str,
    duration_target: int = 40,
    aspect_ratio: str = "9:16",
) -> dict:
    """
    Build system + user prompts for storyboard generation.

    Key improvements over v8:
    - Explicit char_id system for referencing characters
    - characters_in_shot field forces LLM to declare who's in each shot
    - shot_type field prevents abstract/object-only frames
    - Narration length tied to duration via chars-per-second math
    - video_prompt examples are action-specific, not generic
    """
    # For 40s target with 5-10s shots, we want 4-8 shots
    min_shots = max(3, duration_target // 10)
    max_shots = max(min_shots + 1, duration_target // 5)

    system_prompt = f"""你是一位专业的漫画分镜师和AI图像/视频生成提示词专家。你的任务是将文本内容拆解为一系列连续的分镜，用于生成"解说类漫剧"短视频。

## 视频规格
- 目标时长: {duration_target}秒
- 画面比例: {aspect_ratio} (竖屏)
- 预期分镜数: {min_shots}-{max_shots}个
- 每个分镜时长: 5-10秒 (Kling V3 支持3-15秒)
- 所有分镜的 duration_seconds 之和必须接近 {duration_target} 秒

## 角色一致性要求（最核心）
1. character_profiles 中每个角色必须有一个唯一的 char_id
2. appearance_en 是一个"冻结描述标签"——在整个项目中永远不变
3. appearance_en 必须极其具体：发色+发型+长度+刘海、瞳色、肤色、体型、上装颜色材质、下装颜色材质、鞋子、饰品
4. 每个分镜的 image_prompt 中，必须原文复制对应角色的 appearance_en，不得省略或改写
5. 示例 appearance_en: "young woman, long straight black hair reaching her waist with blunt bangs, large dark brown eyes, fair skin, slender figure, wearing a white cotton blouse with pearl buttons tucked into a black high-waisted pencil skirt, black stiletto heels, small silver wristwatch on left wrist"

## image_prompt 构造规则
每个 image_prompt 必须按以下顺序组合：
1. 画质关键词: "masterpiece, best quality, highly detailed, 4K"
2. 风格关键词: "anime style, manga style, cel shading, vibrant colors, detailed illustration"
3. 构图/景别: "wide shot" / "medium shot" / "medium close-up" / "two-shot"
4. 角色描述: 逐字复制 appearance_en + 当前姿态/表情
5. 场景背景: 引用 scene_backgrounds 中的 description_en 核心元素
6. 光线氛围: "dramatic lighting" / "soft warm glow" / "cold blue tones" 等

## video_prompt 构造规则（极其重要）
video_prompt 只描述动态，不重复外貌和场景（因为首帧图已包含）。必须具体：
- 好的: "the woman slowly turns her head to the right, her long black hair sways gently, tears form in her eyes, camera slowly zooms in"
- 坏的: "subtle animation, gentle movement" （太笼统，kling V3 不知道该动什么）
- 好的: "the man stands up from the chair, walks around the desk with measured steps, stops in front of the woman, camera tracks his movement"
- 坏的: "character moves, dramatic scene" （完全没用）

## 旁白控制（严格）
- 每段 narration_text 必须是中文
- 中文语速约 3.5字/秒（speed=0.9时）
- 5秒分镜 → 约15-17个字
- 8秒分镜 → 约25-28个字
- 10秒分镜 → 约30-35个字
- 公式: max_chars = duration_seconds × 3.5 × 0.9 ≈ duration_seconds × 3.15
- 如果旁白在TTS后超出视频时长，会导致冻帧。所以宁短勿长。

## 画面构图要求
- 禁止纯手部/脚部/物品特写
- 每个分镜画面必须包含至少一个人物的上半身或全身
- 优先使用: medium shot, medium close-up, wide shot, two-shot
- characters_in_shot 字段必须列出出现在该画面中的所有角色 char_id

## 输出格式
严格按以下JSON格式输出，不要输出任何其他内容：

```json
{{{{
  "title": "场景标题",
  "character_profiles": [
    {{{{
      "char_id": "char_xxx",
      "name": "角色名",
      "appearance": "中文外貌描述",
      "appearance_en": "FROZEN English appearance tag — 极其详细"
    }}}}
  ],
  "scene_backgrounds": [
    {{{{
      "scene_id": "scene_xxx",
      "name": "场景名",
      "description_en": "Detailed background WITHOUT characters, ending with 'manga style background, no characters, no people'"
    }}}}
  ],
  "storyboards": [
    {{{{
      "shot_number": 1,
      "duration_seconds": 8,
      "scene_id": "scene_xxx",
      "characters_in_shot": ["char_xxx"],
      "shot_type": "medium shot",
      "image_prompt": "masterpiece, best quality, highly detailed, 4K, anime style, manga style, cel shading, vibrant colors, detailed illustration, medium shot of [FULL appearance_en], [pose], [scene background elements], [lighting]",
      "video_prompt": "[specific action: who does what, facial expression change, camera movement]",
      "narration_text": "中文旁白（字数 ≈ duration × 3.15）",
      "scene_description": "中文场景描述",
      "camera_movement": "zoom_in",
      "transition": "cut"
    }}}}
  ]
}}}}
```

## 关键约束
1. 分镜数量 {min_shots}-{max_shots} 个
2. duration_seconds 总和 ≈ {duration_target}s
3. image_prompt 必须包含角色完整 appearance_en（逐字复制）
4. video_prompt 必须描述具体动作，禁止笼统描述
5. narration_text 字数严格遵守: max_chars = floor(duration_seconds × 3.15)
6. 只输出JSON"""

    user_prompt = f"""请将以下文本拆解为漫画风格的解说类短视频分镜。

【重要】请直接输出JSON，不要输出任何分析或说明。你的回复必须以 {{ 开头。

文本内容：
{source_text}"""

    return {"system_prompt": system_prompt, "user_prompt": user_prompt}


# =============================================================================
# STAGE 2: CHARACTER REFERENCE IMAGE GENERATION
# =============================================================================

def build_character_ref_prompt(appearance_en: str) -> str:
    """
    Build Jimeng T2I prompt for a character reference sheet.

    Strategy for consistency WITHOUT element-binding:
    1. Generate a SINGLE canonical reference image per character
    2. Use an extremely detailed appearance_en (the "frozen tag")
    3. Pin the pose to "standing, front view, looking at viewer" — a neutral pose
       that shows all visual features clearly
    4. Use "simple clean background" to prevent scene contamination
    5. Store the frozen tag and use it verbatim in every shot prompt

    This reference image is for HUMAN REVIEW ONLY — it is NOT fed into
    subsequent T2I calls (Jimeng T2I has no image-reference input).
    The consistency comes from repeating the identical text description.
    """
    return (
        "masterpiece, best quality, highly detailed, 4K, "
        "anime style, manga style, cel shading, vibrant colors, "
        "character reference sheet, full body portrait, "
        "front view, standing pose, looking at viewer, "
        f"{appearance_en}, "
        "simple solid light grey background, soft studio lighting, "
        "no other characters, solo"
    )


def build_character_ref_prompt_multiview(appearance_en: str) -> str:
    """
    Alternative: generate a 3-angle reference sheet.
    Useful for verifying the frozen tag produces consistent results.
    """
    return (
        "masterpiece, best quality, highly detailed, 4K, "
        "anime style, manga style, cel shading, vibrant colors, "
        "character reference sheet, three views, "
        "front view and side view and three-quarter view, "
        f"{appearance_en}, "
        "simple white background, clean layout, "
        "no other characters, reference sheet style"
    )


# Implementation:
def generate_character_references(storyboard: dict, output_dir: str):
    """
    Generate character reference images. Called ONCE before shot generation.

    Returns: {char_id: {"image_path": str, "appearance_en": str}}
    """
    from vendor.jimeng.t2i import generate_image
    import os, time

    results = {}
    for char in storyboard["character_profiles"]:
        char_id = char["char_id"]
        appearance_en = char["appearance_en"]

        prompt = build_character_ref_prompt(appearance_en)
        # 9:16 portrait: 832x1472
        paths = generate_image(
            prompt, width=832, height=1472,
            output_dir=output_dir, prefix=f"char_{char_id}"
        )
        if paths:
            results[char_id] = {
                "image_path": paths[0],
                "appearance_en": appearance_en,
            }
        time.sleep(3)  # Rate limiting

    return results


# =============================================================================
# STAGE 3: SCENE BACKGROUND GENERATION
# =============================================================================

def build_scene_bg_prompt(description_en: str) -> str:
    """
    Build Jimeng T2I prompt for a scene background.

    Key: explicitly exclude characters so the BG is clean.
    These backgrounds serve as VISUAL REFERENCE — they confirm the LLM's
    scene description produces the intended atmosphere.

    The actual shot images will composite characters into the scene via
    the combined prompt (character appearance + scene description).
    """
    # Strip trailing comma/period for clean concatenation
    desc = description_en.rstrip(" ,.")
    return (
        "masterpiece, best quality, highly detailed, 4K, "
        "anime style, manga style, cel shading, vibrant colors, "
        "background art, environment concept art, "
        f"{desc}, "
        "no characters, no people, no figures, empty scene"
    )


def generate_scene_backgrounds(storyboard: dict, output_dir: str):
    """
    Generate one background image per scene. Called ONCE.

    Returns: {scene_id: {"image_path": str, "description_en": str}}
    """
    from vendor.jimeng.t2i import generate_image
    import time

    results = {}
    for scene in storyboard["scene_backgrounds"]:
        scene_id = scene["scene_id"]
        desc_en = scene["description_en"]

        prompt = build_scene_bg_prompt(desc_en)
        paths = generate_image(
            prompt, width=832, height=1472,
            output_dir=output_dir, prefix=f"scene_{scene_id}"
        )
        if paths:
            results[scene_id] = {
                "image_path": paths[0],
                "description_en": desc_en,
            }
        time.sleep(3)

    return results


# =============================================================================
# STAGE 4: SHOT FIRST-FRAME GENERATION
# =============================================================================

def build_shot_firstframe_prompt(
    shot: dict,
    char_profiles: dict,  # {char_id: {"appearance_en": str}}
    scene_backgrounds: dict,  # {scene_id: {"description_en": str}}
) -> str:
    """
    Build the image prompt for a shot's first frame.

    CHARACTER CONSISTENCY STRATEGY (the core technique):
    Since Jimeng T2I has no image-reference/element-binding for images,
    consistency is achieved purely through TEXTUAL REPETITION:

    1. The LLM generates a "frozen" appearance_en per character
    2. Every shot prompt contains the FULL frozen tag verbatim
    3. We add scene context from the background description
    4. Quality/style keywords are standardized

    This is the ONLY viable approach with text-only T2I.
    It works well for anime style (less variation than photorealistic).
    """
    # Start with the LLM's image_prompt (which should already contain
    # character appearances, but we verify and augment)
    base_prompt = shot.get("image_prompt", "")

    # Verify all characters' appearances are actually in the prompt
    chars_in_shot = shot.get("characters_in_shot", [])
    missing_appearances = []
    for char_id in chars_in_shot:
        char_info = char_profiles.get(char_id, {})
        appearance = char_info.get("appearance_en", "")
        if appearance and appearance[:40].lower() not in base_prompt.lower():
            missing_appearances.append(appearance)

    # Verify scene background is referenced
    scene_id = shot.get("scene_id", "")
    scene_info = scene_backgrounds.get(scene_id, {})
    scene_desc = scene_info.get("description_en", "")

    # Build augmented prompt
    parts = []

    # Ensure quality+style prefix
    if "masterpiece" not in base_prompt.lower():
        parts.append("masterpiece, best quality, highly detailed, 4K")
    if "anime style" not in base_prompt.lower():
        parts.append("anime style, manga style, cel shading, vibrant colors, detailed illustration")

    parts.append(base_prompt)

    # Append any missing character appearances
    for app in missing_appearances:
        parts.append(app)

    # Append scene context if not present
    if scene_desc and scene_desc[:30].lower() not in base_prompt.lower():
        # Add abbreviated scene context (don't duplicate "no characters" since we HAVE characters)
        scene_brief = scene_desc.replace("no characters, no people", "").strip(" ,.")
        parts.append(f"background: {scene_brief}")

    return ", ".join(parts)


def generate_shot_firstframes(
    storyboard: dict,
    char_profiles: dict,
    scene_backgrounds: dict,
    output_dir: str,
) -> dict:
    """
    Generate first-frame images for all shots.

    Returns: {shot_number: str (image_path)}
    """
    from vendor.jimeng.t2i import generate_image
    import time

    results = {}
    profiles_map = {c["char_id"]: c for c in storyboard["character_profiles"]}

    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        prompt = build_shot_firstframe_prompt(shot, profiles_map, scene_backgrounds)

        paths = generate_image(
            prompt, width=832, height=1472,
            output_dir=output_dir, prefix=f"shot_{sn:02d}"
        )
        if paths:
            results[sn] = paths[0]
        time.sleep(3)

    return results


# =============================================================================
# STAGE 5: VIDEO GENERATION — KLING V3 I2V
# =============================================================================

def build_kling_v3_motion_prompt(shot: dict) -> str:
    """
    Build the motion prompt for Kling V3 I2V.

    BEST PRACTICES FOR KLING V3 ANIME VIDEO:
    1. Focus on MOTION, not appearance (the image already defines appearance)
    2. Be specific about actions: "turns head left" not "moves"
    3. Include subtle ambient motion: "hair sways", "clothes flutter"
    4. Specify camera movement explicitly: "camera slowly zooms in"
    5. Keep prompt under 200 words — Kling V3 ignores excess
    6. Add "anime style, smooth animation" at the end for style reinforcement
    7. Avoid contradictory motions: don't say "static" and "walks forward"

    NEGATIVE PROMPT (always use):
    "blurry, low quality, distorted face, extra fingers, deformed, morphing,
     flickering, abrupt scene change, live action, photorealistic"
    """
    video_prompt = shot.get("video_prompt", "")
    camera = shot.get("camera_movement", "static")

    # Camera movement mapping for Kling V3
    camera_map = {
        "static": "camera remains still",
        "pan_left": "camera slowly pans left",
        "pan_right": "camera slowly pans right",
        "zoom_in": "camera slowly zooms in",
        "zoom_out": "camera slowly pulls back",
        "tilt_up": "camera tilts upward",
        "tilt_down": "camera tilts downward",
        "tracking": "camera follows the subject's movement",
        "dolly_in": "camera smoothly dollies forward",
    }

    parts = []

    if video_prompt:
        parts.append(video_prompt)
    else:
        # Fallback: extract action from scene_description
        parts.append("subtle character animation, gentle breathing")

    # Add camera if not already mentioned in video_prompt
    cam_lower = video_prompt.lower()
    if "camera" not in cam_lower:
        cam_desc = camera_map.get(camera, camera_map["static"])
        parts.append(cam_desc)

    # Always add ambient anime motion and style anchor
    parts.append("hair sways gently, cloth physics, anime style, smooth animation")

    prompt = ", ".join(parts)

    # Truncate to ~180 words max
    words = prompt.split()
    if len(words) > 180:
        prompt = " ".join(words[:180])

    return prompt


KLING_V3_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted face, extra fingers, deformed, morphing, "
    "flickering, abrupt scene change, live action, photorealistic, "
    "text, watermark, signature, frame, border"
)


def generate_videos_with_continuity(
    storyboard: dict,
    shot_images: dict,  # {shot_number: image_path}
    output_dir: str,
    frames_dir: str,
) -> dict:
    """
    Generate videos using Kling V3 I2V with last-frame continuity.

    LAST-FRAME CONTINUITY STRATEGY:
    - Process shots SEQUENTIALLY (not parallel)
    - Within the SAME scene: use the last frame of shot N as the
      first frame of shot N+1 (instead of the T2I-generated image)
    - When scene changes: use the T2I-generated first frame
    - Extract last frame via ffmpeg -sseof -0.1

    This creates smooth visual transitions within a scene without
    needing any image-reference features.

    Returns: {shot_number: video_path}
    """
    from vendor.kling.client import KlingClient
    import subprocess, os, time

    client = KlingClient()
    results = {}
    prev_last_frame = None
    prev_scene_id = None

    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        scene_id = shot.get("scene_id", "")
        duration = shot.get("duration_seconds", 8)

        if sn not in shot_images:
            continue

        # Decide first frame
        same_scene = (scene_id == prev_scene_id) and (prev_last_frame is not None)
        if same_scene:
            first_frame_path = prev_last_frame
        else:
            first_frame_path = shot_images[sn]

        # Build motion prompt
        motion_prompt = build_kling_v3_motion_prompt(shot)

        # Upload image to get URL (Kling V3 needs URL, not base64 for I2V)
        # If first_frame_path is local, encode as base64 data URL or upload to OSS
        image_url_or_b64 = _prepare_image_for_kling(first_frame_path)

        # Submit to Kling V3
        # Key parameters:
        #   model_name="kling-v3"  — latest model, best anime quality
        #   mode="pro"             — professional quality (slower but much better)
        #   duration=str(min(duration, 10))  — Kling V3 supports 3-15s
        #   cfg_scale=0.5          — balance between prompt adherence and image fidelity
        kling_duration = str(max(5, min(int(duration), 10)))
        resp = client.generate_video(
            image=image_url_or_b64,
            prompt=motion_prompt,
            model_name="kling-v3",
            mode="pro",
            duration=kling_duration,
            aspect_ratio="9:16",
            negative_prompt=KLING_V3_NEGATIVE_PROMPT,
            cfg_scale=0.5,
        )

        task_id = resp.get("data", {}).get("task_id")
        if not task_id:
            continue

        # Poll for completion
        data = client.poll_task(task_id, task_type="video", max_wait=600)
        if not data:
            continue

        # Download video
        video_url = data.get("task_result", {}).get("videos", [{}])[0].get("url", "")
        if video_url:
            import requests
            video_path = os.path.join(output_dir, f"shot_{sn:02d}.mp4")
            r = requests.get(video_url, timeout=120)
            with open(video_path, "wb") as f:
                f.write(r.content)
            results[sn] = video_path

            # Extract last frame for continuity
            last_frame_path = os.path.join(frames_dir, f"shot_{sn:02d}_lastframe.png")
            _ok = subprocess.run(
                ["ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path,
                 "-frames:v", "1", last_frame_path],
                capture_output=True, timeout=10,
            )
            if _ok.returncode == 0 and os.path.exists(last_frame_path):
                prev_last_frame = last_frame_path
                prev_scene_id = scene_id
            else:
                prev_last_frame = None

        time.sleep(5)  # Rate limiting between Kling API calls

    return results


def _prepare_image_for_kling(image_path: str) -> str:
    """
    Prepare image for Kling V3 API.
    Kling accepts both URL and base64.
    For local files, convert to base64 data URI.
    """
    import base64
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    # Kling client expects base64 string directly
    return b64


# =============================================================================
# STAGE 6: TTS & NARRATION-VIDEO SYNC
# =============================================================================

def calculate_max_narration_chars(duration_seconds: float, speed: float = 0.9) -> int:
    """
    Calculate maximum narration characters to fit within video duration.

    Chinese TTS at speed=0.9: ~3.15 effective chars/sec
    We use 90% of duration to leave a 1-second tail buffer.
    """
    effective_rate = 3.5 * speed  # chars per second
    usable_duration = duration_seconds * 0.90  # 10% buffer
    return int(usable_duration * effective_rate)


def validate_and_trim_narrations(storyboard: dict) -> dict:
    """
    Pre-TTS validation: ensure every narration fits its shot duration.

    Returns updated storyboard with trimmed narrations.
    """
    for shot in storyboard["storyboards"]:
        duration = shot.get("duration_seconds", 8)
        narration = shot.get("narration_text", "")
        max_chars = calculate_max_narration_chars(duration)

        if len(narration) > max_chars:
            # Use LLM to shorten (preserving meaning)
            from app.services.narration_utils import shorten_narration_via_llm
            shot["narration_text"] = shorten_narration_via_llm(
                narration, max_chars, shot.get("scene_description", "")
            )
    return storyboard


async def generate_tts_all(
    storyboard: dict,
    voice_id: str = "female-shaonv",
    output_dir: str = ".",
) -> dict:
    """
    Generate TTS for all shots in parallel.

    Returns: {shot_number: audio_path}

    TTS speed is set to 0.9 to match the narration budget calculation.
    """
    from app.ai.providers.minimax_tts import MiniMaxTTSProvider
    import os

    provider = MiniMaxTTSProvider()
    results = {}

    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        text = shot.get("narration_text", "")
        if not text:
            continue

        job_id = await provider.submit_job({
            "text": text,
            "voice_id": voice_id,
            "speed": 0.9,
            "emotion": "happy",
        })
        status = await provider.poll_job(job_id)
        if status.result_data:
            path = os.path.join(output_dir, f"shot_{sn:02d}.mp3")
            with open(path, "wb") as f:
                f.write(status.result_data)
            results[sn] = path

    return results


# =============================================================================
# STAGE 7: ASSEMBLY — FFmpeg
# =============================================================================

def assemble_final_video(
    storyboard: dict,
    shot_videos: dict,   # {shot_number: video_path}
    tts_paths: dict,     # {shot_number: audio_path}
    output_dir: str,
    bgm_path: str = "data/bgm/romantic_sweet.mp3",
    bgm_volume: float = 0.20,
) -> str:
    """
    Full assembly pipeline:
    1. For each shot: align video to TTS audio duration
    2. Concatenate all aligned clips
    3. Overlay BGM with fade-in/fade-out

    Returns: path to final video
    """
    from app.services.ffmpeg_utils import (
        align_video_to_audio, concatenate_clips, overlay_bgm
    )
    import os

    aligned_dir = os.path.join(output_dir, "aligned")
    os.makedirs(aligned_dir, exist_ok=True)

    aligned_clips = []
    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        if sn not in shot_videos or sn not in tts_paths:
            continue

        aligned_path = os.path.join(aligned_dir, f"shot_{sn:02d}.mp4")
        ok = align_video_to_audio(shot_videos[sn], tts_paths[sn], aligned_path)
        if ok:
            aligned_clips.append(os.path.abspath(aligned_path))

    # Concatenate
    concat_path = os.path.abspath(os.path.join(output_dir, "concat_no_bgm.mp4"))
    concatenate_clips(aligned_clips, concat_path)

    # BGM overlay
    final_path = os.path.abspath(os.path.join(output_dir, "final_video.mp4"))
    overlay_bgm(concat_path, bgm_path, final_path, bgm_volume=bgm_volume)

    return final_path


# =============================================================================
# STAGE 8: QUALITY GATE
# =============================================================================

def run_quality_gate(
    final_video_path: str,
    storyboard: dict,
    shot_videos: dict,
    tts_paths: dict,
    duration_target: int = 40,
    output_dir: str = ".",
) -> dict:
    """
    Automated quality checks. Returns {passed: bool, issues: [str], metrics: {}}.

    Checks:
    1. Duration: final video within 60%-120% of target
    2. Freeze frames: TTS audio > video duration by >1s → freeze frame issue
    3. BGM presence: compare audio levels with/without BGM
    4. Completeness: all shots have both video and TTS
    5. Narration fit: no shot where TTS > video_duration + 1s
    6. File size: sanity check (not too small = corruption, not too huge)
    """
    from app.services.ffmpeg_utils import get_media_duration
    import subprocess, os

    issues = []
    metrics = {}

    # 1. Duration check
    final_duration = get_media_duration(final_video_path)
    metrics["final_duration"] = final_duration
    if final_duration < duration_target * 0.6:
        issues.append(f"Duration {final_duration:.0f}s < 60% of target {duration_target}s")
    if final_duration > duration_target * 1.3:
        issues.append(f"Duration {final_duration:.0f}s > 130% of target {duration_target}s")

    # 2. Freeze frame check per shot
    freeze_shots = []
    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        if sn in shot_videos and sn in tts_paths:
            vd = get_media_duration(shot_videos[sn])
            ad = get_media_duration(tts_paths[sn])
            if ad > vd + 1.0:
                freeze_shots.append(sn)
                issues.append(
                    f"Shot {sn}: freeze risk (TTS={ad:.1f}s > video={vd:.1f}s, "
                    f"gap={ad-vd:.1f}s)"
                )
    metrics["freeze_risk_shots"] = freeze_shots

    # 3. BGM check
    concat_path = os.path.join(output_dir, "concat_no_bgm.mp4")
    if os.path.exists(concat_path):
        sample_start = min(15, final_duration / 2)
        r_no_bgm = subprocess.run(
            ["ffmpeg", "-i", concat_path, "-ss", str(sample_start), "-t", "3",
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=10,
        )
        r_bgm = subprocess.run(
            ["ffmpeg", "-i", final_video_path, "-ss", str(sample_start), "-t", "3",
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=10,
        )
        vol_no = _extract_mean_volume(r_no_bgm.stderr)
        vol_with = _extract_mean_volume(r_bgm.stderr)
        diff = abs(vol_no - vol_with)
        metrics["bgm_volume_diff_db"] = diff
        if diff < 1.0:
            issues.append(f"BGM not audible (diff={diff:.1f}dB < 1.0dB)")

    # 4. Completeness
    total = len(storyboard["storyboards"])
    vid_count = len(shot_videos)
    tts_count = len(tts_paths)
    metrics["shots_total"] = total
    metrics["shots_with_video"] = vid_count
    metrics["shots_with_tts"] = tts_count
    if vid_count < total:
        issues.append(f"Missing videos: {vid_count}/{total}")
    if tts_count < total:
        issues.append(f"Missing TTS: {tts_count}/{total}")

    # 5. File size
    file_size_mb = os.path.getsize(final_video_path) / (1024 * 1024)
    metrics["file_size_mb"] = file_size_mb
    if file_size_mb < 0.5:
        issues.append(f"File too small ({file_size_mb:.1f}MB) — possible corruption")

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "metrics": metrics,
    }


def _extract_mean_volume(ffmpeg_stderr: str) -> float:
    """Extract mean_volume from ffmpeg volumedetect output."""
    for line in ffmpeg_stderr.split("\n"):
        if "mean_volume" in line:
            try:
                return float(line.split(":")[1].split("dB")[0].strip())
            except (IndexError, ValueError):
                pass
    return -91.0  # silence


# =============================================================================
# FULL PIPELINE ORCHESTRATION
# =============================================================================

def run_full_pipeline(
    source_text: str,
    duration_target: int = 40,
    voice_id: str = "female-shaonv",
    output_dir: str = "e2e_output/v9",
    bgm_path: str = "data/bgm/romantic_sweet.mp3",
) -> dict:
    """
    Execute the complete manga short-drama production pipeline.

    Returns: {
        "final_video": str,
        "storyboard": dict,
        "quality_gate": dict,
        "char_references": dict,
        "scene_backgrounds": dict,
    }
    """
    import os, asyncio

    # Create output directories
    for d in ["images", "scenes", "characters", "videos", "audio",
              "aligned", "frames"]:
        os.makedirs(f"{output_dir}/{d}", exist_ok=True)

    # --- Stage 1: Storyboard ---
    print(f"\n{'='*60}\n[Stage 1] Storyboard generation...")
    from vendor.qwen.client import chat_json
    prompts = build_storyboard_prompt_v9(source_text, duration_target)
    storyboard = chat_json(
        prompts["system_prompt"], prompts["user_prompt"],
        temperature=0.7, max_tokens=8192,
    )
    # Validate and trim narrations
    storyboard = validate_and_trim_narrations(storyboard)
    with open(f"{output_dir}/storyboard.json", "w") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)

    # --- Stage 2: Character references ---
    print(f"\n[Stage 2] Character reference images...")
    char_refs = generate_character_references(
        storyboard, f"{output_dir}/characters"
    )

    # --- Stage 3: Scene backgrounds ---
    print(f"\n[Stage 3] Scene background images...")
    scene_bgs = generate_scene_backgrounds(
        storyboard, f"{output_dir}/scenes"
    )

    # --- Stage 4: Shot first frames ---
    print(f"\n[Stage 4] Shot first-frame images...")
    profiles_map = {c["char_id"]: c for c in storyboard["character_profiles"]}
    shot_images = generate_shot_firstframes(
        storyboard, profiles_map, scene_bgs, f"{output_dir}/images"
    )

    # --- Stage 5: Video generation (Kling V3, sequential) ---
    print(f"\n[Stage 5] Video generation (Kling V3 I2V)...")
    shot_videos = generate_videos_with_continuity(
        storyboard, shot_images,
        f"{output_dir}/videos", f"{output_dir}/frames",
    )

    # --- Stage 6: TTS ---
    print(f"\n[Stage 6] TTS narration...")
    tts_paths = asyncio.run(
        generate_tts_all(storyboard, voice_id, f"{output_dir}/audio")
    )

    # --- Stage 7: Assembly ---
    print(f"\n[Stage 7] Assembly...")
    final_path = assemble_final_video(
        storyboard, shot_videos, tts_paths,
        output_dir, bgm_path,
    )

    # --- Stage 8: Quality gate ---
    print(f"\n[Stage 8] Quality gate...")
    qg = run_quality_gate(
        final_path, storyboard, shot_videos, tts_paths,
        duration_target, output_dir,
    )

    if qg["passed"]:
        print("  PASSED")
    else:
        print(f"  FAILED ({len(qg['issues'])} issues):")
        for issue in qg["issues"]:
            print(f"    - {issue}")

    return {
        "final_video": final_path,
        "storyboard": storyboard,
        "quality_gate": qg,
        "char_references": char_refs,
        "scene_backgrounds": scene_bgs,
    }


# =============================================================================
# KEY DIFFERENCES FROM v7/v8 (scripts/e2e_test.py)
# =============================================================================
#
# 1. VIDEO ENGINE: Jimeng I2V 3.0 → Kling V3 I2V
#    - Kling V3 supports 3-15s duration (vs fixed 5/10s)
#    - Kling V3 "pro" mode produces much better anime motion
#    - Kling V3 understands detailed English action prompts better
#    - Negative prompt support reduces artifacts
#
# 2. CHARACTER CONSISTENCY: added char_id + frozen appearance_en system
#    - LLM must assign char_id to each character
#    - Each shot declares characters_in_shot by char_id
#    - build_shot_firstframe_prompt() verifies and injects missing appearances
#    - Reference images generated for human review
#
# 3. STORYBOARD SCHEMA: richer structure
#    - characters_in_shot: explicit character declaration per shot
#    - shot_type: prevents abstract/object-only frames
#    - video_prompt: LLM now writes action-specific prompts (not generic)
#    - Narration length budget tied to duration via formula
#
# 4. NARRATION SYNC: pre-TTS validation
#    - calculate_max_narration_chars() prevents overlong narrations
#    - validate_and_trim_narrations() auto-shortens before TTS
#    - 10% duration buffer prevents edge-case freeze frames
#
# 5. QUALITY GATE: expanded checks
#    - Freeze frame detection per shot
#    - BGM presence verification
#    - Completeness check
#    - File size sanity
#
# 6. LAST-FRAME CONTINUITY: unchanged from v7, proven effective
#    - Sequential processing within same scene
#    - ffmpeg -sseof -0.1 to extract last frame
#    - Scene changes use fresh T2I image


# =============================================================================
# APPENDIX: KLING V3 API CALL FORMAT REFERENCE
# =============================================================================
#
# POST https://openapi.klingai.com/v1/videos/image2video
# Headers: Authorization: Bearer <JWT>
# Body:
# {
#     "model_name": "kling-v3",
#     "image": "<base64 or URL>",
#     "prompt": "specific motion description...",
#     "negative_prompt": "blurry, distorted...",
#     "mode": "pro",
#     "duration": "8",          # 3-15 seconds for v3
#     "aspect_ratio": "9:16",
#     "cfg_scale": 0.5
# }
#
# GET https://openapi.klingai.com/v1/videos/image2video/{task_id}
# Response.data.task_result.videos[0].url → download URL


# =============================================================================
# APPENDIX: JIMENG T2I OPTIMAL SETTINGS FOR ANIME
# =============================================================================
#
# Optimal Jimeng T2I 4.0 parameters for manga-style characters:
#   width=832, height=1472    (9:16 vertical, native resolution)
#   scale=0.5                 (prompt adherence — 0.5 is balanced)
#   seed=-1                   (random, or pin for reproducibility)
#
# Prompt pattern that works best:
#   "[quality], [style], [subject], [details], [background], [lighting]"
#   Quality: "masterpiece, best quality, highly detailed, 4K"
#   Style: "anime style, manga style, cel shading, vibrant colors"
#   Subject: full appearance description, specific and frozen
#   Background: simple for references, detailed for shots
#   Lighting: match scene mood
#
# Negative prompt (Jimeng T2I doesn't support it, but worth noting
# for future upgrades or if switching to a different T2I engine):
#   "low quality, blurry, deformed, extra limbs, bad anatomy"
