"""
E2E v11b: Final pipeline with all P0/P1 fixes
================================================
P0 fixes:
  - Keep T2I first-frame for scene-first shots (characters won't appear from empty bg)
  - Duration clamp: max(5, min(15, computed))
  - Pause/interjection-aware duration calculation
P1 fixes:
  - First-shot video_prompt must contain character action verb
  - Subtitle overlay in assembly
  - Retry strategy (1 retry per shot)
Other improvements:
  - subject_reference = character refs only (no scene bg)
  - emotion field per shot → TTS
  - Rich storytelling narration with preserved dialogue
  - Duration derived from narration length
  - BGM volume 0.25

Stages:
  1: LLM Storyboard (Qwen) — rich narration + emotion + duration from char count
  2: Character Reference Images (Jimeng T2I) → subject_reference
  3: Scene Background Images (Jimeng T2I) → subject_reference removed, kept for review
  4: First-Frame Images (Jimeng T2I, scene-first shots only) → image
  5: Video Generation (Kling V3 I2V + subject_reference)
  6: TTS (MiniMax, per-shot emotion)
  7: Assembly (FFmpeg + subtitles + BGM)
  8: Quality Gate
"""

import json, os, sys, time, asyncio, argparse, subprocess, base64, math, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

parser = argparse.ArgumentParser()
parser.add_argument("--duration", type=int, default=40)
parser.add_argument("--voice", type=str, default="female-shaonv")
parser.add_argument("--output", type=str, default="e2e_output/v11b")
parser.add_argument("--stop-after-shot", type=int, default=None,
                    help="Stop after generating this shot number (e.g. 2)")
args = parser.parse_args()

DURATION, VOICE_ID, OUTPUT = args.duration, args.voice, args.output
for d in ["images", "scenes", "characters", "videos", "audio", "aligned", "frames"]:
    os.makedirs(f"{OUTPUT}/{d}", exist_ok=True)

from vendor.qwen.client import chat_with_system, _extract_json
from vendor.jimeng.t2i import generate_image
from vendor.kling.client import KlingClient
from app.services.ffmpeg_utils import (
    align_video_to_audio, concatenate_clips, overlay_bgm, get_media_duration
)
from app.services.narration_utils import shorten_narration_via_llm
import requests as http_requests

def log(msg): print(msg, flush=True)

def img_to_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def extract_last_frame(video_path, output_path):
    r = subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path, "-frames:v", "1", output_path],
        capture_output=True, timeout=10)
    return r.returncode == 0 and os.path.exists(output_path)

def calc_duration_from_narration(narration_text):
    """P0 fix: calculate duration from narration, accounting for pauses and interjections."""
    text = narration_text
    # Count pause markers like <#1.5#>
    pause_total = sum(float(m) for m in re.findall(r'<#([\d.]+)#>', text))
    # Count interjections like (sighs) (laughs)
    interjection_count = len(re.findall(r'\([^)]+\)', text))
    # Remove markers for char counting
    clean_text = re.sub(r'<#[\d.]+#>', '', text)
    clean_text = re.sub(r'\([^)]+\)', '', clean_text)
    char_count = len(clean_text.strip())
    # Base duration from char count
    base = math.ceil(char_count / 3.0) + 1
    extra = pause_total + interjection_count * 1.0
    # P0 fix: clamp to Kling V3 range
    return max(5, min(15, int(base + extra)))

NEGATIVE_PROMPT = (
    "blurry, low quality, distorted face, extra fingers, deformed, morphing, "
    "flickering, abrupt scene change, live action, photorealistic, "
    "text, watermark, signature, frame, border, "
    "style change, color shift, inconsistent character, extra limbs"
)

CAMERA_MAP = {
    "static": "camera remains still", "pan_left": "camera slowly pans left",
    "pan_right": "camera slowly pans right", "zoom_in": "camera slowly zooms in",
    "zoom_out": "camera slowly pulls back", "tilt_up": "camera tilts upward",
    "tilt_down": "camera tilts downward", "tracking": "camera follows the subject's movement",
    "dolly_in": "camera smoothly dollies forward", "orbit": "camera slowly orbits around",
}


# ============ STAGE 1: Storyboard ============
log(f"\n{'='*60}\n[Stage 1/8] Storyboard ({DURATION}s)...")

with open("data/test_novel.txt") as f:
    novel = f.read()

