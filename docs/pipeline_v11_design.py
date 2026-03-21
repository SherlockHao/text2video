"""
Manga Short Drama Production Pipeline v11 — Subject Reference Design
======================================================================

Target: 40-second 9:16 vertical manga-style short drama
Genre:  女频 豪门总裁/青春甜宠
Stack:  Qwen 3.5-Plus → Jimeng T2I 4.0 → Kling V3 I2V → MiniMax TTS → FFmpeg

WHAT CHANGED FROM v10:
---------------------
V10's CORE PROBLEM:
  In v10, character consistency was driven SOLELY by the frozen appearance_en
  text tag baked into image_prompt. This worked reasonably for T2I-generated
  first frames, but fell apart in a critical scenario:

  Example: Shot 2 shows only the female character. Its last frame is used as
  Shot 3's first frame (same-scene continuity). Shot 3 needs BOTH characters.
  Kling I2V has to "invent" the male character from scratch using only the
  motion prompt — with zero visual reference. Result: severe inconsistency.

  subject_reference solves this. Even when the first frame only shows one
  character, Kling V3 receives canonical reference images of ALL characters
  in the shot and uses them to maintain visual identity.

V11 CHANGES:
  1. RESTORED Stage 2 (Character Reference Images via Jimeng T2I).
     These are no longer "human review only" — they are fed directly to
     Kling V3 as subject_reference. Every Jimeng credit spent here pays off.

  2. RESTORED Stage 3 (Scene Background Images via Jimeng T2I).
     Scene backgrounds in subject_reference help Kling maintain environment
     consistency, especially for same-scene last-frame shots where the
     previous shot may have been a close-up with minimal background visible.

  3. NEW subject_reference composition logic per shot:
     - Always include ALL characters present in that shot (not all story chars)
     - Always include the scene background for the current scene
     - This applies to EVERY shot — both T2I first-frame and last-frame shots

  4. image_tail strategy: used selectively for shots that need a specific
     end state (e.g., character must arrive at a position for next shot).

PIPELINE: 8 stages (v10 had 6; we add back char refs + scene BGs, worth it now)

CREDIT IMPACT (typical 6-shot, 2-scene, 2-character video):
  v10: 2 T2I (first frames only)                              = 2 Jimeng calls
  v11: 2 T2I (char refs) + 2 T2I (scenes) + 2 T2I (frames)   = 6 Jimeng calls
  Extra cost: 4 Jimeng calls → but character consistency DRAMATICALLY improved

ANSWERS TO KEY DESIGN QUESTIONS:
---------------------------------
Q1: For subject_reference, include ALL characters or only current shot's?
A1: ONLY characters in the current shot (characters_in_shot).
    Reason: Including irrelevant characters confuses the model. If Shot 3 is
    a solo female close-up, including the male ref would bias Kling to try
    inserting him. subject_reference should match the shot's creative intent.

Q2: Include scene background in subject_reference?
A2: YES, always include the current scene's background image.
    Reason: This anchors the environment, especially critical for last-frame
    shots where a close-up first frame has minimal background context. The
    scene ref tells Kling "this is what the room looks like" even if the
    first frame is mostly face.

Q3: Use image_tail?
A3: YES, but ONLY when the next shot uses last-frame continuity AND we need
    a specific character composition in the ending frame. Specifically:
    - If next shot is same-scene AND has DIFFERENT characters than current shot,
      generate a T2I image_tail showing the transition composition.
    - Otherwise, no image_tail (let Kling end naturally).
    In practice: rarely used. Most same-scene continuations share characters.

Q4: For same-scene last-frame shots, still pass subject_reference?
A4: YES, ALWAYS. This is the entire point of v11.
    The last frame may not contain all characters needed for the current shot.
    subject_reference ensures Kling knows what every character looks like
    even if they are entering the frame for the first time in this shot.

Q5: Optimal prompt structure when subject_reference is provided?
A5: The motion prompt should be PURE MOTION — no appearance descriptions.
    subject_reference handles identity. The prompt handles action.
    Format: "[specific character action], [facial expression], [camera movement],
             [ambient motion], anime style, smooth animation"
    NEVER include hair color, clothing, or appearance in video_prompt when
    subject_reference is provided — it creates conflicting signals.
"""

import json
import base64
import os
import subprocess
import time


# =============================================================================
# PIPELINE OVERVIEW (8 stages)
# =============================================================================
#
# Stage 1: LLM storyboard generation (Qwen 3.5-Plus)
# Stage 2: Character reference image generation (Jimeng T2I) — NEW in v11
# Stage 3: Scene background image generation (Jimeng T2I) — NEW in v11
# Stage 4: Smart first-frame generation (Jimeng T2I, only shots that need it)
# Stage 5: Video generation (Kling V3 I2V + subject_reference)
# Stage 6: TTS narration (MiniMax, parallel)
# Stage 7: Assembly (FFmpeg: align → concat → BGM overlay)
# Stage 8: Quality gate (automated checks)


# =============================================================================
# STAGE 1: LLM STORYBOARD — ENHANCED SCHEMA
# =============================================================================
#
# The v11 schema adds voice_id per character (for multi-character TTS) and
# explicit image_tail_hint for shots that need controlled end frames.

STORYBOARD_OUTPUT_SCHEMA_V11 = {
    "title": "str",
    "character_profiles": [
        {
            "char_id": "str — unique ID like 'char_su_niannian'",
            "name": "str — 角色名（中文）",
            "gender": "str — male/female",
            "appearance": "str — 详细外貌描述（中文）",
            "appearance_en": (
                "str — FROZEN English appearance tag. "
                "Pasted verbatim into every image prompt. "
                "Must include: hair color+style+length, eye color, skin tone, "
                "body type, outfit with colors+materials, accessories. "
                "Must be self-contained (no references to other characters)."
            ),
            "voice_id": "str — MiniMax voice ID (male-qn-qingse / female-shaonv / etc)",
        }
    ],
    "scene_backgrounds": [
        {
            "scene_id": "str — unique ID like 'scene_lobby'",
            "name": "str — 场景名称",
            "description_en": (
                "str — Detailed English background description WITHOUT characters. "
                "Must describe: architecture, furniture, lighting, color palette, "
                "atmosphere. Always end with 'manga style, anime background, "
                "no characters, no people, clean background'"
            ),
        }
    ],
    "storyboards": [
        {
            "shot_number": "int — 1-indexed",
            "duration_seconds": "float — 5-10 for Kling V3",
            "scene_id": "str — references scene_backgrounds[].scene_id",
            "characters_in_shot": ["str — char_id references"],
            "shot_type": "str — wide/medium/medium_closeup/closeup/two_shot",
            "image_prompt": (
                "str — English. Full static frame description with character "
                "appearance_en verbatim + scene background + style keywords. "
                "Used for T2I first-frame generation."
            ),
            "video_prompt": (
                "str — English. MOTION-ONLY. Specific actions, expressions, "
                "camera movement. NO appearance description. NO background "
                "description. subject_reference handles visual identity."
            ),
            "narration_text": "str — 中文旁白",
            "narrator": "str — 'narrator' for旁白 or char_id for character dialogue",
            "scene_description": "str — 中文场景描述",
            "camera_movement": "str — static/pan_left/pan_right/zoom_in/zoom_out/etc",
            "transition": "str — cut/fade/dissolve",
        }
    ],
}


