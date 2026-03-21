"""
E2E v10: Jimeng T2I + Kling V3 I2V Pipeline
============================================
Stage 1: LLM Storyboard (Qwen)
Stage 2: Character Reference Images (Jimeng T2I) — for review
Stage 3: Scene Background Images (Jimeng T2I) — for review
Stage 4: Smart First-Frame Generation (Jimeng T2I, only scene-first shots)
Stage 5: Video Generation (Kling V3 I2V, sequential + last-frame continuity)
Stage 6: TTS (MiniMax)
Stage 7: Assembly (FFmpeg)
Stage 8: Quality Gate
"""

import json, os, sys, time, asyncio, argparse, subprocess, base64

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

parser = argparse.ArgumentParser()
parser.add_argument("--duration", type=int, default=40)
parser.add_argument("--voice", type=str, default="female-shaonv")
parser.add_argument("--output", type=str, default="e2e_output/v10")
parser.add_argument("--stop-after", type=str, default=None,
                    help="Stop after stage: storyboard, characters, scenes, firstframes, video1")
args = parser.parse_args()

DURATION = args.duration
VOICE_ID = args.voice
OUTPUT = args.output

for d in ["images", "scenes", "characters", "videos", "audio", "aligned", "frames"]:
    os.makedirs(f"{OUTPUT}/{d}", exist_ok=True)

from vendor.qwen.client import chat_with_system, chat_json, _extract_json
from vendor.jimeng.t2i import submit_t2i_task, get_t2i_result, save_images, generate_image
from vendor.kling.client import KlingClient
from app.services.ffmpeg_utils import (
    align_video_to_audio, concatenate_clips, overlay_bgm, get_media_duration
)
from app.services.narration_utils import shorten_narration_via_llm

import requests as http_requests


def log(msg):
    print(msg, flush=True)


def extract_last_frame(video_path: str, output_path: str) -> bool:
    r = subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path, "-frames:v", "1", output_path],
        capture_output=True, text=True, timeout=10,
    )
    return r.returncode == 0 and os.path.exists(output_path)


# ============ STAGE 1: Storyboard ============
log(f"\n{'='*60}\n[Stage 1/8] Storyboard ({DURATION}s)...")

with open("data/test_novel.txt") as f:
    novel = f.read()