system_prompt = f"""你是一位顶级短剧导演兼编剧，擅长将小说文本改编为"解说类漫剧"短视频分镜。

## 你的任务
将原文改编为一部约 {DURATION} 秒的竖屏短视频分镜脚本。这是"旁白驱动"的漫剧——观众通过旁白听故事，画面配合营造氛围。

## 旁白写作（最核心）

旁白是整个视频的灵魂：

1. **保留原文精华**：经典对话、内心独白、氛围描写必须保留或改编进旁白
2. **讲故事而非描述画面**：不要"她走进大厅"，要"苏家破产，千金沦为秘书，她低头穿过嘲讽的目光"
3. **融入关键对话**：原文对话自然融入，如：'他低沉的声音响起——"好久不见。"'
4. **情感层次丰富**：每段旁白都有明确的情感基调
5. **每段旁白严格控制在20-30个汉字**

旁白示例：
- ❌ "苏念念低头走进大厅。"（纯画面描述）
- ✅ "苏家破产，千金沦为秘书，她低头穿过嘲讽的目光。"（有故事、有情感）
- ❌ "他站起来走向她。"（没有信息量）
- ✅ "他逼近，熟悉的木香让她心颤——三年了，他没变。"（有感官、有时间线）

## 时长计算规则
1. 先写好旁白（20-30字）
2. duration_seconds = ceil(字数 / 3.0) + 1
3. 所有 duration_seconds 总和应接近 {DURATION} 秒
4. 分镜数量 4-5 个

## 情绪标注
每个分镜需要指定 emotion 字段，用于TTS语音合成的情绪控制：
- happy: 开心/甜蜜    - sad: 悲伤/心痛
- angry: 愤怒/质问    - fearful: 紧张/恐惧
- surprised: 震惊     - calm: 平静叙述
- whisper: 低语/私密

## 角色设定
1. char_id 唯一标识，gender（male/female）
2. appearance_en 是"冻结标签"：极其详细的英文外貌描述（发色+发型+长度+刘海、瞳色、肤色、体型、上装材质颜色、下装、鞋子、饰品）
3. 每个 image_prompt 必须逐字复制 appearance_en
4. **【色彩要求】appearance_en 必须包含丰富的色彩描述，避免全黑灰色调**：
   - 眼睛用具体色彩：deep dark brown eyes / warm amber eyes（不要只写 black eyes）
   - 肤色用暖色调：light warm-toned skin / fair skin with warm undertone（不要写 cold pale skin）
   - 服装要有色彩对比：如西装角色加上领带颜色、衬衫细节等
   - 这是因为AI生图模型在全黑灰描述下容易生成黑白风格图片

## image_prompt 规则
顺序：画质词 + 风格词 + 景别 + 角色外貌(逐字复制appearance_en) + 姿态表情 + 场景背景 + 光线

## video_prompt 规则（极其重要）
只描述【运动和动作】。绝对禁止外貌和场景描述（视频生成时传入参考图处理）。
- ✅ "the woman turns her head slowly, tears form, camera zooms in"
- ❌ "the woman with long black hair in the office turns"（含外貌/场景）
- ❌ "subtle animation"（太笼统）

**【P1约束】场景首镜的 video_prompt 必须包含角色动作动词**（walks in, enters, stands, appears 等），
确保视频中角色有明确的出场动作，而非只有镜头运动。

**【动作幅度约束】video_prompt 的动作幅度必须小且可控**：
- 每个分镜只有5-10秒，AI视频模型无法生成长距离移动（如"穿过整个大厅"）
- 动作超出范围会导致后半段回弹/倒退
- ✅ 好的: "the woman takes a few steps forward, then pauses"（小幅度，有起止）
- ✅ 好的: "the man slowly stands up from the chair"（单一动作）
- ❌ 坏的: "the woman walks fast through the entire hall"（距离太大，会回弹）
- ❌ 坏的: "the man runs across the room"（动作幅度超出视频长度）
- 镜头运动也要平缓: "camera slowly follows" 而非 "camera tracks forward fast"

**【双人/多人镜头约束 — 极其重要】**：
当 characters_in_shot 包含2个或以上角色时：
1. video_prompt 必须描述每一个在场角色的动作或状态，不能只写一个人
   - ✅ "the man lifts his head coldly, the woman clutches the folder and takes a step back"
   - ❌ "the man lifts his head"（只写了一个人，另一个会被镜头推出画面）
2. video_prompt 的镜头运动要适度，不要完全静止也不要大幅推近：
   - ✅ "camera very slowly pushes in on both characters"（适度运动，画面有活力）
   - ❌ "camera holds steady"（画面太死板，毫无动态）
   - ❌ "camera zooms in on the man's face"（会把另一个角色推出画面）
3. 双人镜头的动作描述要具体有力，不要过于保守：
   - ✅ "the man stands up sharply, the woman gasps and steps back"（具体、有张力）
   - ❌ "the man trembles slightly"（太弱，视频看不出动态）
4. 双人镜头的 duration_seconds 建议不超过8秒

**【角色体型约束】**：
- 男性角色的 appearance_en 必须强调成年男性的体型特征："tall imposing adult man", "broad shoulders", "towering over"
- 避免模糊描述导致AI将男性画成少年体型

## 输出格式
严格JSON：
```json
{{{{
  "title": "标题",
  "character_profiles": [
    {{{{ "char_id": "char_xxx", "name": "名", "gender": "female",
      "appearance": "中文外貌", "appearance_en": "FROZEN English tag" }}}}
  ],
  "scene_backgrounds": [
    {{{{ "scene_id": "scene_xxx", "name": "场景名",
      "description_en": "background desc, ending with 'manga style, anime background, no characters, no people'" }}}}
  ],
  "storyboards": [
    {{{{
      "shot_number": 1, "duration_seconds": 9,
      "scene_id": "scene_xxx", "characters_in_shot": ["char_xxx"],
      "shot_type": "medium shot",
      "image_prompt": "masterpiece, best quality, 4K, anime style, ...",
      "video_prompt": "motion only, must include character action verb for scene-first shots",
      "narration_text": "20-30字精彩旁白",
      "emotion": "calm",
      "narrator": "narrator",
      "scene_description": "中文",
      "camera_movement": "zoom_in",
      "transition": "cut"
    }}}}
  ]
}}}}
```

## 约束
1. 4-5个分镜，duration_seconds = ceil(旁白字数/3) + 1
2. 总时长接近 {DURATION}s
3. 旁白 20-30 字，讲故事、保留对话
4. video_prompt 纯动作，场景首镜必须含角色动作动词
5. 每镜指定 emotion
6. 只输出JSON"""