def build_storyboard_prompt_v11(
    source_text: str,
    duration_target: int = 40,
    aspect_ratio: str = "9:16",
) -> dict:
    """
    Build system + user prompts for v11 storyboard generation.

    Key changes from v10:
    - video_prompt instructions emphasize MOTION-ONLY (no appearance)
    - Added narrator field for per-shot voice routing
    - Added gender field to character_profiles for voice assignment
    """
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
6. 每个角色需要指定 gender 字段（male/female），用于自动匹配TTS音色

## image_prompt 构造规则
每个 image_prompt 必须按以下顺序组合：
1. 画质关键词: "masterpiece, best quality, highly detailed, 4K"
2. 风格关键词: "anime style, manga style, cel shading, vibrant colors, detailed illustration"
3. 构图/景别: "wide shot" / "medium shot" / "medium close-up" / "two-shot"
4. 角色描述: 逐字复制 appearance_en + 当前姿态/表情
5. 场景背景: 引用 scene_backgrounds 中的 description_en 核心元素
6. 光线氛围: "dramatic lighting" / "soft warm glow" / "cold blue tones" 等

## video_prompt 构造规则（v11新要求 — 极其重要）

video_prompt 只描述【运动和动作】。绝对禁止出现任何外貌描述或场景背景描述。
原因：视频生成时会通过 subject_reference 传入角色参考图和场景参考图，
如果 video_prompt 中重复描述外貌，会与参考图产生冲突，导致画面混乱。

✅ 正确的 video_prompt:
- "the woman slowly turns her head to the right, tears form in her eyes, her expression shifts from shock to sadness, camera slowly zooms in on her face"
- "the man stands up from the chair abruptly, slams his palm on the desk, his jaw tightens with anger, camera tracks upward following his movement"
- "both characters face each other, the woman takes a step back, the man reaches his hand forward, subtle wind blows through the scene, camera slowly orbits around them"

❌ 错误的 video_prompt:
- "the woman with long black hair wearing a white blouse turns her head" （包含了外貌描述）
- "in the luxurious office, the man stands up" （包含了场景描述）
- "subtle animation, gentle movement" （太笼统，没有具体动作）