min_shots = max(3, DURATION // 10)
max_shots = max(min_shots + 1, DURATION // 5)

system_prompt = f"""你是一位专业的漫画分镜师和AI图像/视频生成提示词专家。你的任务是将文本内容拆解为一系列连续的分镜，用于生成"解说类漫剧"短视频。

## 视频规格
- 目标时长: {DURATION}秒
- 画面比例: 9:16 (竖屏)
- 预期分镜数: {min_shots}-{max_shots}个
- 每个分镜时长: 5-10秒
- 所有分镜的 duration_seconds 之和必须接近 {DURATION} 秒

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
- 坏的: "subtle animation, gentle movement"
- 好的: "the man stands up from the chair, walks around the desk with measured steps, stops in front of the woman, camera tracks his movement"
- 坏的: "character moves, dramatic scene"

## 旁白控制（严格）
- 每段 narration_text 必须是中文
- 中文语速约 3.5字/秒（speed=0.9时）
- 5秒分镜 → 约15-17个字
- 8秒分镜 → 约25-28个字
- 10秒分镜 → 约30-35个字
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
2. duration_seconds 总和 ≈ {DURATION}s
3. image_prompt 必须包含角色完整 appearance_en（逐字复制）
4. video_prompt 必须描述具体动作，禁止笼统描述
5. narration_text 字数严格遵守: max_chars = floor(duration_seconds × 3.15)
6. 只输出JSON"""

user_prompt = f"""请将以下文本拆解为漫画风格的解说类短视频分镜。

【重要】请直接输出JSON，不要输出任何分析或说明。你的回复必须以 {{ 开头。

文本内容：
{novel}"""

raw = chat_with_system(system_prompt, user_prompt, max_tokens=8192)
sb = json.loads(_extract_json(raw))
shots = sb.get("storyboards", [])
chars = sb.get("character_profiles", [])
scenes = sb.get("scene_backgrounds", [])

# Validate and trim narrations
for s in shots:
    duration = s.get("duration_seconds", 8)
    max_chars = int(duration * 3.15)
    nt = s.get("narration_text", "")
    if len(nt) > max_chars:
        s["narration_text"] = shorten_narration_via_llm(nt, max_chars, s.get("scene_description", ""))

with open(f"{OUTPUT}/storyboard.json", "w") as f:
    json.dump(sb, f, ensure_ascii=False, indent=2)

log(f"  {len(shots)} shots, {len(scenes)} scenes, {len(chars)} characters")
for c in chars:
    log(f"  Character: {c['name']} ({c['char_id']})")
    log(f"    appearance_en: {c.get('appearance_en', '')[:100]}...")
for sc in scenes:
    log(f"  Scene: {sc['scene_id']} - {sc['name']}")
for s in shots:
    log(f"  Shot {s['shot_number']}: scene={s.get('scene_id','')} | dur={s.get('duration_seconds',0)}s | '{s.get('narration_text','')}'")

if args.stop_after == "storyboard":
    log("\n--- Stopped after storyboard. Review storyboard.json ---")
    sys.exit(0)


# ============ STAGE 2: Character Reference Images ============
log(f"\n[Stage 2/8] Character reference images...")

char_images = {}
for c in chars:
    char_id = c["char_id"]
    appearance_en = c.get("appearance_en", "")
    prompt = (
        "masterpiece, best quality, highly detailed, 4K, "
        "anime style, manga style, cel shading, vibrant colors, "
        "character reference sheet, full body portrait, "
        "front view, standing pose, looking at viewer, "
        f"{appearance_en}, "
        "simple solid light grey background, soft studio lighting, "
        "no other characters, solo"
    )
    paths = generate_image(prompt, width=832, height=1472,
                           output_dir=f"{OUTPUT}/characters", prefix=char_id)
    if paths:
        char_images[char_id] = paths[0]
        log(f"  {c['name']} ({char_id}): ✓")
    time.sleep(3)

log(f"  {len(char_images)}/{len(chars)} character images generated")

if args.stop_after == "characters":
    log(f"\n--- Stopped after characters. Review {OUTPUT}/characters/ ---")
    sys.exit(0)


# ============ STAGE 3: Scene Background Images ============
log(f"\n[Stage 3/8] Scene background images...")

scene_images = {}
scene_desc_map = {}
for sc in scenes:
    sid = sc["scene_id"]
    desc_en = sc.get("description_en", "")
    scene_desc_map[sid] = desc_en

    desc = desc_en.rstrip(" ,.")
    prompt = (
        "masterpiece, best quality, highly detailed, 4K, "
        "anime style, manga style, cel shading, vibrant colors, "
        "background art, environment concept art, "
        f"{desc}, "
        "no characters, no people, no figures, empty scene"
    )
    paths = generate_image(prompt, width=832, height=1472,
                           output_dir=f"{OUTPUT}/scenes", prefix=sid)
    if paths:
        scene_images[sid] = paths[0]
        log(f"  {sid} ({sc['name']}): ✓")
    time.sleep(3)

log(f"  {len(scene_images)}/{len(scenes)} scene images generated")

if args.stop_after == "scenes":
    log(f"\n--- Stopped after scenes. Review {OUTPUT}/scenes/ ---")
    sys.exit(0)


# ============ STAGE 4: Smart First-Frame Generation ============
log(f"\n[Stage 4/8] Smart first-frame generation...")

profiles_map = {c["char_id"]: c for c in chars}

# Classify shots
shot_plan = {}
prev_scene_id = None
for s in shots:
    sn = s["shot_number"]
    scene_id = s.get("scene_id", "")
    if sn == 1:
        shot_plan[sn] = "t2i"
        log(f"  Shot {sn}: T2I (first shot)")
    elif scene_id != prev_scene_id:
        shot_plan[sn] = "t2i"
        log(f"  Shot {sn}: T2I (scene change → {scene_id})")
    else:
        shot_plan[sn] = "last_frame"
        log(f"  Shot {sn}: last_frame (same scene {scene_id})")
    prev_scene_id = scene_id

# Generate T2I images for shots that need them
t2i_images = {}
for s in shots:
    sn = s["shot_number"]
    if shot_plan[sn] != "t2i":
        continue

    base_prompt = s.get("image_prompt", "")

    # Verify character appearances are in prompt
    chars_in_shot = s.get("characters_in_shot", [])
    missing = []
    for cid in chars_in_shot:
        app = profiles_map.get(cid, {}).get("appearance_en", "")
        if app and app[:40].lower() not in base_prompt.lower():
            missing.append(app)

    # Verify scene background
    scene_id = s.get("scene_id", "")
    scene_desc = scene_desc_map.get(scene_id, "")

    parts = []
    if "masterpiece" not in base_prompt.lower():
        parts.append("masterpiece, best quality, highly detailed, 4K")
    if "anime style" not in base_prompt.lower():
        parts.append("anime style, manga style, cel shading, vibrant colors, detailed illustration")
    parts.append(base_prompt)
    for app in missing:
        parts.append(app)
    if scene_desc and scene_desc[:30].lower() not in base_prompt.lower():
        scene_brief = scene_desc.replace("no characters, no people", "").strip(" ,.")
        parts.append(f"background: {scene_brief}")

    prompt = ", ".join(parts)
    paths = generate_image(prompt, width=832, height=1472,
                           output_dir=f"{OUTPUT}/images", prefix=f"shot_{sn:02d}")
    if paths:
        t2i_images[sn] = paths[0]
        log(f"  Shot {sn} first-frame: ✓")
    time.sleep(3)

log(f"  {len(t2i_images)} T2I first-frames generated")

if args.stop_after == "firstframes":
    log(f"\n--- Stopped after first-frames. Review {OUTPUT}/images/ ---")
    sys.exit(0)


# ============ STAGE 5: Video Generation (Kling V3 I2V) ============
log(f"\n[Stage 5/8] Video generation (Kling V3 I2V)...")

NEGATIVE_PROMPT = (
    "blurry, low quality, distorted face, extra fingers, deformed, morphing, "
    "flickering, abrupt scene change, live action, photorealistic, "
    "text, watermark, signature, frame, border"
)

kling = KlingClient()
shot_videos = {}
prev_last_frame = None

for idx, s in enumerate(shots):
    sn = s["shot_number"]
    duration = s.get("duration_seconds", 8)

    # Determine first frame
    if shot_plan[sn] == "t2i":
        if sn not in t2i_images:
            log(f"  Shot {sn}: SKIP (no first-frame image)")
            continue
        first_frame_path = t2i_images[sn]
        log(f"  Shot {sn}: using T2I first-frame")
    else:
        if prev_last_frame and os.path.exists(prev_last_frame):
            first_frame_path = prev_last_frame
            log(f"  Shot {sn}: using last-frame continuity")
        else:
            log(f"  Shot {sn}: last-frame unavailable, generating T2I fallback...")
            # Fallback: generate on-the-fly
            base_prompt = s.get("image_prompt", "")
            paths = generate_image(base_prompt, width=832, height=1472,
                                   output_dir=f"{OUTPUT}/images", prefix=f"shot_{sn:02d}_fb")
            if paths:
                first_frame_path = paths[0]
            else:
                log(f"  Shot {sn}: SKIP (fallback failed)")
                continue

    # Build motion prompt
    video_prompt = s.get("video_prompt", "")
    camera = s.get("camera_movement", "static")
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
    motion_parts = []
    if video_prompt:
        motion_parts.append(video_prompt)
    else:
        motion_parts.append("subtle character animation, gentle breathing")
    if "camera" not in video_prompt.lower():
        motion_parts.append(camera_map.get(camera, "camera remains still"))
    motion_parts.append("hair sways gently, cloth physics, anime style, smooth animation")
    motion_prompt = ", ".join(motion_parts)

    log(f"    motion: {motion_prompt[:100]}...")

    # Prepare image for Kling (base64)
    with open(first_frame_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    # Submit to Kling V3
    # kling-v1-6 only accepts "5" or "10", snap to nearest
    kling_duration = "10" if duration > 7 else "5"
    try:
        resp = kling.generate_video(
            image=image_b64,
            prompt=motion_prompt,
            model_name="kling-v1-6",
            mode="std",
            duration=kling_duration,
            aspect_ratio="9:16",
            negative_prompt=NEGATIVE_PROMPT,
            cfg_scale=0.5,
        )
    except Exception as e:
        log(f"  Shot {sn}: API error: {e}")
        prev_last_frame = None
        continue

    resp_code = resp.get("code", -1)
    if resp_code != 0:
        log(f"  Shot {sn}: API returned code={resp_code} msg={resp.get('message','')}")
        prev_last_frame = None
        continue

    task_id = resp.get("data", {}).get("task_id")
    if not task_id:
        log(f"  Shot {sn}: no task_id returned")
        prev_last_frame = None
        continue

    log(f"  Shot {sn}: task_id={task_id}, polling...")
    data = kling.poll_task(task_id, task_type="video", max_wait=600, interval=10)
    if not data:
        log(f"  Shot {sn}: poll failed")
        prev_last_frame = None
        continue

    # Download video
    videos = data.get("task_result", {}).get("videos", [])
    if not videos:
        log(f"  Shot {sn}: no video in result")
        prev_last_frame = None
        continue

    video_url = videos[0].get("url", "")
    if not video_url:
        log(f"  Shot {sn}: no video URL")
        prev_last_frame = None
        continue

    video_path = f"{OUTPUT}/videos/shot_{sn:02d}.mp4"
    r = http_requests.get(video_url, timeout=120)
    with open(video_path, "wb") as f:
        f.write(r.content)
    shot_videos[sn] = video_path

    # Extract last frame for next shot
    lf_path = f"{OUTPUT}/frames/shot_{sn:02d}_lastframe.png"
    if extract_last_frame(video_path, lf_path):
        prev_last_frame = lf_path
        log(f"  Shot {sn}: ✓ ({kling_duration}s, last-frame saved)")
    else:
        prev_last_frame = None
        log(f"  Shot {sn}: ✓ ({kling_duration}s, last-frame extraction failed)")

    # === STOP AFTER FIRST VIDEO for review ===
    if args.stop_after == "video1" or (idx == 0 and args.stop_after is None):
        log(f"\n{'='*60}")
        log(f"★ First video generated: {video_path}")
        log(f"  Duration: {get_media_duration(video_path):.1f}s")
        log(f"  First-frame: {first_frame_path}")
        log(f"  Motion prompt: {motion_prompt}")
        log(f"\n  Please review the video and first-frame image.")
        log(f"  To continue full pipeline, re-run with: --stop-after none")
        log(f"{'='*60}")
        sys.exit(0)

    time.sleep(5)

log(f"  {len(shot_videos)}/{len(shots)} videos generated")


# ============ STAGE 6: TTS ============
log(f"\n[Stage 6/8] TTS ({VOICE_ID})...")

async def gen_tts():
    from app.ai.providers.minimax_tts import MiniMaxTTSProvider
    provider = MiniMaxTTSProvider()
    paths = {}
    for s in shots:
        sn = s["shot_number"]
        text = s.get("narration_text", "")
        if not text:
            continue
        job_id = await provider.submit_job({
            "text": text, "voice_id": VOICE_ID, "speed": 0.9, "emotion": "happy",
        })
        status = await provider.poll_job(job_id)
        if status.result_data:
            path = f"{OUTPUT}/audio/shot_{sn:02d}.mp3"
            with open(path, "wb") as f:
                f.write(status.result_data)
            paths[sn] = path
            log(f"  Shot {sn}: ✓")
        time.sleep(1)
    return paths

tts_paths = asyncio.run(gen_tts())


# ============ STAGE 7: Assembly ============
log(f"\n[Stage 7/8] Assembly...")
aligned = []
for s in shots:
    sn = s["shot_number"]
    if sn not in shot_videos or sn not in tts_paths:
        continue
    out = f"{OUTPUT}/aligned/shot_{sn:02d}.mp4"
    ok = align_video_to_audio(shot_videos[sn], tts_paths[sn], out)
    if ok:
        vd = get_media_duration(shot_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        fd = get_media_duration(out)
        log(f"  Shot {sn}: v={vd:.1f}s a={ad:.1f}s → {fd:.1f}s ✓")
        aligned.append(os.path.abspath(out))

concat = os.path.abspath(f"{OUTPUT}/concat_no_bgm.mp4")
concatenate_clips(aligned, concat)
log(f"  Concat: {get_media_duration(concat):.1f}s")

final = os.path.abspath(f"{OUTPUT}/final_video.mp4")
bgm = os.path.abspath("data/bgm/romantic_sweet.mp3")
overlay_bgm(concat, bgm, final, bgm_volume=0.20)
dur = get_media_duration(final)
size = os.path.getsize(final) / 1024 / 1024
log(f"  Final: {dur:.1f}s, {size:.1f}MB")


# ============ STAGE 8: Quality Gate ============
log(f"\n{'='*60}\n[Stage 8/8] Quality gate...")
issues = []

if dur < DURATION * 0.6:
    issues.append(f"Duration {dur:.0f}s < 60% of target {DURATION}s")
if dur > DURATION * 1.3:
    issues.append(f"Duration {dur:.0f}s > 130% of target {DURATION}s")

for s in shots:
    sn = s["shot_number"]
    if sn in shot_videos and sn in tts_paths:
        vd = get_media_duration(shot_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        if ad > vd + 1.0:
            issues.append(f"Shot {sn}: freeze risk (TTS={ad:.1f}s > video={vd:.1f}s)")

# BGM check
r_c = subprocess.run(["ffmpeg", "-i", concat, "-ss", "15", "-t", "3", "-af", "volumedetect", "-f", "null", "-"],
    capture_output=True, text=True, timeout=10)
r_f = subprocess.run(["ffmpeg", "-i", final, "-ss", "15", "-t", "3", "-af", "volumedetect", "-f", "null", "-"],
    capture_output=True, text=True, timeout=10)
vc = vf = -91.0
for l in r_c.stderr.split("\n"):
    if "mean_volume" in l:
        try: vc = float(l.split(":")[1].split("dB")[0])
        except: pass
for l in r_f.stderr.split("\n"):
    if "mean_volume" in l:
        try: vf = float(l.split(":")[1].split("dB")[0])
        except: pass
diff = abs(vc - vf)
if diff < 1.0:
    issues.append(f"BGM not audible (diff={diff:.1f}dB)")
else:
    log(f"  BGM confirmed ✓ (diff={diff:.1f}dB)")

if len(shot_videos) < len(shots):
    issues.append(f"Missing videos: {len(shot_videos)}/{len(shots)}")

if issues:
    log(f"\n  ⚠ ISSUES ({len(issues)}):")
    for i in issues:
        log(f"    - {i}")
    log(f"  Quality gate: FAILED")
else:
    log(f"  ✓ Quality gate: PASSED")

log(f"\n{'='*60}")
log(f"★ {OUTPUT}/final_video.mp4 ({dur:.1f}s, {size:.1f}MB)")
log(f"{'='*60}")