user_prompt = f"""请将以下小说改编为解说类漫剧短视频分镜脚本。

【重要】你是顶级导演，旁白要讲好故事。直接输出JSON，回复以 {{ 开头。

文本内容：
{novel}"""

raw = chat_with_system(system_prompt, user_prompt, max_tokens=8192)
sb = json.loads(_extract_json(raw))
shots = sb.get("storyboards", [])
chars = sb.get("character_profiles", [])
scenes = sb.get("scene_backgrounds", [])

# P0 fix: recalculate and clamp duration from narration
for s in shots:
    nt = s.get("narration_text", "")
    dur = calc_duration_from_narration(nt)
    # Multi-character shots: cap at 8s to reduce drift
    if len(s.get("characters_in_shot", [])) >= 2 and dur > 8:
        dur = 8
    s["duration_seconds"] = dur

# Validate narration length
for s in shots:
    nt = s.get("narration_text", "")
    max_chars = 30
    if len(nt) > max_chars:
        s["narration_text"] = shorten_narration_via_llm(nt, max_chars, s.get("scene_description", ""))
        s["duration_seconds"] = calc_duration_from_narration(s["narration_text"])

with open(f"{OUTPUT}/storyboard.json", "w") as f:
    json.dump(sb, f, ensure_ascii=False, indent=2)

total_dur = sum(s.get("duration_seconds", 0) for s in shots)
log(f"  {len(shots)} shots, {len(scenes)} scenes, {len(chars)} chars, total {total_dur}s")
for c in chars:
    log(f"  Char: {c['name']} ({c['char_id']}) {c.get('gender','?')}")
for s in shots:
    nt = s.get("narration_text", "")
    log(f"  Shot {s['shot_number']}: {s['duration_seconds']}s | {len(nt)}字 | emotion={s.get('emotion','?')} | chars={s.get('characters_in_shot',[])}")
    log(f"    旁白: \"{nt}\"")
    log(f"    video: \"{s.get('video_prompt','')[:90]}\"")


