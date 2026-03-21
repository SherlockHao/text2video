"""
Manga Short Drama Production Pipeline v10 — Optimized Design
==============================================================

Target: 40-second 9:16 vertical manga-style short drama
Genre:  女频 豪门总裁/青春甜宠
Stack:  Qwen 3.5-Plus → Jimeng T2I 4.0 → Kling V3 I2V → MiniMax TTS → FFmpeg

WHAT CHANGED FROM v9:
---------------------
1. REMOVED Stage 2 (character reference images) — these were "human review only"
   and never fed into downstream stages. Pure waste of Jimeng credits.
   Character consistency still comes from the frozen appearance_en text.

2. REMOVED Stage 3 (scene background images) — same reason. The scene description
   is baked into each shot's image_prompt. Standalone backgrounds served no
   pipeline purpose.

3. SMART FIRST-FRAME STRATEGY (replaces old "generate ALL first frames"):
   - Only generate T2I images when ACTUALLY NEEDED
   - Use last-frame-of-previous-shot whenever possible
   - This cuts Jimeng T2I calls from N (every shot) to typically 1-2

4. Pipeline reduced from 9 stages to 6 stages (faster, cheaper, same quality).

FIRST-FRAME DECISION LOGIC:
----------------------------
For each shot, in order:

  Shot 1 (first shot of entire video):
    → MUST generate via Jimeng T2I. No previous frame exists.

  Shot N where scene_id == previous shot's scene_id (SAME SCENE continuation):
    → Use last frame extracted from previous shot's video.
    → This gives perfect visual continuity (same characters, same background).
    → The I2V model (Kling V3) handles the motion transition naturally.

  Shot N where scene_id != previous shot's scene_id (SCENE CHANGE):
    → Check the storyboard's "transition" field:
      - If transition == "cut": Generate fresh T2I image.
        Clean scene break. New background, possibly new characters.
        A fresh image prevents visual contamination from previous scene.
      - If transition == "dissolve" or "fade": Generate fresh T2I image.
        Same reasoning — the dissolve/fade happens in FFmpeg assembly,
        so the source frames should each be clean.
    → In practice: ALL scene changes get fresh T2I images.

WHY NOT always use last-frame for same-scene?
  It IS always correct for same-scene. The last frame contains the right
  characters in the right setting. Kling V3 I2V will animate from it using
  the new video_prompt. This produces seamless continuity within a scene.

WHY NOT use last-frame across scene changes?
  The last frame shows Scene A's background/characters. If Shot N is in
  Scene B (different location, different characters), the I2V model would
  try to morph Scene A into Scene B, producing artifacts. A fresh T2I
  image for Scene B is always better.

CREDIT IMPACT (typical 6-shot, 2-scene video):
  v9:  6 T2I (shots) + 2 T2I (chars) + 2 T2I (scenes) = 10 Jimeng calls
  v10: 2 T2I (shot 1 + first shot of scene 2)           = 2 Jimeng calls
  Savings: 80% fewer Jimeng T2I calls

QUALITY IMPACT:
  - Same-scene continuity: BETTER (real frame vs. re-generated approximation)
  - Scene changes: SAME (both use T2I)
  - Character consistency: SAME (frozen appearance_en unchanged)
  - No loss in video quality — Kling V3 I2V doesn't care if the input
    image came from T2I or from a previous video frame.
"""

import json


# =============================================================================
# PIPELINE OVERVIEW (6 stages)
# =============================================================================
#
# Stage 1: LLM storyboard generation (Qwen 3.5-Plus)
# Stage 2: Smart first-frame generation (Jimeng T2I, only for shots that need it)
# Stage 3: Video generation (Kling V3 I2V, sequential with last-frame propagation)
# Stage 4: TTS narration (MiniMax, parallel)
# Stage 5: Assembly (FFmpeg: align → concat → BGM overlay)
# Stage 6: Quality gate (automated checks)