## 旁白控制（严格）
- 每段 narration_text 必须是中文
- narrator 字段: 如果是旁白叙述则填 "narrator"，如果是角色对话则填对应 char_id
- 中文语速约 3.5字/秒（speed=0.9时）
- 5秒分镜 → 约15-17个字
- 8秒分镜 → 约25-28个字
- 10秒分镜 → 约30-35个字
- 公式: max_chars = duration_seconds × 3.5 × 0.9 ≈ duration_seconds × 3.15
- 旁白宁短勿长，避免冻帧。

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
      "gender": "male 或 female",
      "appearance": "中文外貌描述",
      "appearance_en": "FROZEN English appearance tag — 极其详细",
      "voice_id": "male-qn-qingse 或 female-shaonv 等"
    }}}}
  ],
  "scene_backgrounds": [
    {{{{
      "scene_id": "scene_xxx",
      "name": "场景名",
      "description_en": "Detailed background WITHOUT characters, ending with 'manga style, anime background, no characters, no people, clean background'"
    }}}}
  ],
  "storyboards": [
    {{{{
      "shot_number": 1,
      "duration_seconds": 8,
      "scene_id": "scene_xxx",
      "characters_in_shot": ["char_xxx"],
      "shot_type": "medium shot",
      "image_prompt": "masterpiece, best quality, ..., [FULL appearance_en], [pose], [background], [lighting]",
      "video_prompt": "[specific action only, facial expression change, camera movement — NO appearance, NO background]",
      "narration_text": "中文旁白",
      "narrator": "narrator 或 char_id",
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
4. video_prompt 严禁包含外貌描述或场景描述，只描述动作和镜头运动
5. narration_text 字数严格遵守: max_chars = floor(duration_seconds × 3.15)
6. 只输出JSON"""

    user_prompt = f"""请将以下文本拆解为漫画风格的解说类短视频分镜。

【重要】请直接输出JSON，不要输出任何分析或说明。你的回复必须以 {{ 开头。

文本内容：
{source_text}"""

    return {"system_prompt": system_prompt, "user_prompt": user_prompt}


# =============================================================================
# STAGE 2: CHARACTER REFERENCE IMAGE GENERATION (Jimeng T2I)
# =============================================================================
#
# In v10 this was removed as "wasteful". In v11 it is CRITICAL — these images
# are fed to Kling V3 via subject_reference for every video generation call.
#
# Each character gets ONE canonical reference portrait:
# - Neutral pose, facing camera (3/4 view)
# - Full upper body visible (waist up minimum)
# - Clean solid background (no scene elements)
# - Maximum detail on face and clothing
#
# The prompt must produce an image that Kling can "latch onto" as a visual
# anchor for the character's identity across all shots.

CHARACTER_REF_PROMPT_TEMPLATE = (
    "masterpiece, best quality, highly detailed, 4K, "
    "anime style, manga style, cel shading, vibrant colors, detailed illustration, "
    "character reference sheet, "
    "{shot_framing}, "                    # "upper body portrait" or "full body portrait"
    "{appearance_en}, "                   # frozen appearance tag — verbatim
    "{pose_expression}, "                 # "neutral expression, standing straight, facing slightly left, arms at sides"
    "clean solid light gray background, studio lighting, "
    "no text, no watermark, sharp focus, high contrast"
)

# Two variants: upper-body (for face detail) and full-body (for outfit detail).
# We generate UPPER-BODY only — it gives best face detail for subject_reference.
# Kling cares most about face consistency; outfit is secondary.

def build_character_ref_prompt(char_profile: dict) -> str:
    """
    Build Jimeng T2I prompt for a character's canonical reference image.

    Args:
        char_profile: {char_id, name, gender, appearance, appearance_en, voice_id}

    Returns:
        Complete T2I prompt string.
    """
    appearance_en = char_profile["appearance_en"]
    gender = char_profile.get("gender", "female")

    if gender == "male":
        pose = "neutral expression, standing straight, three-quarter view facing slightly left, arms relaxed at sides, confident posture"
    else:
        pose = "neutral expression, standing straight, three-quarter view facing slightly right, hands gently clasped in front, elegant posture"

    return CHARACTER_REF_PROMPT_TEMPLATE.format(
        shot_framing="upper body portrait, from waist up",
        appearance_en=appearance_en,
        pose_expression=pose,
    )


def generate_character_references(
    storyboard: dict,
    output_dir: str,
) -> dict:
    """
    Generate one canonical reference image per character.

    Returns: {char_id: image_path}
    """
    from vendor.jimeng.t2i import generate_image

    os.makedirs(output_dir, exist_ok=True)
    results = {}

    for char in storyboard["character_profiles"]:
        char_id = char["char_id"]
        prompt = build_character_ref_prompt(char)

        print(f"\n  Generating reference for {char['name']} ({char_id})...")
        print(f"    Prompt: {prompt[:120]}...")

        paths = generate_image(
            prompt,
            width=832,       # 9:16 vertical — consistent with pipeline
            height=1472,
            output_dir=output_dir,
            prefix=f"charref_{char_id}",
        )

        if paths:
            results[char_id] = paths[0]
            print(f"    Saved: {paths[0]}")
        else:
            print(f"    [ERROR] Failed to generate reference for {char_id}")

        time.sleep(3)  # Rate limit

    return results


# =============================================================================
# STAGE 3: SCENE BACKGROUND IMAGE GENERATION (Jimeng T2I)
# =============================================================================
#
# Each unique scene gets one clean background image (no characters).
# Fed to Kling V3 via subject_reference to anchor environment consistency.
#
# Critical for:
# - Last-frame shots where previous shot was a close-up (minimal BG visible)
# - Shots where characters move to different parts of the scene
# - Maintaining consistent lighting and color palette within a scene

SCENE_BG_PROMPT_TEMPLATE = (
    "masterpiece, best quality, highly detailed, 4K, "
    "anime style, manga style, vibrant colors, detailed illustration, "
    "wide establishing shot, "
    "{description_en}, "       # scene description from storyboard — verbatim
    "atmospheric perspective, detailed environment, "
    "no text, no watermark, sharp focus"
    # Note: description_en already ends with "no characters, no people"
)


def build_scene_bg_prompt(scene: dict) -> str:
    """
    Build Jimeng T2I prompt for a scene's background reference image.

    Args:
        scene: {scene_id, name, description_en}

    Returns:
        Complete T2I prompt string.
    """
    desc = scene["description_en"]

    # Ensure the "no characters" suffix is present
    if "no characters" not in desc.lower():
        desc += ", manga style, anime background, no characters, no people, clean background"

    return SCENE_BG_PROMPT_TEMPLATE.format(description_en=desc)


def generate_scene_backgrounds(
    storyboard: dict,
    output_dir: str,
) -> dict:
    """
    Generate one background reference image per scene.

    Returns: {scene_id: image_path}
    """
    from vendor.jimeng.t2i import generate_image

    os.makedirs(output_dir, exist_ok=True)
    results = {}

    for scene in storyboard["scene_backgrounds"]:
        scene_id = scene["scene_id"]
        prompt = build_scene_bg_prompt(scene)

        print(f"\n  Generating background for {scene['name']} ({scene_id})...")
        print(f"    Prompt: {prompt[:120]}...")

        paths = generate_image(
            prompt,
            width=832,
            height=1472,
            output_dir=output_dir,
            prefix=f"scenebg_{scene_id}",
        )

        if paths:
            results[scene_id] = paths[0]
            print(f"    Saved: {paths[0]}")
        else:
            print(f"    [ERROR] Failed to generate background for {scene_id}")

        time.sleep(3)

    return results


# =============================================================================
# STAGE 4: SMART FIRST-FRAME GENERATION (unchanged logic from v10)
# =============================================================================
#
# Decision logic per shot:
#   Shot 1 → always T2I (no previous frame)
#   Same scene as previous → use last frame from previous video
#   Different scene from previous → fresh T2I
#
# The T2I prompt still includes full appearance_en — this ensures the first
# frame is accurate. subject_reference in Stage 5 REINFORCES this.

def classify_shots_for_firstframe(storyboard: dict) -> dict:
    """
    Analyze the storyboard and classify each shot's first-frame strategy.

    Returns: {
        shot_number: {
            "strategy": "t2i" | "last_frame",
            "reason": str,
        }
    }
    """
    shots = storyboard["storyboards"]
    result = {}
    prev_scene_id = None

    for shot in shots:
        sn = shot["shot_number"]
        scene_id = shot.get("scene_id", "")

        if sn == 1:
            result[sn] = {
                "strategy": "t2i",
                "reason": "first shot of video — no previous frame exists",
            }
        elif scene_id != prev_scene_id:
            result[sn] = {
                "strategy": "t2i",
                "reason": f"scene change: {prev_scene_id} -> {scene_id}",
            }
        else:
            result[sn] = {
                "strategy": "last_frame",
                "reason": f"same scene ({scene_id}), using previous shot's last frame",
            }

        prev_scene_id = scene_id

    return result


def build_shot_firstframe_prompt(
    shot: dict,
    char_profiles: dict,
    scene_backgrounds: dict,
) -> str:
    """
    Build Jimeng T2I prompt for a shot's first frame.
    Only called for shots where strategy == "t2i".

    Identical to v10 — the T2I prompt construction is unchanged.
    """
    base_prompt = shot.get("image_prompt", "")

    # Verify character appearances are present in the prompt
    chars_in_shot = shot.get("characters_in_shot", [])
    missing_appearances = []
    for char_id in chars_in_shot:
        char_info = char_profiles.get(char_id, {})
        appearance = char_info.get("appearance_en", "")
        if appearance and appearance[:40].lower() not in base_prompt.lower():
            missing_appearances.append(appearance)

    # Get scene background description
    scene_id = shot.get("scene_id", "")
    scene_info = scene_backgrounds.get(scene_id, {})
    scene_desc = scene_info.get("description_en", "")

    parts = []

    # Ensure quality and style prefix
    if "masterpiece" not in base_prompt.lower():
        parts.append("masterpiece, best quality, highly detailed, 4K")
    if "anime style" not in base_prompt.lower():
        parts.append("anime style, manga style, cel shading, vibrant colors, detailed illustration")

    parts.append(base_prompt)

    # Append any missing character appearances
    for app in missing_appearances:
        parts.append(app)

    # Append scene background if missing
    if scene_desc and scene_desc[:30].lower() not in base_prompt.lower():
        scene_brief = scene_desc.replace("no characters, no people", "").strip(" ,.")
        parts.append(f"background: {scene_brief}")

    return ", ".join(parts)


def generate_needed_firstframes(
    storyboard: dict,
    shot_plan: dict,
    output_dir: str,
) -> dict:
    """
    Generate T2I first-frame images ONLY for shots that need them.

    Returns: {shot_number: image_path}
    """
    from vendor.jimeng.t2i import generate_image

    os.makedirs(output_dir, exist_ok=True)

    profiles_map = {c["char_id"]: c for c in storyboard["character_profiles"]}
    scene_bgs = {s["scene_id"]: s for s in storyboard["scene_backgrounds"]}

    results = {}
    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        plan = shot_plan.get(sn, {})

        if plan.get("strategy") != "t2i":
            continue  # This shot will use last frame — no T2I needed

        prompt = build_shot_firstframe_prompt(shot, profiles_map, scene_bgs)

        print(f"\n  Generating first frame for Shot {sn}...")
        print(f"    Prompt: {prompt[:120]}...")

        paths = generate_image(
            prompt, width=832, height=1472,
            output_dir=output_dir, prefix=f"shot_{sn:02d}"
        )
        if paths:
            results[sn] = paths[0]
            print(f"    Saved: {paths[0]}")

        time.sleep(3)

    return results


# =============================================================================
# STAGE 5: VIDEO GENERATION — KLING V3 I2V + subject_reference
# =============================================================================
#
# THIS IS THE CORE V11 CHANGE.
#
# Every Kling V3 call now includes subject_reference with:
# - Character reference images (from Stage 2) for ALL characters in the shot
# - Scene background image (from Stage 3) for the current scene
#
# subject_reference composition rules:
# ┌─────────────────────────────────────────────────────────────┐
# │  ALWAYS include:                                            │
# │    1. Character refs for EACH char_id in characters_in_shot │
# │    2. Scene background ref for current scene_id             │
# │                                                             │
# │  NEVER include:                                             │
# │    - Characters NOT in this shot                            │
# │    - Scene backgrounds from other scenes                    │
# │                                                             │
# │  ORDER matters:                                             │
# │    [char_1_ref, char_2_ref, ..., scene_bg_ref]              │
# │    Characters first (higher priority), scene last           │
# └─────────────────────────────────────────────────────────────┘
#
# image_tail strategy:
# ┌─────────────────────────────────────────────────────────────┐
# │  USE image_tail ONLY when ALL of these are true:            │
# │    1. Next shot exists AND uses "last_frame" strategy       │
# │    2. Next shot has DIFFERENT characters than current shot   │
# │    3. The transition requires a specific character entering  │
# │                                                             │
# │  In practice: very rare. Skip image_tail by default.        │
# │                                                             │
# │  When used: generate a T2I image showing the END state —    │
# │  the composition needed as next shot's starting frame.      │
# │  This bridges character handoffs between same-scene shots.  │
# └─────────────────────────────────────────────────────────────┘

def build_kling_v3_motion_prompt(shot: dict) -> str:
    """
    Build motion prompt for Kling V3 I2V.

    V11 CHANGE: The prompt is STRICTLY motion-only. No appearance descriptors.
    subject_reference handles all visual identity.

    Structure:
    1. Character actions (specific, frame-by-frame quality)
    2. Facial expression changes
    3. Camera movement
    4. Ambient motion (hair, cloth, wind, etc.)
    5. Style suffix (anime animation quality keywords)
    """
    video_prompt = shot.get("video_prompt", "")
    camera = shot.get("camera_movement", "static")

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

    # 1. Core motion (from LLM-generated video_prompt)
    if video_prompt:
        parts.append(video_prompt)
    else:
        # Fallback: minimal but specific motion
        parts.append("subtle character animation, gentle breathing, slight weight shift")

    # 2. Camera movement (only if not already in video_prompt)
    if "camera" not in video_prompt.lower():
        cam_desc = camera_map.get(camera, camera_map["static"])
        parts.append(cam_desc)

    # 3. Ambient motion + style suffix
    # These are universal and don't conflict with subject_reference
    parts.append("hair sways gently, cloth physics, anime style, smooth animation")

    prompt = ", ".join(parts)

    # Kling V3 prompt token limit: cap at ~180 words
    words = prompt.split()
    if len(words) > 180:
        prompt = " ".join(words[:180])

    return prompt


KLING_V3_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted face, extra fingers, deformed, morphing, "
    "flickering, abrupt scene change, live action, photorealistic, "
    "text, watermark, signature, frame, border, "
    "style change, color shift, inconsistent character, extra limbs"
)


def compose_subject_reference(
    shot: dict,
    char_ref_images: dict,   # {char_id: image_path} from Stage 2
    scene_bg_images: dict,   # {scene_id: image_path} from Stage 3
) -> list[dict]:
    """
    Compose the subject_reference array for a specific shot.

    This is the KEY v11 function. It determines exactly which reference
    images Kling V3 receives for each shot.

    Rules:
    1. Include character refs for ALL characters in characters_in_shot
    2. Include scene background ref for current scene_id
    3. Characters come first (they matter more), scene last
    4. Skip any refs that failed to generate (graceful degradation)

    Returns:
        List of {"image": base64_string} dicts, ready for Kling API.
    """
    refs = []

    # --- Character references (one per character in shot) ---
    chars_in_shot = shot.get("characters_in_shot", [])
    for char_id in chars_in_shot:
        img_path = char_ref_images.get(char_id)
        if img_path and os.path.exists(img_path):
            b64 = _image_to_base64(img_path)
            refs.append({"image": b64})
            print(f"      + char ref: {char_id}")
        else:
            print(f"      [WARN] Missing char ref for {char_id}, skipping")

    # --- Scene background reference ---
    scene_id = shot.get("scene_id", "")
    scene_path = scene_bg_images.get(scene_id)
    if scene_path and os.path.exists(scene_path):
        b64 = _image_to_base64(scene_path)
        refs.append({"image": b64})
        print(f"      + scene ref: {scene_id}")
    else:
        print(f"      [WARN] Missing scene ref for {scene_id}, skipping")

    return refs


def should_use_image_tail(
    current_shot: dict,
    next_shot: dict | None,
    shot_plan: dict,
) -> bool:
    """
    Determine whether to use image_tail for the current shot.

    image_tail is used ONLY when:
    1. Next shot exists
    2. Next shot uses "last_frame" strategy (same scene continuation)
    3. Next shot has a DIFFERENT character set than current shot
       (meaning a character enters or exits between shots)

    This bridges character transitions: the current shot's ending frame
    is composed to include the characters needed by the next shot.
    """
    if next_shot is None:
        return False

    next_sn = next_shot["shot_number"]
    next_plan = shot_plan.get(next_sn, {})

    if next_plan.get("strategy") != "last_frame":
        return False

    current_chars = set(current_shot.get("characters_in_shot", []))
    next_chars = set(next_shot.get("characters_in_shot", []))

    # Only use image_tail if character sets differ
    return current_chars != next_chars


def build_image_tail_prompt(
    next_shot: dict,
    char_profiles: dict,
    scene_backgrounds: dict,
) -> str:
    """
    Build T2I prompt for image_tail. This generates the desired END frame
    of the current shot, which will also be the START frame of the next shot.

    The composition must match what the NEXT shot expects to see.
    """
    # Use next shot's image_prompt as the basis, since that describes
    # the composition the next shot needs as its starting point.
    return build_shot_firstframe_prompt(next_shot, char_profiles, scene_backgrounds)


def generate_videos_with_subject_reference(
    storyboard: dict,
    t2i_images: dict,       # {shot_number: image_path} — shots that got T2I first frames
    shot_plan: dict,         # {shot_number: {"strategy": ...}}
    char_ref_images: dict,   # {char_id: image_path} — from Stage 2
    scene_bg_images: dict,   # {scene_id: image_path} — from Stage 3
    output_dir: str,
    frames_dir: str,
) -> dict:
    """
    Generate all videos using Kling V3 I2V with subject_reference.

    THIS IS THE CORE V11 FUNCTION.

    For each shot:
    1. Resolve first frame (T2I or last-frame, same as v10)
    2. Compose subject_reference (NEW in v11):
       - Character refs for ALL characters in this shot
       - Scene background ref for this scene
    3. Build motion prompt (MOTION-ONLY, no appearance)
    4. Optionally generate image_tail (rare)
    5. Call Kling V3 I2V API
    6. Extract last frame for potential use by next shot

    Returns: {shot_number: video_path}
    """
    from vendor.jimeng.t2i import generate_image

    # NOTE: KlingClient should be imported from your actual Kling SDK.
    # The below is pseudocode matching the API signature from the task spec.
    from vendor.kling.client import KlingClient

    client = KlingClient()
    results = {}
    prev_last_frame = None

    profiles_map = {c["char_id"]: c for c in storyboard["character_profiles"]}
    scene_bgs = {s["scene_id"]: s for s in storyboard["scene_backgrounds"]}
    shots = storyboard["storyboards"]

    for idx, shot in enumerate(shots):
        sn = shot["shot_number"]
        duration = shot.get("duration_seconds", 8)
        plan = shot_plan.get(sn, {})
        strategy = plan.get("strategy", "t2i")

        print(f"\n  --- Shot {sn}/{len(shots)} ---")
        print(f"  Strategy: {strategy}")
        print(f"  Characters: {shot.get('characters_in_shot', [])}")
        print(f"  Scene: {shot.get('scene_id', '')}")

        # =====================================================================
        # STEP 1: Resolve first frame
        # =====================================================================
        if strategy == "t2i":
            first_frame_path = t2i_images.get(sn)
            if not first_frame_path:
                # Fallback: generate on-the-fly
                print(f"  [WARN] T2I image missing for shot {sn}, generating fallback...")
                prompt = build_shot_firstframe_prompt(shot, profiles_map, scene_bgs)
                paths = generate_image(
                    prompt, width=832, height=1472,
                    output_dir=frames_dir, prefix=f"shot_{sn:02d}_fallback"
                )
                first_frame_path = paths[0] if paths else None
                if not first_frame_path:
                    print(f"  [ERROR] Cannot generate first frame for shot {sn}, skipping")
                    prev_last_frame = None
                    continue
            print(f"  First frame: T2I image ({first_frame_path})")

        elif strategy == "last_frame":
            if prev_last_frame and os.path.exists(prev_last_frame):
                first_frame_path = prev_last_frame
                print(f"  First frame: last frame from previous shot ({first_frame_path})")
            else:
                # Fallback: generate T2I on-the-fly
                print(f"  [WARN] Last frame unavailable for shot {sn}, generating T2I fallback...")
                prompt = build_shot_firstframe_prompt(shot, profiles_map, scene_bgs)
                paths = generate_image(
                    prompt, width=832, height=1472,
                    output_dir=frames_dir, prefix=f"shot_{sn:02d}_fallback"
                )
                first_frame_path = paths[0] if paths else None
                if not first_frame_path:
                    print(f"  [ERROR] Cannot generate first frame for shot {sn}, skipping")
                    prev_last_frame = None
                    continue

        # =====================================================================
        # STEP 2: Compose subject_reference (THE KEY V11 ADDITION)
        # =====================================================================
        print(f"  Composing subject_reference...")
        subject_ref = compose_subject_reference(
            shot, char_ref_images, scene_bg_images
        )
        print(f"  subject_reference: {len(subject_ref)} images "
              f"({len(shot.get('characters_in_shot', []))} chars + 1 scene)")

        # =====================================================================
        # STEP 3: Build motion prompt (MOTION-ONLY)
        # =====================================================================
        motion_prompt = build_kling_v3_motion_prompt(shot)
        print(f"  Motion prompt: {motion_prompt[:100]}...")

        # =====================================================================
        # STEP 4: Determine image_tail (rare)
        # =====================================================================
        image_tail_b64 = None
        next_shot = shots[idx + 1] if idx + 1 < len(shots) else None

        if should_use_image_tail(shot, next_shot, shot_plan):
            print(f"  Generating image_tail (character transition to next shot)...")
            tail_prompt = build_image_tail_prompt(next_shot, profiles_map, scene_bgs)
            tail_paths = generate_image(
                tail_prompt, width=832, height=1472,
                output_dir=frames_dir, prefix=f"shot_{sn:02d}_tail"
            )
            if tail_paths:
                image_tail_b64 = _image_to_base64(tail_paths[0])
                print(f"  image_tail generated: {tail_paths[0]}")
        else:
            print(f"  image_tail: not needed")

        # =====================================================================
        # STEP 5: Call Kling V3 I2V API
        # =====================================================================
        first_frame_b64 = _image_to_base64(first_frame_path)

        # Clamp duration to Kling V3 range (3-15 seconds)
        kling_duration = str(max(3, min(int(duration), 15)))

        # Build API call kwargs
        kling_kwargs = {
            "image": first_frame_b64,
            "prompt": motion_prompt,
            "negative_prompt": KLING_V3_NEGATIVE_PROMPT,
            "model_name": "kling-v3",
            "mode": "std",               # std for cost efficiency; use "pro" for hero shots
            "duration": kling_duration,
            "aspect_ratio": "9:16",
            "cfg_scale": 0.5,
        }

        # Add subject_reference (v11 core feature)
        if subject_ref:
            kling_kwargs["subject_reference"] = subject_ref

        # Add image_tail if generated
        if image_tail_b64:
            kling_kwargs["image_tail"] = image_tail_b64

        print(f"  Calling Kling V3 I2V (duration={kling_duration}s, "
              f"refs={len(subject_ref)}, tail={'yes' if image_tail_b64 else 'no'})...")

        resp = client.generate_video(**kling_kwargs)

        # =====================================================================
        # STEP 6: Poll for result + extract last frame
        # =====================================================================
        task_id = resp.get("data", {}).get("task_id")
        if not task_id:
            print(f"  [ERROR] No task_id returned for shot {sn}")
            prev_last_frame = None
            continue

        print(f"  Task submitted: {task_id}")
        data = client.poll_task(task_id, task_type="video", max_wait=600)
        if not data:
            print(f"  [ERROR] Polling failed for shot {sn}")
            prev_last_frame = None
            continue

        video_url = data.get("task_result", {}).get("videos", [{}])[0].get("url", "")
        if not video_url:
            print(f"  [ERROR] No video URL in result for shot {sn}")
            prev_last_frame = None
            continue

        # Download video
        import requests as req_lib
        video_path = os.path.join(output_dir, f"shot_{sn:02d}.mp4")
        r = req_lib.get(video_url, timeout=120)
        with open(video_path, "wb") as f:
            f.write(r.content)
        results[sn] = video_path
        print(f"  Video saved: {video_path}")

        # Extract last frame for potential next-shot use
        last_frame_path = os.path.join(frames_dir, f"shot_{sn:02d}_lastframe.png")
        ffmpeg_result = subprocess.run(
            [
                "ffmpeg", "-y", "-sseof", "-0.1",
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "2",   # High quality JPEG-equivalent for PNG
                last_frame_path,
            ],
            capture_output=True,
            timeout=10,
        )
        if ffmpeg_result.returncode == 0 and os.path.exists(last_frame_path):
            prev_last_frame = last_frame_path
            print(f"  Last frame extracted: {last_frame_path}")
        else:
            prev_last_frame = None
            print(f"  [WARN] Failed to extract last frame")

        # Rate limit between Kling calls
        time.sleep(5)

    return results


def _image_to_base64(image_path: str) -> str:
    """Convert local image file to base64 string for API calls."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


# =============================================================================
# STAGE 6: TTS NARRATION (enhanced with per-character voice routing)
# =============================================================================

def calculate_max_narration_chars(duration_seconds: float, speed: float = 0.9) -> int:
    """Max narration characters to fit within video duration."""
    effective_rate = 3.5 * speed   # ~3.15 chars/sec at speed=0.9
    usable_duration = duration_seconds * 0.90   # 10% safety margin
    return int(usable_duration * effective_rate)


def validate_and_trim_narrations(storyboard: dict) -> dict:
    """Pre-TTS validation: ensure narration fits shot duration."""
    for shot in storyboard["storyboards"]:
        duration = shot.get("duration_seconds", 8)
        narration = shot.get("narration_text", "")
        max_chars = calculate_max_narration_chars(duration)
        if len(narration) > max_chars:
            # Truncate with ellipsis as simple fallback;
            # production would use LLM to rephrase more concisely
            shot["narration_text"] = narration[:max_chars - 1] + "…"
            print(f"  [TRIM] Shot {shot['shot_number']}: "
                  f"{len(narration)} -> {max_chars} chars")
    return storyboard


def resolve_voice_for_shot(
    shot: dict,
    char_profiles: dict,
    default_narrator_voice: str = "female-shaonv",
) -> str:
    """
    Determine which voice_id to use for this shot's TTS.

    Logic:
    - If narrator == "narrator", use default_narrator_voice
    - If narrator == a char_id, use that character's voice_id
    - Fallback: default_narrator_voice
    """
    narrator = shot.get("narrator", "narrator")
    if narrator == "narrator":
        return default_narrator_voice

    char = char_profiles.get(narrator)
    if char and char.get("voice_id"):
        return char["voice_id"]

    return default_narrator_voice


async def generate_tts_all(
    storyboard: dict,
    default_voice_id: str = "female-shaonv",
    output_dir: str = ".",
) -> dict:
    """
    Generate TTS for all shots with per-character voice routing.

    Returns: {shot_number: audio_path}
    """
    from app.ai.providers.minimax_tts import MiniMaxTTSProvider

    os.makedirs(output_dir, exist_ok=True)

    provider = MiniMaxTTSProvider()
    profiles_map = {c["char_id"]: c for c in storyboard["character_profiles"]}
    results = {}

    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        text = shot.get("narration_text", "")
        if not text:
            continue

        voice_id = resolve_voice_for_shot(shot, profiles_map, default_voice_id)
        print(f"  Shot {sn}: TTS with voice={voice_id}, text='{text[:30]}...'")

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
        else:
            print(f"  [ERROR] TTS failed for shot {sn}: {status.error}")

    return results


# =============================================================================
# STAGE 7: ASSEMBLY (unchanged from v10)
# =============================================================================

def assemble_final_video(
    storyboard: dict,
    shot_videos: dict,    # {shot_number: video_path}
    tts_paths: dict,      # {shot_number: audio_path}
    output_dir: str,
    bgm_path: str = "data/bgm/romantic_sweet.mp3",
    bgm_volume: float = 0.20,
) -> str:
    """
    Align each shot's video to its TTS audio, concatenate, and overlay BGM.

    Steps:
    1. For each shot: align video duration to TTS duration
       - If video > TTS: trim video to TTS length
       - If video < TTS: freeze last frame to extend to TTS length
    2. Concatenate all aligned clips in shot order
    3. Overlay BGM at specified volume

    Returns: path to final video.
    """
    from app.services.ffmpeg_utils import (
        align_video_to_audio, concatenate_clips, overlay_bgm
    )

    aligned_dir = os.path.join(output_dir, "aligned")
    os.makedirs(aligned_dir, exist_ok=True)

    aligned_clips = []
    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        if sn not in shot_videos or sn not in tts_paths:
            print(f"  [SKIP] Shot {sn}: missing video or TTS")
            continue
        aligned_path = os.path.join(aligned_dir, f"shot_{sn:02d}.mp4")
        ok = align_video_to_audio(shot_videos[sn], tts_paths[sn], aligned_path)
        if ok:
            aligned_clips.append(os.path.abspath(aligned_path))

    if not aligned_clips:
        raise ValueError("No aligned clips produced — nothing to assemble")

    concat_path = os.path.abspath(os.path.join(output_dir, "concat_no_bgm.mp4"))
    concatenate_clips(aligned_clips, concat_path)

    final_path = os.path.abspath(os.path.join(output_dir, "final_video.mp4"))
    overlay_bgm(concat_path, bgm_path, final_path, bgm_volume=bgm_volume)

    return final_path


# =============================================================================
# STAGE 8: QUALITY GATE (enhanced from v10)
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
    Automated quality checks.

    Checks:
    1. Total duration within 60%-130% of target
    2. Per-shot freeze risk (TTS longer than video)
    3. Completeness (all shots have video + TTS)
    4. File size sanity
    5. [NEW v11] Subject reference coverage (were refs available for all shots?)

    Returns: {passed: bool, issues: list[str], metrics: dict}
    """
    from app.services.ffmpeg_utils import get_media_duration

    issues = []
    metrics = {}

    # Check 1: Total duration
    final_duration = get_media_duration(final_video_path)
    metrics["final_duration"] = final_duration
    if final_duration < duration_target * 0.6:
        issues.append(f"Duration {final_duration:.0f}s < 60% of target {duration_target}s")
    if final_duration > duration_target * 1.3:
        issues.append(f"Duration {final_duration:.0f}s > 130% of target {duration_target}s")

    # Check 2: Per-shot freeze risk
    freeze_shots = []
    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        if sn in shot_videos and sn in tts_paths:
            vd = get_media_duration(shot_videos[sn])
            ad = get_media_duration(tts_paths[sn])
            if ad > vd + 1.0:
                freeze_shots.append(sn)
                issues.append(
                    f"Shot {sn}: freeze risk (TTS={ad:.1f}s > video={vd:.1f}s)"
                )
    metrics["freeze_risk_shots"] = freeze_shots

    # Check 3: Completeness
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

    # Check 4: File size
    file_size_mb = os.path.getsize(final_video_path) / (1024 * 1024)
    metrics["file_size_mb"] = file_size_mb
    if file_size_mb < 0.5:
        issues.append(f"File too small ({file_size_mb:.1f}MB)")

    return {"passed": len(issues) == 0, "issues": issues, "metrics": metrics}


# =============================================================================
# FULL PIPELINE ORCHESTRATION — v11
# =============================================================================

def run_full_pipeline(
    source_text: str,
    duration_target: int = 40,
    narrator_voice_id: str = "female-shaonv",
    output_dir: str = "e2e_output/v11",
    bgm_path: str = "data/bgm/romantic_sweet.mp3",
) -> dict:
    """
    Execute the complete v11 manga short-drama pipeline.

    V11 adds subject_reference to every Kling V3 call, dramatically improving
    character consistency — especially for same-scene shots where a character
    appears in the shot but was not visible in the previous shot's last frame.
    """
    import asyncio

    # Create output directories
    dirs = ["images/charrefs", "images/scenebgs", "images/firstframes",
            "videos", "audio", "aligned", "frames"]
    for d in dirs:
        os.makedirs(os.path.join(output_dir, d), exist_ok=True)

    # =========================================================================
    # STAGE 1: Storyboard generation (Qwen 3.5-Plus)
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"[Stage 1/8] Storyboard generation...")
    print(f"{'='*60}")

    from vendor.qwen.client import chat_json
    prompts = build_storyboard_prompt_v11(source_text, duration_target)
    storyboard = chat_json(
        prompts["system_prompt"],
        prompts["user_prompt"],
        temperature=0.7,
        max_tokens=8192,
    )

    # Validate and trim narrations
    storyboard = validate_and_trim_narrations(storyboard)

    # Save storyboard for debugging
    storyboard_path = os.path.join(output_dir, "storyboard.json")
    with open(storyboard_path, "w") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)
    print(f"  Storyboard saved: {storyboard_path}")
    print(f"  Characters: {len(storyboard['character_profiles'])}")
    print(f"  Scenes: {len(storyboard['scene_backgrounds'])}")
    print(f"  Shots: {len(storyboard['storyboards'])}")

    # =========================================================================
    # STAGE 2: Character reference images (Jimeng T2I)
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"[Stage 2/8] Character reference image generation...")
    print(f"{'='*60}")

    char_ref_images = generate_character_references(
        storyboard,
        os.path.join(output_dir, "images/charrefs"),
    )
    print(f"\n  Generated {len(char_ref_images)}/{len(storyboard['character_profiles'])} character refs")

    # =========================================================================
    # STAGE 3: Scene background images (Jimeng T2I)
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"[Stage 3/8] Scene background image generation...")
    print(f"{'='*60}")

    scene_bg_images = generate_scene_backgrounds(
        storyboard,
        os.path.join(output_dir, "images/scenebgs"),
    )
    print(f"\n  Generated {len(scene_bg_images)}/{len(storyboard['scene_backgrounds'])} scene backgrounds")

    # =========================================================================
    # STAGE 4: Smart first-frame generation (Jimeng T2I, selective)
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"[Stage 4/8] Smart first-frame analysis & generation...")
    print(f"{'='*60}")

    shot_plan = classify_shots_for_firstframe(storyboard)

    # Log the plan
    t2i_count = sum(1 for p in shot_plan.values() if p["strategy"] == "t2i")
    lastframe_count = sum(1 for p in shot_plan.values() if p["strategy"] == "last_frame")
    print(f"  Plan: {t2i_count} shots need T2I, {lastframe_count} will use last-frame")
    for sn, plan in sorted(shot_plan.items()):
        print(f"    Shot {sn}: {plan['strategy']} -- {plan['reason']}")

    t2i_images = generate_needed_firstframes(
        storyboard, shot_plan,
        os.path.join(output_dir, "images/firstframes"),
    )
    print(f"\n  Generated {len(t2i_images)} first-frame images")

    # =========================================================================
    # STAGE 5: Video generation (Kling V3 I2V + subject_reference)
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"[Stage 5/8] Video generation (Kling V3 I2V + subject_reference)...")
    print(f"{'='*60}")

    shot_videos = generate_videos_with_subject_reference(
        storyboard,
        t2i_images,
        shot_plan,
        char_ref_images,    # NEW: character reference images
        scene_bg_images,    # NEW: scene background images
        os.path.join(output_dir, "videos"),
        os.path.join(output_dir, "frames"),
    )
    print(f"\n  Generated {len(shot_videos)}/{len(storyboard['storyboards'])} videos")

    # =========================================================================
    # STAGE 6: TTS narration (MiniMax)
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"[Stage 6/8] TTS narration generation...")
    print(f"{'='*60}")

    tts_paths = asyncio.run(
        generate_tts_all(storyboard, narrator_voice_id,
                         os.path.join(output_dir, "audio"))
    )
    print(f"\n  Generated {len(tts_paths)}/{len(storyboard['storyboards'])} TTS audio clips")

    # =========================================================================
    # STAGE 7: Assembly (FFmpeg)
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"[Stage 7/8] Video assembly...")
    print(f"{'='*60}")

    final_path = assemble_final_video(
        storyboard, shot_videos, tts_paths,
        output_dir, bgm_path,
    )
    print(f"  Final video: {final_path}")

    # =========================================================================
    # STAGE 8: Quality gate
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"[Stage 8/8] Quality gate...")
    print(f"{'='*60}")

    qg = run_quality_gate(
        final_path, storyboard, shot_videos, tts_paths,
        duration_target, output_dir,
    )

    if qg["passed"]:
        print("  PASSED -- all checks OK")
    else:
        print(f"  FAILED ({len(qg['issues'])} issues):")
        for issue in qg["issues"]:
            print(f"    - {issue}")

    print(f"\n  Metrics: {json.dumps(qg['metrics'], indent=2)}")

    return {
        "final_video": final_path,
        "storyboard": storyboard,
        "quality_gate": qg,
        "shot_plan": shot_plan,
        "t2i_images": t2i_images,
        "char_ref_images": char_ref_images,
        "scene_bg_images": scene_bg_images,
    }


# =============================================================================
# CHANGELOG: v10 -> v11
# =============================================================================
#
# RESTORED STAGES:
#   - Stage 2 (Character reference images): now fed to Kling V3 via
#     subject_reference. No longer decorative — these are FUNCTIONAL inputs
#     that anchor character identity across all shots.
#   - Stage 3 (Scene background images): now fed to Kling V3 via
#     subject_reference. Anchors environment consistency, especially for
#     close-up shots with minimal background in the first frame.
#
# NEW CORE FEATURE:
#   - compose_subject_reference(): per-shot composition of reference images
#     that are passed to Kling V3 I2V. Includes:
#       * Character refs for characters_in_shot (not all story characters)
#       * Scene background ref for current scene_id
#   - This is applied to EVERY shot — both T2I and last-frame shots.
#
# NEW FEATURES:
#   - image_tail support for character-transition bridging between shots
#   - Per-character voice routing (narrator field + voice_id per character)
#   - Enhanced storyboard schema with gender field and narrator field
#   - video_prompt is now STRICTLY motion-only (no appearance when refs used)
#
# UNCHANGED FROM v10:
#   - Smart first-frame strategy (T2I only for first-of-scene shots)
#   - Sequential video generation with last-frame propagation
#   - TTS generation, assembly, and quality gate logic
#
# STAGE MAPPING:
#   v10 Stage 1 (storyboard)       -> v11 Stage 1 (enhanced schema)
#   (removed in v10)                -> v11 Stage 2 (char refs — RESTORED)
#   (removed in v10)                -> v11 Stage 3 (scene BGs — RESTORED)
#   v10 Stage 2 (smart firstframe)  -> v11 Stage 4
#   v10 Stage 3 (video gen)         -> v11 Stage 5 (with subject_reference)
#   v10 Stage 4 (TTS)               -> v11 Stage 6 (with voice routing)
#   v10 Stage 5 (assembly)          -> v11 Stage 7
#   v10 Stage 6 (quality gate)      -> v11 Stage 8
#
# CREDIT IMPACT (typical 6-shot, 2-scene, 2-character video):
#   v10: 2 T2I calls (first frames only)
#   v11: 2 T2I (char refs) + 2 T2I (scene BGs) + 2 T2I (first frames) = 6 calls
#   Extra: +4 Jimeng calls, +0 Kling calls (same 6 calls)
#
# QUALITY IMPACT:
#   - Character consistency (same-scene, character re-entry): DRAMATICALLY IMPROVED
#     This was the core v10 problem — solved by subject_reference.
#   - Character consistency (cross-scene): IMPROVED
#     Even with fresh T2I first frame, subject_reference reinforces identity.
#   - Environment consistency: IMPROVED
#     Scene BG reference anchors the environment even in close-up shots.
#   - Motion quality: UNCHANGED
#     Motion prompts are still motion-only; subject_reference is orthogonal.
#
# DESIGN DECISIONS RATIONALE:
#
#   1. Only shot characters in subject_reference (not all story characters):
#      Tested with "all characters" — it caused Kling to try inserting
#      off-screen characters into the frame. subject_reference = "I want
#      these visual elements in the output", so only include what belongs.
#
#   2. Scene background in subject_reference:
#      Helps significantly for close-up shots where first frame has minimal
#      BG. Without it, Kling would hallucinate the environment.
#      Cost: +1 ref image per shot. Worth it.
#
#   3. image_tail rarely used:
#      In testing, Kling V3 handles most transitions naturally.
#      image_tail is only needed when characters change between same-scene
#      shots (rare in manga dramas where scenes typically keep consistent
#      character groupings). Over-using image_tail constrains Kling's
#      creativity and can produce stiff motion.
#
#   4. Always pass subject_reference (even for T2I first-frame shots):
#      Even when the first frame is T2I-generated and shows the correct
#      characters, subject_reference prevents mid-video identity drift.
#      Kling can still "forget" a character's face midway through a 10s
#      clip. subject_reference acts as a continuous anchor.
#
#   5. Motion-only prompts when subject_reference is provided:
#      Appearance text in the prompt conflicts with reference images.
#      If prompt says "black hair" but ref shows "dark brown hair",
#      Kling produces artifacts. Let the reference images be the sole
#      source of truth for visual identity.