# ============ STAGE 2: Character Reference Images ============
log(f"\n[Stage 2/8] Character reference images...")

char_images = {}
for c in chars:
    cid = c["char_id"]
    gender = c.get("gender", "female")
    appearance = c.get("appearance_en", "")
    pose = ("neutral expression, standing straight, three-quarter view, arms relaxed, confident posture"
            if gender == "male" else
            "neutral expression, standing straight, three-quarter view, hands clasped, elegant posture")
    prompt = (
        "masterpiece, best quality, highly detailed, 4K, "
        "anime style, manga style, cel shading, vibrant colors, full color illustration, colorful, "
        "detailed illustration, character reference sheet, upper body portrait, from waist up, "
        f"{appearance}, {pose}, "
        "clean solid light gray background, studio lighting, "
        "no text, no watermark, sharp focus, no other characters, solo"
    )
    paths = generate_image(prompt, width=832, height=1472,
                           output_dir=f"{OUTPUT}/characters", prefix=f"charref_{cid}")
    if paths:
        char_images[cid] = paths[0]
        log(f"  {c['name']} ({cid}): ✓")
    time.sleep(3)


# ============ STAGE 3: Scene Background Images ============
log(f"\n[Stage 3/8] Scene background images...")

scene_images = {}
for sc in scenes:
    sid = sc["scene_id"]
    desc = sc.get("description_en", "")
    if "no characters" not in desc.lower():
        desc += ", manga style, anime background, no characters, no people"
    prompt = (
        "masterpiece, best quality, highly detailed, 4K, "
        "anime style, manga style, vibrant colors, detailed illustration, "
        f"wide establishing shot, {desc}, "
        "atmospheric perspective, detailed environment, no text, no watermark"
    )
    paths = generate_image(prompt, width=832, height=1472,
                           output_dir=f"{OUTPUT}/scenes", prefix=f"scenebg_{sid}")
    if paths:
        scene_images[sid] = paths[0]
        log(f"  {sid} ({sc['name']}): ✓")
    time.sleep(3)


# ============ STAGE 4: Smart First-Frame (scene-first only) ============
log(f"\n[Stage 4/8] First-frame generation (scene-first shots)...")

profiles_map = {c["char_id"]: c for c in chars}
scene_desc_map = {s["scene_id"]: s for s in scenes}

shot_plan = {}
prev_sid = None
for s in shots:
    sn, sid = s["shot_number"], s.get("scene_id", "")
    if sn == 1:
        shot_plan[sn] = "t2i"
    elif sid != prev_sid:
        shot_plan[sn] = "t2i"
    else:
        shot_plan[sn] = "last_frame"
    prev_sid = sid
    log(f"  Shot {sn}: {shot_plan[sn]}")

t2i_images = {}
for s in shots:
    sn = s["shot_number"]
    if shot_plan[sn] != "t2i":
        continue

    chars_in = s.get("characters_in_shot", [])
    sid = s.get("scene_id", "")
    sd = scene_desc_map.get(sid, {}).get("description_en", "")

    # Multi-char shots: generate SINGLE main character first frame only
    # Kling subject_reference will bring in the other characters
    if len(chars_in) >= 2:
        # Use the first character as the main subject for the first frame
        main_cid = chars_in[0]
        main_app = profiles_map.get(main_cid, {}).get("appearance_en", "")
        scene_brief = sd.replace("no characters, no people", "").strip(" ,.")
        prompt = (
            "masterpiece, best quality, highly detailed, 4K, "
            "anime style, manga style, cel shading, vibrant colors, detailed illustration, "
            f"medium shot, {main_app}, "
            f"standing at a doorway looking nervous, {scene_brief}, dramatic lighting"
        )
        log(f"  Shot {sn}: T2I single-char first-frame (main={main_cid}, multi-char shot)")
    else:
        # Single-char shot: use the original image_prompt
        base_prompt = s.get("image_prompt", "")
        missing = []
        for cid in chars_in:
            app = profiles_map.get(cid, {}).get("appearance_en", "")
            if app and app[:40].lower() not in base_prompt.lower():
                missing.append(app)
        parts = []
        if "masterpiece" not in base_prompt.lower():
            parts.append("masterpiece, best quality, highly detailed, 4K")
        if "anime style" not in base_prompt.lower():
            parts.append("anime style, manga style, cel shading, vibrant colors, detailed illustration")
        parts.append(base_prompt)
        for a in missing:
            parts.append(a)
        if sd and sd[:30].lower() not in base_prompt.lower():
            parts.append(f"background: {sd.replace('no characters, no people', '').strip(' ,.')}")
        prompt = ", ".join(parts)
        log(f"  Shot {sn}: T2I single-char first-frame")

    paths = generate_image(prompt, width=832, height=1472,
                           output_dir=f"{OUTPUT}/images", prefix=f"shot_{sn:02d}")
    if paths:
        t2i_images[sn] = paths[0]
        log(f"  Shot {sn} first-frame: ✓")
    time.sleep(3)