# =============================================================================
# STAGE 1: LLM STORYBOARD — SCHEMA & PROMPT (unchanged from v9)
# =============================================================================

STORYBOARD_OUTPUT_SCHEMA = {
    "title": "str",
    "character_profiles": [
        {
            "char_id": "str — unique ID like 'char_su_niannian'",
            "name": "str — 角色名（中文）",
            "appearance": "str — 详细外貌描述（中文）",
            "appearance_en": (
                "str — FROZEN English appearance tag. "
                "Pasted verbatim into every image prompt. "
                "Must include: hair color+style, eye color, skin tone, "
                "body type, outfit with colors+materials, accessories."
            ),
            "voice_id": "str — MiniMax voice ID",
        }
    ],
    "scene_backgrounds": [
        {
            "scene_id": "str — unique ID like 'scene_lobby'",
            "name": "str — 场景名称",
            "description_en": (
                "str — Detailed English background description WITHOUT characters. "
                "Always end with 'manga style background, no characters, no people'"
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
                "appearance_en verbatim + scene background + style keywords."
            ),
            "video_prompt": (
                "str — English. Motion-only. Specific actions, expressions, "
                "camera movement. No appearance or background repetition."
            ),
            "narration_text": "str — 中文旁白",
            "scene_description": "str — 中文场景描述",
            "camera_movement": "str — static/pan_left/pan_right/zoom_in/zoom_out/etc",
            "transition": "str — cut/fade/dissolve",
        }
    ],
}


def build_storyboard_prompt_v10(
    source_text: str,
    duration_target: int = 40,
    aspect_ratio: str = "9:16",
) -> dict:
    """
    Build system + user prompts for storyboard generation.
    Identical to v9 — the storyboard schema is unchanged.
    The optimization happens downstream in how we USE the storyboard.
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
- 坏的: "subtle animation, gentle movement" （太笼统）
- 好的: "the man stands up from the chair, walks around the desk with measured steps, stops in front of the woman, camera tracks his movement"
- 坏的: "character moves, dramatic scene"

## 旁白控制（严格）
- 每段 narration_text 必须是中文
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
      "image_prompt": "masterpiece, best quality, ..., [FULL appearance_en], [pose], [background], [lighting]",
      "video_prompt": "[specific action, facial expression, camera movement]",
      "narration_text": "中文旁白",
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
# STAGE 2: SMART FIRST-FRAME GENERATION (replaces v9 Stages 2+3+4)
# =============================================================================
#
# Decision logic per shot:
#   - Shot 1 → always T2I (no previous frame)
#   - Same scene as previous → skip T2I (will use last frame from prev video)
#   - Different scene from previous → T2I (need new background/characters)
#
# The actual first-frame selection happens in Stage 3 (video generation),
# but we pre-generate the T2I images here for the shots that need them.

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
            # First shot: must generate
            result[sn] = {
                "strategy": "t2i",
                "reason": "first shot of video — no previous frame exists",
            }
        elif scene_id != prev_scene_id:
            # Scene change: generate fresh image
            result[sn] = {
                "strategy": "t2i",
                "reason": f"scene change: {prev_scene_id} → {scene_id}",
            }
        else:
            # Same scene continuation: use last frame from previous shot
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

    Unchanged from v9 — the prompt construction logic is the same.
    """
    base_prompt = shot.get("image_prompt", "")

    # Verify character appearances are present
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

    if "masterpiece" not in base_prompt.lower():
        parts.append("masterpiece, best quality, highly detailed, 4K")
    if "anime style" not in base_prompt.lower():
        parts.append("anime style, manga style, cel shading, vibrant colors, detailed illustration")

    parts.append(base_prompt)

    for app in missing_appearances:
        parts.append(app)

    if scene_desc and scene_desc[:30].lower() not in base_prompt.lower():
        scene_brief = scene_desc.replace("no characters, no people", "").strip(" ,.")
        parts.append(f"background: {scene_brief}")

    return ", ".join(parts)