# ============ STAGE 5: Video Generation (Kling V3 + subject_reference) ============
log(f"\n[Stage 5/8] Video generation (Kling V3 + subject_reference)...")

kling = KlingClient()
shot_videos = {}
prev_last_frame = None

for idx, s in enumerate(shots):
    sn = s["shot_number"]
    duration = s.get("duration_seconds", 8)
    chars_in = s.get("characters_in_shot", [])
    sid = s.get("scene_id", "")

    log(f"\n  --- Shot {sn}/{len(shots)} ---")

    # STEP 1: Resolve first frame
    if shot_plan[sn] == "t2i":
        if sn not in t2i_images:
            log(f"  SKIP (no first-frame)"); prev_last_frame = None; continue
        first_frame_path = t2i_images[sn]
        log(f"  First frame: T2I ({first_frame_path})")
    else:
        if prev_last_frame and os.path.exists(prev_last_frame):
            first_frame_path = prev_last_frame
            log(f"  First frame: last-frame continuity")
        else:
            log(f"  Last-frame unavailable, generating T2I fallback...")
            bp = s.get("image_prompt", "")
            paths = generate_image(bp, width=832, height=1472,
                                   output_dir=f"{OUTPUT}/images", prefix=f"shot_{sn:02d}_fb")
            if not paths:
                log(f"  SKIP"); prev_last_frame = None; continue
            first_frame_path = paths[0]; time.sleep(3)

    # STEP 2: subject_reference = character refs ONLY (P0: no scene bg)
    subject_ref = []
    for cid in chars_in:
        if cid in char_images:
            subject_ref.append({"image": img_to_b64(char_images[cid])})
            log(f"    + char ref: {cid}")
    log(f"  subject_reference: {len(subject_ref)} char refs")

    # STEP 3: Motion prompt (motion-only)
    vp = s.get("video_prompt", "")
    cam = s.get("camera_movement", "static")
    motion_parts = []
    if vp:
        motion_parts.append(vp)
    else:
        motion_parts.append("subtle character animation, gentle breathing, slight weight shift")
    if "camera" not in vp.lower():
        motion_parts.append(CAMERA_MAP.get(cam, "camera remains still"))
    motion_parts.append("hair sways gently, cloth physics, anime style, smooth animation")
    motion_prompt = ", ".join(motion_parts)
    log(f"  Motion: {motion_prompt[:100]}...")

    # STEP 4: P0 fix — clamp duration
    kling_duration = str(max(5, min(15, duration)))
    log(f"  Duration: {kling_duration}s")

    # STEP 5: Call Kling V3 with retry (P1 fix)
    first_b64 = img_to_b64(first_frame_path)

    resp = None
    for attempt in range(2):  # P1: 1 retry
        try:
            resp = kling.generate_video(
                image=first_b64,
                prompt=motion_prompt,
                model_name="kling-v3",
                mode="std",
                duration=kling_duration,
                aspect_ratio="9:16",
                negative_prompt=NEGATIVE_PROMPT,
                cfg_scale=0.5,
                subject_reference=subject_ref if subject_ref else None,
            )
        except Exception as e:
            log(f"  Attempt {attempt+1} error: {e}")
            if attempt == 0:
                time.sleep(10); continue
            else:
                break

        code = resp.get("code", -1) if resp else -1
        if code == 1303:  # parallel limit
            log(f"  Parallel limit, waiting 90s...")
            time.sleep(90); continue
        elif code == 0:
            break
        else:
            log(f"  Attempt {attempt+1} failed: code={code} msg={resp.get('message','')}")
            if attempt == 0:
                time.sleep(10); continue

    if not resp or resp.get("code") != 0:
        log(f"  FAILED after retries"); prev_last_frame = None; continue

    task_id = resp["data"]["task_id"]
    log(f"  Task: {task_id}, polling...")
    data = kling.poll_task(task_id, task_type="video", max_wait=600, interval=10)
    if not data:
        log(f"  Poll failed"); prev_last_frame = None; continue

    videos = data.get("task_result", {}).get("videos", [])
    if not videos or not videos[0].get("url"):
        log(f"  No video URL"); prev_last_frame = None; continue

    video_path = f"{OUTPUT}/videos/shot_{sn:02d}.mp4"
    r = http_requests.get(videos[0]["url"], timeout=120)
    with open(video_path, "wb") as f:
        f.write(r.content)
    shot_videos[sn] = video_path
    dur_v = get_media_duration(video_path)
    sz = os.path.getsize(video_path) / 1024 / 1024

    lf_path = f"{OUTPUT}/frames/shot_{sn:02d}_lastframe.png"
    if extract_last_frame(video_path, lf_path):
        prev_last_frame = lf_path
        log(f"  ✓ Shot {sn}: {dur_v:.1f}s, {sz:.1f}MB (last-frame saved)")
    else:
        prev_last_frame = None
        log(f"  ✓ Shot {sn}: {dur_v:.1f}s, {sz:.1f}MB (no last-frame)")

    # Stop after specified shot
    if args.stop_after_shot and sn >= args.stop_after_shot:
        log(f"\n{'='*60}")
        log(f"★ Stopped after Shot {sn}. Generated {len(shot_videos)} videos.")
        log(f"  Review: {OUTPUT}/videos/")
        log(f"  Re-run without --stop-after-shot to continue.")
        log(f"{'='*60}")
        sys.exit(0)

    time.sleep(5)

log(f"\n  {len(shot_videos)}/{len(shots)} videos generated")


# ============ STAGE 6: TTS (with per-shot emotion) ============
log(f"\n[Stage 6/8] TTS (emotion-aware)...")

async def gen_tts():
    from app.ai.providers.minimax_tts import MiniMaxTTSProvider
    provider = MiniMaxTTSProvider()
    paths = {}
    for s in shots:
        sn = s["shot_number"]
        text = s.get("narration_text", "")
        if not text: continue
        emotion = s.get("emotion", "calm")
        # Validate emotion against MiniMax supported values
        valid_emotions = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "fluent", "whisper"}
        if emotion not in valid_emotions:
            emotion = "calm"
        job_id = await provider.submit_job({
            "text": text, "voice_id": VOICE_ID, "speed": 0.9, "emotion": emotion,
        })
        status = await provider.poll_job(job_id)
        if status.result_data:
            path = f"{OUTPUT}/audio/shot_{sn:02d}.mp3"
            with open(path, "wb") as f: f.write(status.result_data)
            paths[sn] = path
            log(f"  Shot {sn}: ✓ (emotion={emotion})")
        await asyncio.sleep(1)
    return paths

tts_paths = asyncio.run(gen_tts())


# ============ STAGE 7: Assembly (with subtitles + BGM) ============
log(f"\n[Stage 7/8] Assembly...")