def generate_needed_firstframes(
    storyboard: dict,
    shot_plan: dict,  # output of classify_shots_for_firstframe
    output_dir: str,
) -> dict:
    """
    Generate T2I first-frame images ONLY for shots that need them.

    Returns: {shot_number: image_path} — only contains shots with strategy "t2i"
    """
    from vendor.jimeng.t2i import generate_image
    import time

    profiles_map = {c["char_id"]: c for c in storyboard["character_profiles"]}
    scene_bgs = {s["scene_id"]: s for s in storyboard["scene_backgrounds"]}

    results = {}
    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        plan = shot_plan.get(sn, {})

        if plan.get("strategy") != "t2i":
            continue  # This shot will use last frame — no T2I needed

        prompt = build_shot_firstframe_prompt(shot, profiles_map, scene_bgs)
        paths = generate_image(
            prompt, width=832, height=1472,
            output_dir=output_dir, prefix=f"shot_{sn:02d}"
        )
        if paths:
            results[sn] = paths[0]
        time.sleep(3)

    return results


# =============================================================================
# STAGE 3: VIDEO GENERATION — KLING V3 I2V (with integrated last-frame logic)
# =============================================================================

def build_kling_v3_motion_prompt(shot: dict) -> str:
    """
    Build motion prompt for Kling V3 I2V. Unchanged from v9.
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
    if video_prompt:
        parts.append(video_prompt)
    else:
        parts.append("subtle character animation, gentle breathing")

    cam_lower = video_prompt.lower()
    if "camera" not in cam_lower:
        cam_desc = camera_map.get(camera, camera_map["static"])
        parts.append(cam_desc)

    parts.append("hair sways gently, cloth physics, anime style, smooth animation")

    prompt = ", ".join(parts)
    words = prompt.split()
    if len(words) > 180:
        prompt = " ".join(words[:180])

    return prompt


KLING_V3_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted face, extra fingers, deformed, morphing, "
    "flickering, abrupt scene change, live action, photorealistic, "
    "text, watermark, signature, frame, border"
)


def generate_videos_with_smart_firstframes(
    storyboard: dict,
    t2i_images: dict,   # {shot_number: image_path} — only shots that got T2I
    shot_plan: dict,     # {shot_number: {"strategy": ...}}
    output_dir: str,
    frames_dir: str,
) -> dict:
    """
    Generate all videos using Kling V3 I2V.

    FIRST-FRAME RESOLUTION (the core v10 logic):
    - Processes shots SEQUENTIALLY (must be, for last-frame propagation)
    - For each shot, determines the first frame based on shot_plan:
        strategy == "t2i"        → use pre-generated T2I image from t2i_images
        strategy == "last_frame" → use last frame extracted from previous video

    This means:
    - Shot 1: always uses T2I image (guaranteed to be in t2i_images)
    - Same-scene continuations: use extracted last frame (seamless!)
    - Scene changes: use T2I image (clean break)

    FALLBACK: if last_frame extraction fails for a "last_frame" strategy shot,
    we fall back to generating a T2I image on-the-fly. This shouldn't happen
    in practice, but we handle it defensively.

    Returns: {shot_number: video_path}
    """
    from vendor.kling.client import KlingClient
    from vendor.jimeng.t2i import generate_image
    import subprocess, os, time

    client = KlingClient()
    results = {}
    prev_last_frame = None

    profiles_map = {c["char_id"]: c for c in storyboard["character_profiles"]}
    scene_bgs = {s["scene_id"]: s for s in storyboard["scene_backgrounds"]}

    for shot in storyboard["storyboards"]:
        sn = shot["shot_number"]
        duration = shot.get("duration_seconds", 8)
        plan = shot_plan.get(sn, {})
        strategy = plan.get("strategy", "t2i")

        # --- Determine first frame ---
        if strategy == "t2i":
            first_frame_path = t2i_images.get(sn)
            if not first_frame_path:
                # Should not happen if generate_needed_firstframes worked
                print(f"  [WARN] Shot {sn}: T2I image missing, generating on-the-fly")
                prompt = build_shot_firstframe_prompt(shot, profiles_map, scene_bgs)
                paths = generate_image(
                    prompt, width=832, height=1472,
                    output_dir=frames_dir, prefix=f"shot_{sn:02d}_fallback"
                )
                first_frame_path = paths[0] if paths else None
                if not first_frame_path:
                    print(f"  [ERROR] Shot {sn}: cannot generate first frame, skipping")
                    continue

        elif strategy == "last_frame":
            if prev_last_frame and os.path.exists(prev_last_frame):
                first_frame_path = prev_last_frame
                print(f"  Shot {sn}: using last frame from previous shot (continuity)")
            else:
                # Fallback: generate T2I on-the-fly
                print(f"  [WARN] Shot {sn}: last frame unavailable, generating T2I fallback")
                prompt = build_shot_firstframe_prompt(shot, profiles_map, scene_bgs)
                paths = generate_image(
                    prompt, width=832, height=1472,
                    output_dir=frames_dir, prefix=f"shot_{sn:02d}_fallback"
                )
                first_frame_path = paths[0] if paths else None
                if not first_frame_path:
                    print(f"  [ERROR] Shot {sn}: cannot generate first frame, skipping")
                    continue

        # --- Generate video ---
        motion_prompt = build_kling_v3_motion_prompt(shot)
        image_b64 = _prepare_image_for_kling(first_frame_path)

        kling_duration = str(max(5, min(int(duration), 10)))
        resp = client.generate_video(
            image=image_b64,
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
            prev_last_frame = None
            continue

        data = client.poll_task(task_id, task_type="video", max_wait=600)
        if not data:
            prev_last_frame = None
            continue

        video_url = data.get("task_result", {}).get("videos", [{}])[0].get("url", "")
        if video_url:
            import requests
            video_path = os.path.join(output_dir, f"shot_{sn:02d}.mp4")
            r = requests.get(video_url, timeout=120)
            with open(video_path, "wb") as f:
                f.write(r.content)
            results[sn] = video_path

            # Extract last frame for potential use by next shot
            last_frame_path = os.path.join(frames_dir, f"shot_{sn:02d}_lastframe.png")
            _ok = subprocess.run(
                ["ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path,
                 "-frames:v", "1", last_frame_path],
                capture_output=True, timeout=10,
            )
            if _ok.returncode == 0 and os.path.exists(last_frame_path):
                prev_last_frame = last_frame_path
            else:
                prev_last_frame = None
        else:
            prev_last_frame = None

        time.sleep(5)

    return results


def _prepare_image_for_kling(image_path: str) -> str:
    """Convert local image to base64 for Kling V3 API."""
    import base64
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return b64


# =============================================================================
# STAGE 4: TTS & NARRATION SYNC (was Stage 6 in v9)
# =============================================================================

def calculate_max_narration_chars(duration_seconds: float, speed: float = 0.9) -> int:
    """Max narration characters to fit within video duration."""
    effective_rate = 3.5 * speed
    usable_duration = duration_seconds * 0.90
    return int(usable_duration * effective_rate)


def validate_and_trim_narrations(storyboard: dict) -> dict:
    """Pre-TTS validation: ensure narration fits shot duration."""
    for shot in storyboard["storyboards"]:
        duration = shot.get("duration_seconds", 8)
        narration = shot.get("narration_text", "")
        max_chars = calculate_max_narration_chars(duration)
        if len(narration) > max_chars:
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
    """Generate TTS for all shots. Returns: {shot_number: audio_path}"""
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
# STAGE 5: ASSEMBLY (was Stage 7 in v9, unchanged)
# =============================================================================

def assemble_final_video(
    storyboard: dict,
    shot_videos: dict,
    tts_paths: dict,
    output_dir: str,
    bgm_path: str = "data/bgm/romantic_sweet.mp3",
    bgm_volume: float = 0.20,
) -> str:
    """Align → concat → BGM overlay. Returns path to final video."""
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

    concat_path = os.path.abspath(os.path.join(output_dir, "concat_no_bgm.mp4"))
    concatenate_clips(aligned_clips, concat_path)

    final_path = os.path.abspath(os.path.join(output_dir, "final_video.mp4"))
    overlay_bgm(concat_path, bgm_path, final_path, bgm_volume=bgm_volume)

    return final_path


# =============================================================================
# STAGE 6: QUALITY GATE (was Stage 8 in v9, unchanged)
# =============================================================================

def run_quality_gate(
    final_video_path: str,
    storyboard: dict,
    shot_videos: dict,
    tts_paths: dict,
    duration_target: int = 40,
    output_dir: str = ".",
) -> dict:
    """Automated quality checks. Returns {passed, issues, metrics}."""
    from app.services.ffmpeg_utils import get_media_duration
    import subprocess, os

    issues = []
    metrics = {}

    final_duration = get_media_duration(final_video_path)
    metrics["final_duration"] = final_duration
    if final_duration < duration_target * 0.6:
        issues.append(f"Duration {final_duration:.0f}s < 60% of target {duration_target}s")
    if final_duration > duration_target * 1.3:
        issues.append(f"Duration {final_duration:.0f}s > 130% of target {duration_target}s")

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

    file_size_mb = os.path.getsize(final_video_path) / (1024 * 1024)
    metrics["file_size_mb"] = file_size_mb
    if file_size_mb < 0.5:
        issues.append(f"File too small ({file_size_mb:.1f}MB)")

    return {"passed": len(issues) == 0, "issues": issues, "metrics": metrics}


# =============================================================================
# FULL PIPELINE ORCHESTRATION — v10
# =============================================================================

def run_full_pipeline(
    source_text: str,
    duration_target: int = 40,
    voice_id: str = "female-shaonv",
    output_dir: str = "e2e_output/v10",
    bgm_path: str = "data/bgm/romantic_sweet.mp3",
) -> dict:
    """
    Execute the v10 manga short-drama pipeline.

    Key difference from v9:
    - No separate character reference or scene background generation
    - Smart first-frame strategy: only generate T2I for shots that need it
    - Fewer stages, fewer API calls, same or better quality
    """
    import os, asyncio

    for d in ["images", "videos", "audio", "aligned", "frames"]:
        os.makedirs(f"{output_dir}/{d}", exist_ok=True)

    # --- Stage 1: Storyboard ---
    print(f"\n{'='*60}\n[Stage 1/6] Storyboard generation...")
    from vendor.qwen.client import chat_json
    prompts = build_storyboard_prompt_v10(source_text, duration_target)
    storyboard = chat_json(
        prompts["system_prompt"], prompts["user_prompt"],
        temperature=0.7, max_tokens=8192,
    )
    storyboard = validate_and_trim_narrations(storyboard)
    with open(f"{output_dir}/storyboard.json", "w") as f:
        json.dump(storyboard, f, ensure_ascii=False, indent=2)

    # --- Stage 2: Smart first-frame generation ---
    print(f"\n[Stage 2/6] Smart first-frame analysis & generation...")
    shot_plan = classify_shots_for_firstframe(storyboard)

    # Log the plan
    t2i_count = sum(1 for p in shot_plan.values() if p["strategy"] == "t2i")
    lastframe_count = sum(1 for p in shot_plan.values() if p["strategy"] == "last_frame")
    print(f"  Plan: {t2i_count} shots need T2I, {lastframe_count} shots will use last-frame")
    for sn, plan in sorted(shot_plan.items()):
        print(f"    Shot {sn}: {plan['strategy']} — {plan['reason']}")

    # Generate only the T2I images we actually need
    t2i_images = generate_needed_firstframes(
        storyboard, shot_plan, f"{output_dir}/images"
    )
    print(f"  Generated {len(t2i_images)} T2I first-frame images")

    # --- Stage 3: Video generation (Kling V3, sequential) ---
    print(f"\n[Stage 3/6] Video generation (Kling V3 I2V)...")
    shot_videos = generate_videos_with_smart_firstframes(
        storyboard, t2i_images, shot_plan,
        f"{output_dir}/videos", f"{output_dir}/frames",
    )

    # --- Stage 4: TTS ---
    print(f"\n[Stage 4/6] TTS narration...")
    tts_paths = asyncio.run(
        generate_tts_all(storyboard, voice_id, f"{output_dir}/audio")
    )

    # --- Stage 5: Assembly ---
    print(f"\n[Stage 5/6] Assembly...")
    final_path = assemble_final_video(
        storyboard, shot_videos, tts_paths,
        output_dir, bgm_path,
    )

    # --- Stage 6: Quality gate ---
    print(f"\n[Stage 6/6] Quality gate...")
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
        "shot_plan": shot_plan,
        "t2i_images": t2i_images,
    }


# =============================================================================
# CHANGELOG: v9 → v10
# =============================================================================
#
# REMOVED STAGES:
#   - Stage 2 (Character reference images): was for "human review only" and
#     never fed into any downstream stage. The frozen appearance_en text is
#     what drives character consistency, not a reference image.
#   - Stage 3 (Scene background images): same — purely decorative. The scene
#     description_en is baked into each shot's image_prompt already.
#
# MERGED/OPTIMIZED:
#   - Old Stage 4 (generate ALL shot first-frames) → New Stage 2 (generate
#     ONLY the first-frames that truly need T2I generation).
#   - Old Stage 5 (video generation with last-frame continuity) → New Stage 3
#     (video generation with INTEGRATED first-frame resolution logic).
#
# NEW LOGIC:
#   - classify_shots_for_firstframe(): analyzes the storyboard to determine
#     which shots need T2I and which can reuse previous shot's last frame.
#   - generate_videos_with_smart_firstframes(): resolves first frames at
#     video-generation time, with fallback to on-the-fly T2I if needed.
#
# STAGE MAPPING:
#   v9 Stage 0 (input validation)          → (handled by caller)
#   v9 Stage 1 (storyboard)                → v10 Stage 1
#   v9 Stage 2 (char refs)                 → REMOVED
#   v9 Stage 3 (scene backgrounds)         → REMOVED
#   v9 Stage 4 (all shot first-frames)     → v10 Stage 2 (smart, partial)
#   v9 Stage 5 (video gen)                 → v10 Stage 3 (with integrated logic)
#   v9 Stage 6 (TTS)                       → v10 Stage 4
#   v9 Stage 7 (assembly)                  → v10 Stage 5
#   v9 Stage 8 (quality gate)              → v10 Stage 6
#
# CREDIT SAVINGS (typical 6-shot, 2-scene video):
#   v9:  2 char refs + 2 scene BGs + 6 shot frames = 10 Jimeng T2I calls
#   v10: 2 shot frames (shot 1 + first shot of scene 2)  = 2 Jimeng T2I calls
#   Jimeng savings: ~80%
#   Kling usage: identical (1 call per shot, unchanged)
#
# QUALITY ASSESSMENT:
#   - Same-scene shot transitions: IMPROVED (real last-frame = pixel-perfect
#     continuity, vs T2I re-generation which can drift despite frozen text)
#   - Scene-change transitions: UNCHANGED (both v9 and v10 use fresh T2I)
#   - Character consistency: UNCHANGED (driven by appearance_en text, not images)
#   - Overall: strictly better or equal on every dimension