# Step 7a: Align video to audio
aligned = []
for s in shots:
    sn = s["shot_number"]
    if sn not in shot_videos or sn not in tts_paths: continue
    out = f"{OUTPUT}/aligned/shot_{sn:02d}.mp4"
    ok = align_video_to_audio(shot_videos[sn], tts_paths[sn], out)
    if ok:
        vd = get_media_duration(shot_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        fd = get_media_duration(out)
        log(f"  Shot {sn}: v={vd:.1f}s a={ad:.1f}s → {fd:.1f}s ✓")
        aligned.append(os.path.abspath(out))

# Step 7b: Concatenate
concat = os.path.abspath(f"{OUTPUT}/concat_no_bgm.mp4")
concatenate_clips(aligned, concat)
log(f"  Concat: {get_media_duration(concat):.1f}s")

# Step 7c: P1 fix — Add subtitles
log(f"  Adding subtitles...")
# BUG1 fix: only emit SRT for shots whose aligned clip made it into the concat
aligned_shots = set()
for s in shots:
    sn = s["shot_number"]
    aligned_path = f"{OUTPUT}/aligned/shot_{sn:02d}.mp4"
    if os.path.abspath(aligned_path) in aligned:
        aligned_shots.add(sn)

srt_path = os.path.abspath(f"{OUTPUT}/subtitles.srt")
current_time = 0.0
srt_entries = []
for s in shots:
    sn = s["shot_number"]
    if sn not in aligned_shots: continue
    ad = get_media_duration(tts_paths[sn])
    start_h, start_m = divmod(int(current_time), 3600)
    start_m, start_s = divmod(start_m, 60)
    start_ms = int((current_time % 1) * 1000)
    end_time = current_time + ad
    end_h, end_m = divmod(int(end_time), 3600)
    end_m, end_s = divmod(end_m, 60)
    end_ms = int((end_time % 1) * 1000)
    nt = s.get("narration_text", "")
    srt_entries.append(
        f"{len(srt_entries)+1}\n"
        f"{start_h:02d}:{start_m:02d}:{start_s:02d},{start_ms:03d} --> "
        f"{end_h:02d}:{end_m:02d}:{end_s:02d},{end_ms:03d}\n"
        f"{nt}\n"
    )
    current_time = end_time

with open(srt_path, "w", encoding="utf-8") as f:
    f.write("\n".join(srt_entries))

# Burn subtitles into video
concat_sub = os.path.abspath(f"{OUTPUT}/concat_with_sub.mp4")
sub_result = subprocess.run([
    "ffmpeg", "-y", "-i", concat,
    "-vf", f"subtitles={srt_path}:force_style='FontSize=16,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=2,Alignment=2,MarginV=40'",
    "-c:a", "copy", concat_sub
], capture_output=True, text=True, timeout=120)
if sub_result.returncode == 0:
    log(f"  Subtitles: ✓")
else:
    log(f"  Subtitles failed, using no-subtitle version")
    concat_sub = concat

# Step 7d: Overlay BGM (P2: volume 0.25)
final = os.path.abspath(f"{OUTPUT}/final_video.mp4")
bgm = os.path.abspath("data/bgm/romantic_sweet.mp3")
overlay_bgm(concat_sub, bgm, final, bgm_volume=0.25)
dur = get_media_duration(final)
size = os.path.getsize(final) / 1024 / 1024
log(f"  Final: {dur:.1f}s, {size:.1f}MB")


# ============ STAGE 8: Quality Gate ============
log(f"\n{'='*60}\n[Stage 8/8] Quality gate...")
issues = []

if dur < DURATION * 0.5:
    issues.append(f"Duration {dur:.0f}s < 50% of target {DURATION}s")

for s in shots:
    sn = s["shot_number"]
    if sn in shot_videos and sn in tts_paths:
        vd = get_media_duration(shot_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        if ad > vd + 1.5:
            issues.append(f"Shot {sn}: freeze risk (TTS={ad:.1f}s > video={vd:.1f}s)")

# BGM check
sample = str(min(15, dur / 2))
r_c = subprocess.run(["ffmpeg", "-i", concat, "-ss", sample, "-t", "3", "-af", "volumedetect", "-f", "null", "-"],
    capture_output=True, text=True, timeout=10)
r_f = subprocess.run(["ffmpeg", "-i", final, "-ss", sample, "-t", "3", "-af", "volumedetect", "-f", "null", "-"],
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
    log(f"  BGM ✓ (diff={diff:.1f}dB)")

if len(shot_videos) < len(shots):
    issues.append(f"Missing videos: {len(shot_videos)}/{len(shots)}")

# Continuity check
prev_sid = None
for s in shots:
    sn = s["shot_number"]
    sid = s.get("scene_id", "")
    if prev_sid and sid == prev_sid:
        lf = f"{OUTPUT}/frames/shot_{sn-1:02d}_lastframe.png"
        status = "✓" if os.path.exists(lf) else "⚠ missing"
        log(f"  Shot {sn-1}→{sn}: same scene, last-frame {status}")
    elif prev_sid:
        log(f"  Shot {sn-1}→{sn}: scene change ✓")
    prev_sid = sid

if issues:
    log(f"\n  ⚠ ISSUES ({len(issues)}):")
    for i in issues: log(f"    - {i}")
    log(f"  Quality gate: FAILED")
else:
    log(f"\n  ✓ Quality gate: PASSED")

log(f"\n{'='*60}")
log(f"★ {OUTPUT}/final_video.mp4 ({dur:.1f}s, {size:.1f}MB)")
log(f"{'='*60}")
