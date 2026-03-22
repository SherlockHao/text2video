"""
E2E v11b: Sub-shot splitting pipeline
======================================
Core change: Decouple narration from video segments.
  - Each "segment" has ONE narration (20-30 chars) and 2-3 sub-shots (5s each)
  - Sub-shots use different shot_types (中景→特写→远景) for cinematic variety
  - TTS per segment, video per sub-shot, assembly stitches them together
  - All prompts in Chinese

Stages:
  1: LLM Storyboard (Qwen) — segments with sub-shots
  2: Character Reference Images (Jimeng T2I) → subject_reference
  3: Scene Background Images (Jimeng T2I) → review only
  4: First-Frame Images (Jimeng T2I, scene-first sub-shots) → image
  5: Video Generation (Kling V3 I2V, 5s per sub-shot)
  6: TTS (MiniMax, per-segment emotion)
  7: Assembly (sub-shots → segment → align with TTS → concat → subtitles → BGM)
  8: Quality Gate
"""

import json, os, sys, time, asyncio, argparse, subprocess, base64, math, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

parser = argparse.ArgumentParser()
parser.add_argument("--duration", type=int, default=40)
parser.add_argument("--voice", type=str, default="female-shaonv")
parser.add_argument("--output", type=str, default="e2e_output/v11b")
parser.add_argument("--stop-after-segment", type=int, default=None,
                    help="Stop after generating this segment number (e.g. 2)")
args = parser.parse_args()

DURATION, VOICE_ID, OUTPUT = args.duration, args.voice, args.output
for d in ["images", "scenes", "characters", "videos", "audio", "aligned", "frames", "segments"]:
    os.makedirs(f"{OUTPUT}/{d}", exist_ok=True)

from vendor.qwen.client import chat_with_system, _extract_json
from vendor.jimeng.t2i import generate_image
from vendor.kling.client import KlingClient
from app.services.ffmpeg_utils import (
    align_video_to_audio, concatenate_clips, overlay_bgm, get_media_duration
)
from app.services.narration_utils import shorten_narration_via_llm
import requests as http_requests

SUB_SHOT_DURATION = 5  # 每个子镜头固定5秒

def log(msg): print(msg, flush=True)

def img_to_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def extract_last_frame(video_path, output_path):
    r = subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path, "-frames:v", "1", output_path],
        capture_output=True, timeout=10)
    return r.returncode == 0 and os.path.exists(output_path)

def estimate_tts_duration(text):
    """估算TTS音频时长（秒），基于中文字数。"""
    clean = re.sub(r'<#[\d.]+#>', '', text)
    clean = re.sub(r'\([^)]+\)', '', clean)
    pause_total = sum(float(m) for m in re.findall(r'<#([\d.]+)#>', text))
    interjection_count = len(re.findall(r'\([^)]+\)', text))
    char_count = len(clean.strip())
    return char_count / 3.0 + 1 + pause_total + interjection_count * 1.0

NEGATIVE_PROMPT = (
    "模糊, 低质量, 面部扭曲, 多余手指, 变形, 形变, "
    "闪烁, 突然切换场景, 真人实拍, 写实风格, "
    "文字, 水印, 签名, 边框, "
    "风格突变, 色彩偏移, 角色不一致, 多余肢体"
)

CAMERA_MAP = {
    "static": "镜头保持不动", "pan_left": "镜头缓慢向左平移",
    "pan_right": "镜头缓慢向右平移", "zoom_in": "镜头缓慢推近",
    "zoom_out": "镜头缓慢拉远", "tilt_up": "镜头缓慢上摇",
    "tilt_down": "镜头缓慢下摇", "tracking": "镜头跟随主体移动",
    "dolly_in": "镜头平滑向前推进", "orbit": "镜头缓慢环绕",
}


# ============ STAGE 1: Storyboard ============
log(f"\n{'='*60}\n[Stage 1/8] Storyboard ({DURATION}s)...")

with open("data/test_novel.txt") as f:
    novel = f.read()

system_prompt = f"""你是一位顶级短剧导演兼编剧，擅长将小说文本改编为"解说类漫剧"短视频分镜。

## 你的任务
将原文改编为一部约 {DURATION} 秒的竖屏短视频分镜脚本。这是"旁白驱动"的漫剧——观众通过旁白听故事，画面配合营造氛围。

## 核心架构：叙事段 + 子镜头

每个"叙事段"(segment) 包含：
- 一段旁白（20-30字），连续播放
- 2-3个子镜头(sub_shots)，每个子镜头5秒，用不同景别和角度切换

这样做的好处：
1. 旁白可以保持丰富自然，不用压缩
2. 每个子镜头只有5秒，视频生成质量最优
3. 多角度切换更有影视感

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

## 子镜头数量规则
1. 先写好旁白（20-30字）
2. 估算旁白TTS时长 ≈ ceil(字数 / 3) + 1 秒
3. 子镜头数量 = ceil(TTS时长 / 5)，通常为2个
4. 所有叙事段的 子镜头数×5秒 之和应接近 {DURATION} 秒
5. 叙事段数量 4-5 个

## 子镜头设计规则（极其重要）

同一叙事段内的子镜头：
1. **景别必须不同**：相邻子镜头切换景别，制造影视节奏感
   - 好的组合：中景→特写、远景→中景、中景→近景特写
   - 避免：中景→中景（无变化）
2. **动作连贯但视角变化**：
   - 子镜头1: "女子快步走来，低头攥紧文件夹"（中景，跟随）
   - 子镜头2: "女子抬起头，眼中一闪不安"（面部特写，推近）
3. **每个子镜头只描述5秒能完成的小动作**

## 情绪标注
每个叙事段指定 emotion 字段，用于TTS语音合成的情绪控制：
- happy: 开心/甜蜜    - sad: 悲伤/心痛
- angry: 愤怒/质问    - fearful: 紧张/恐惧
- surprised: 震惊     - calm: 平静叙述
- whisper: 低语/私密

## 角色设定
1. char_id 唯一标识，gender（male/female）
2. appearance_prompt 是"冻结标签"：极其详细的中文外貌描述（发色+发型+长度+刘海、瞳色、肤色、体型、上装材质颜色、下装、鞋子、饰品）
3. **【色彩要求】appearance_prompt 必须包含丰富的色彩描述，避免全黑灰色调**：
   - 眼睛用具体色彩：深棕色眼眸 / 温暖琥珀色眼睛（不要只写"黑色眼睛"）
   - 肤色用暖色调：暖白肤色 / 白皙暖色调皮肤（不要写"冷白皮肤"）
   - 服装要有色彩对比：如西装角色加上领带颜色、衬衫细节等

**【角色体型约束】**：
- 男性角色的 appearance_prompt 必须强调成年男性的体型特征："高大威严的成年男性"、"宽阔的肩膀"、"身材高挑"

## image_prompt 规则（仅第一个子镜头需要）
顺序：画质词 + 风格词 + 景别 + 角色外貌(逐字复制appearance_prompt) + 姿态表情 + 场景背景 + 光线

## video_prompt 规则（每个子镜头都需要）
只描述【运动和动作】。绝对禁止外貌和场景描述（视频生成时传入参考图处理）。
- ✅ "女子缓缓转头，眼中泛起泪光，镜头缓慢推近"
- ❌ "长黑发的女子在办公室里转头"（含外貌/场景）

**【动作幅度约束】每个子镜头只有5秒，动作必须小且可控**：
- ✅ "女子向前迈出两步，然后停住"（小幅度，有起止）
- ✅ "男子缓缓从椅子上站起"（单一动作）
- ❌ "女子快速穿过整个大厅"（5秒内无法完成）

**【双人/多人镜头约束】**：
当 characters_in_shot 包含2个或以上角色时：
1. video_prompt 必须描述每一个在场角色的动作或状态
   - ✅ "男子冷冷抬头，女子攥紧文件夹后退一步"
   - ❌ "男子抬头"（另一个角色会被推出画面）
2. 镜头运动适度，不要大幅推近单人（会推出另一角色）

## 输出格式
严格JSON，所有prompt字段均使用中文：
```json
{{{{
  "title": "标题",
  "character_profiles": [
    {{{{ "char_id": "char_xxx", "name": "名", "gender": "female",
      "appearance": "中文外貌概述", "appearance_prompt": "冻结中文外貌标签，极其详细" }}}}
  ],
  "scene_backgrounds": [
    {{{{ "scene_id": "scene_xxx", "name": "场景名",
      "scene_prompt": "中文场景描述，以'漫画风格，动漫背景，无人物'结尾" }}}}
  ],
  "segments": [
    {{{{
      "segment_number": 1,
      "scene_id": "scene_xxx",
      "characters_in_shot": ["char_xxx"],
      "narration_text": "20-30字精彩旁白",
      "emotion": "sad",
      "scene_description": "中文场景描述",
      "image_prompt": "杰作, 最高质量, 4K, 动漫风格, ...(该段第一个子镜头的首帧生图提示词)",
      "sub_shots": [
        {{{{
          "shot_type": "中景",
          "video_prompt": "纯动作+镜头运动，5秒可完成",
          "camera_movement": "tracking"
        }}}},
        {{{{
          "shot_type": "面部特写",
          "video_prompt": "纯动作+镜头运动，5秒可完成",
          "camera_movement": "zoom_in"
        }}}}
      ]
    }}}}
  ]
}}}}
```

## 约束
1. 4-5个叙事段，每段2-3个子镜头（每个5秒）
2. 总子镜头数 × 5秒 ≈ {DURATION}s
3. 旁白 20-30 字，讲故事、保留对话
4. 相邻子镜头景别必须不同
5. video_prompt 纯动作（中文），场景首段的第一个子镜头必须含角色动作动词
6. 每段指定 emotion
7. 所有 prompt 字段使用中文
8. 只输出JSON"""

user_prompt = f"""请将以下小说改编为解说类漫剧短视频分镜脚本。

【重要】你是顶级导演，旁白要讲好故事。直接输出JSON，回复以 {{ 开头。

文本内容：
{novel}"""

raw = chat_with_system(system_prompt, user_prompt, max_tokens=8192)
sb = json.loads(_extract_json(raw))
segments = sb.get("segments", [])
chars = sb.get("character_profiles", [])
scenes = sb.get("scene_backgrounds", [])

# 验证并修正子镜头数量
for seg in segments:
    nt = seg.get("narration_text", "")
    # 旁白超长则压缩
    if len(nt) > 30:
        seg["narration_text"] = shorten_narration_via_llm(nt, 30, seg.get("scene_description", ""))
        nt = seg["narration_text"]
    # 根据旁白时长计算需要的子镜头数
    tts_est = estimate_tts_duration(nt)
    needed = max(1, math.ceil(tts_est / SUB_SHOT_DURATION))
    subs = seg.get("sub_shots", [])
    # 如果LLM给的子镜头数不够，复制最后一个并调整景别
    while len(subs) < needed:
        last = subs[-1].copy() if subs else {
            "shot_type": "特写", "video_prompt": "角色微妙动态，轻微呼吸",
            "camera_movement": "zoom_in"
        }
        # 交替景别
        alt_types = ["中景", "特写", "近景", "远景"]
        used = last.get("shot_type", "中景")
        for t in alt_types:
            if t != used:
                last["shot_type"] = t
                break
        subs.append(last)
    seg["sub_shots"] = subs

with open(f"{OUTPUT}/storyboard.json", "w") as f:
    json.dump(sb, f, ensure_ascii=False, indent=2)

# 构建全局子镜头列表（用于后续Stage引用）
all_sub_shots = []  # [(seg_idx, sub_idx, seg, sub)]
for seg_idx, seg in enumerate(segments):
    for sub_idx, sub in enumerate(seg.get("sub_shots", [])):
        all_sub_shots.append((seg_idx, sub_idx, seg, sub))

total_subs = len(all_sub_shots)
total_video_dur = total_subs * SUB_SHOT_DURATION

log(f"  {len(segments)} segments, {total_subs} sub-shots, {len(scenes)} scenes, {len(chars)} chars")
log(f"  预计视频总时长: {total_video_dur}s")
for c in chars:
    log(f"  Char: {c['name']} ({c['char_id']}) {c.get('gender','?')}")
for seg in segments:
    sn = seg["segment_number"]
    nt = seg.get("narration_text", "")
    subs = seg.get("sub_shots", [])
    tts_est = estimate_tts_duration(nt)
    log(f"  Seg {sn}: {len(subs)}个子镜头 | {len(nt)}字 | TTS≈{tts_est:.0f}s | emotion={seg.get('emotion','?')} | chars={seg.get('characters_in_shot',[])}")
    log(f"    旁白: \"{nt}\"")
    for i, sub in enumerate(subs):
        log(f"    子镜头{i+1}: {sub.get('shot_type','')} | {sub.get('video_prompt','')[:60]}")


# ============ STAGE 2: Character Reference Images ============
log(f"\n[Stage 2/8] Character reference images...")

char_images = {}
for c in chars:
    cid = c["char_id"]
    gender = c.get("gender", "female")
    appearance = c.get("appearance_prompt", "")
    pose = ("面无表情，笔直站立，四分之三侧面，双臂自然放松，自信姿态"
            if gender == "male" else
            "面无表情，笔直站立，四分之三侧面，双手交叠，优雅姿态")
    prompt = (
        "杰作, 最高质量, 高度精细, 4K, "
        "动漫风格, 漫画风格, 赛璐璐上色, 鲜艳色彩, 全彩插画, 色彩丰富, "
        "精细插画, 角色设定图, 上半身肖像, 腰部以上, "
        f"{appearance}, {pose}, "
        "纯净浅灰色背景, 摄影棚灯光, "
        "无文字, 无水印, 高清锐利, 无其他角色, 单人"
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
    desc = sc.get("scene_prompt", "")
    if "无人物" not in desc:
        desc += ", 漫画风格, 动漫背景, 无人物, 无角色"
    prompt = (
        "杰作, 最高质量, 高度精细, 4K, "
        "动漫风格, 漫画风格, 鲜艳色彩, 精细插画, "
        f"远景全景, {desc}, "
        "空气透视, 精细环境, 无文字, 无水印"
    )
    paths = generate_image(prompt, width=832, height=1472,
                           output_dir=f"{OUTPUT}/scenes", prefix=f"scenebg_{sid}")
    if paths:
        scene_images[sid] = paths[0]
        log(f"  {sid} ({sc['name']}): ✓")
    time.sleep(3)


# ============ STAGE 4: First-Frame (scene-first sub-shots only) ============
log(f"\n[Stage 4/8] First-frame generation...")

profiles_map = {c["char_id"]: c for c in chars}
scene_desc_map = {s["scene_id"]: s for s in scenes}

# 确定每个子镜头的首帧策略
# 规则：每个叙事段的第一个子镜头 = 场景首段用T2I，同场景后续段用last_frame
#       段内后续子镜头 = 上一个子镜头的末尾帧（last_frame）
sub_shot_plan = []  # 与 all_sub_shots 对应
prev_sid = None
for seg_idx, sub_idx, seg, sub in all_sub_shots:
    sid = seg.get("scene_id", "")
    if sub_idx == 0:
        # 叙事段的第一个子镜头
        if seg_idx == 0:
            sub_shot_plan.append("t2i")  # 第一段必须T2I
        elif sid != prev_sid:
            sub_shot_plan.append("t2i")  # 场景切换
        else:
            sub_shot_plan.append("last_frame")  # 同场景后续段
        prev_sid = sid
    else:
        # 段内后续子镜头 = 上一个子镜头的末尾帧
        sub_shot_plan.append("last_frame")

for i, (seg_idx, sub_idx, seg, sub) in enumerate(all_sub_shots):
    log(f"  Seg{seg['segment_number']}-Sub{sub_idx+1}: {sub_shot_plan[i]}")

# 生成需要T2I的首帧图
t2i_images = {}  # key = global sub-shot index
for i, (seg_idx, sub_idx, seg, sub) in enumerate(all_sub_shots):
    if sub_shot_plan[i] != "t2i":
        continue

    chars_in = seg.get("characters_in_shot", [])
    sid = seg.get("scene_id", "")
    sd = scene_desc_map.get(sid, {}).get("scene_prompt", "")

    if len(chars_in) >= 2:
        main_cid = chars_in[0]
        main_app = profiles_map.get(main_cid, {}).get("appearance_prompt", "")
        scene_brief = sd.replace("无人物, 无角色", "").replace("no characters, no people", "").strip(" ,.")
        prompt = (
            "杰作, 最高质量, 高度精细, 4K, "
            "动漫风格, 漫画风格, 赛璐璐上色, 鲜艳色彩, 精细插画, "
            f"中景, {main_app}, "
            f"站在门口神情紧张, {scene_brief}, 戏剧性光影"
        )
        log(f"  Seg{seg['segment_number']}-Sub{sub_idx+1}: T2I (main={main_cid}, multi-char)")
    else:
        # 使用 segment 的 image_prompt
        base_prompt = seg.get("image_prompt", "")
        missing = []
        for cid in chars_in:
            app = profiles_map.get(cid, {}).get("appearance_prompt", "")
            if app and app[:20] not in base_prompt:
                missing.append(app)
        parts = []
        if "杰作" not in base_prompt:
            parts.append("杰作, 最高质量, 高度精细, 4K")
        if "动漫风格" not in base_prompt:
            parts.append("动漫风格, 漫画风格, 赛璐璐上色, 鲜艳色彩, 精细插画")
        parts.append(base_prompt)
        for a in missing:
            parts.append(a)
        if sd and sd[:20] not in base_prompt:
            parts.append(f"背景: {sd.replace('无人物, 无角色', '').replace('no characters, no people', '').strip(' ,.')}")
        prompt = ", ".join(parts)
        log(f"  Seg{seg['segment_number']}-Sub{sub_idx+1}: T2I single-char")

    sn = seg["segment_number"]
    paths = generate_image(prompt, width=832, height=1472,
                           output_dir=f"{OUTPUT}/images", prefix=f"seg{sn:02d}_sub{sub_idx+1:02d}")
    if paths:
        t2i_images[i] = paths[0]
        log(f"  Seg{sn}-Sub{sub_idx+1} first-frame: ✓")
    time.sleep(3)


# ============ STAGE 5: Video Generation (Kling V3, 5s per sub-shot) ============
log(f"\n[Stage 5/8] Video generation (Kling V3, {SUB_SHOT_DURATION}s per sub-shot)...")

kling = KlingClient()
sub_shot_videos = {}  # key = global sub-shot index
prev_last_frame = None
total_generated = 0

for i, (seg_idx, sub_idx, seg, sub) in enumerate(all_sub_shots):
    sn = seg["segment_number"]
    chars_in = seg.get("characters_in_shot", [])

    log(f"\n  --- Seg{sn}-Sub{sub_idx+1} ({i+1}/{total_subs}) ---")

    # STEP 1: 确定首帧
    if sub_shot_plan[i] == "t2i":
        if i not in t2i_images:
            log(f"  SKIP (no first-frame)"); prev_last_frame = None; continue
        first_frame_path = t2i_images[i]
        log(f"  First frame: T2I ({first_frame_path})")
    else:
        if prev_last_frame and os.path.exists(prev_last_frame):
            first_frame_path = prev_last_frame
            log(f"  First frame: last-frame continuity")
        else:
            log(f"  Last-frame unavailable, generating T2I fallback...")
            bp = seg.get("image_prompt", "")
            if not bp:
                bp = "杰作, 动漫风格, 角色站立"
            paths = generate_image(bp, width=832, height=1472,
                                   output_dir=f"{OUTPUT}/images", prefix=f"seg{sn:02d}_sub{sub_idx+1:02d}_fb")
            if not paths:
                log(f"  SKIP"); prev_last_frame = None; continue
            first_frame_path = paths[0]; time.sleep(3)

    # STEP 2: subject_reference = 角色参考图
    subject_ref = []
    for cid in chars_in:
        if cid in char_images:
            subject_ref.append({"image": img_to_b64(char_images[cid])})
            log(f"    + char ref: {cid}")
    log(f"  subject_reference: {len(subject_ref)} char refs")

    # STEP 3: Motion prompt
    vp = sub.get("video_prompt", "")
    cam = sub.get("camera_movement", "static")
    motion_parts = []
    if vp:
        motion_parts.append(vp)
    else:
        motion_parts.append("角色微妙动态, 轻微呼吸, 细微重心转移")
    if "镜头" not in vp:
        motion_parts.append(CAMERA_MAP.get(cam, "镜头保持不动"))
    motion_parts.append("发丝轻轻飘动, 衣物物理效果, 动漫风格, 流畅动画")
    motion_prompt = ", ".join(motion_parts)
    log(f"  Motion: {motion_prompt[:100]}...")
    log(f"  Duration: {SUB_SHOT_DURATION}s | Shot type: {sub.get('shot_type', '?')}")

    # STEP 4: 调用 Kling V3
    first_b64 = img_to_b64(first_frame_path)

    resp = None
    for attempt in range(2):
        try:
            resp = kling.generate_video(
                image=first_b64,
                prompt=motion_prompt,
                model_name="kling-v3",
                mode="std",
                duration=str(SUB_SHOT_DURATION),
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
        if code == 1303:
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

    video_path = f"{OUTPUT}/videos/seg{sn:02d}_sub{sub_idx+1:02d}.mp4"
    r = http_requests.get(videos[0]["url"], timeout=120)
    with open(video_path, "wb") as f:
        f.write(r.content)
    sub_shot_videos[i] = video_path
    total_generated += 1
    dur_v = get_media_duration(video_path)
    sz = os.path.getsize(video_path) / 1024 / 1024

    lf_path = f"{OUTPUT}/frames/seg{sn:02d}_sub{sub_idx+1:02d}_lastframe.png"
    if extract_last_frame(video_path, lf_path):
        prev_last_frame = lf_path
        log(f"  ✓ Seg{sn}-Sub{sub_idx+1}: {dur_v:.1f}s, {sz:.1f}MB (last-frame saved)")
    else:
        prev_last_frame = None
        log(f"  ✓ Seg{sn}-Sub{sub_idx+1}: {dur_v:.1f}s, {sz:.1f}MB (no last-frame)")

    # 按段停止
    if args.stop_after_segment and sn >= args.stop_after_segment:
        # 检查是否是该段的最后一个子镜头
        is_last_sub = (sub_idx == len(seg.get("sub_shots", [])) - 1)
        if is_last_sub:
            log(f"\n{'='*60}")
            log(f"★ Stopped after Segment {sn}. Generated {total_generated} sub-shot videos.")
            log(f"  Review: {OUTPUT}/videos/")
            log(f"  Re-run without --stop-after-segment to continue.")
            log(f"{'='*60}")
            sys.exit(0)

    time.sleep(5)

log(f"\n  {total_generated}/{total_subs} sub-shot videos generated")


# ============ STAGE 6: TTS (per-segment emotion) ============
log(f"\n[Stage 6/8] TTS (emotion-aware, per segment)...")

async def gen_tts():
    from app.ai.providers.minimax_tts import MiniMaxTTSProvider
    provider = MiniMaxTTSProvider()
    paths = {}
    for seg in segments:
        sn = seg["segment_number"]
        text = seg.get("narration_text", "")
        if not text: continue
        emotion = seg.get("emotion", "calm")
        valid_emotions = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "fluent"}
        # whisper 映射为 calm（MiniMax 不支持 whisper）
        if emotion == "whisper":
            emotion = "calm"
        if emotion not in valid_emotions:
            emotion = "calm"
        job_id = await provider.submit_job({
            "text": text, "voice_id": VOICE_ID, "speed": 0.9, "emotion": emotion,
        })
        status = await provider.poll_job(job_id)
        if status.result_data:
            path = f"{OUTPUT}/audio/seg_{sn:02d}.mp3"
            with open(path, "wb") as f: f.write(status.result_data)
            paths[sn] = path
            log(f"  Seg {sn}: ✓ (emotion={emotion})")
        await asyncio.sleep(1)
    return paths

tts_paths = asyncio.run(gen_tts())


# ============ STAGE 7: Assembly ============
log(f"\n[Stage 7/8] Assembly...")

# Step 7a: 拼接每段的子镜头视频 → 段视频
segment_videos = {}
for seg in segments:
    sn = seg["segment_number"]
    subs = seg.get("sub_shots", [])
    sub_video_paths = []
    for sub_idx in range(len(subs)):
        # 找到该子镜头的全局索引
        global_idx = None
        for gi, (si, sbi, s, _) in enumerate(all_sub_shots):
            if s["segment_number"] == sn and sbi == sub_idx:
                global_idx = gi
                break
        if global_idx is not None and global_idx in sub_shot_videos:
            sub_video_paths.append(os.path.abspath(sub_shot_videos[global_idx]))

    if not sub_video_paths:
        log(f"  Seg {sn}: no sub-shot videos, skip")
        continue

    if len(sub_video_paths) == 1:
        # 只有一个子镜头，直接使用
        segment_videos[sn] = sub_video_paths[0]
        dur_s = get_media_duration(sub_video_paths[0])
        log(f"  Seg {sn}: 1 sub-shot → {dur_s:.1f}s ✓")
    else:
        # 拼接多个子镜头
        seg_concat = os.path.abspath(f"{OUTPUT}/segments/seg_{sn:02d}_concat.mp4")
        concatenate_clips(sub_video_paths, seg_concat)
        segment_videos[sn] = seg_concat
        dur_s = get_media_duration(seg_concat)
        log(f"  Seg {sn}: {len(sub_video_paths)} sub-shots → {dur_s:.1f}s ✓")

# Step 7b: 将段视频与TTS音频对齐
aligned = []
for seg in segments:
    sn = seg["segment_number"]
    if sn not in segment_videos or sn not in tts_paths:
        continue
    out = f"{OUTPUT}/aligned/seg_{sn:02d}.mp4"
    ok = align_video_to_audio(segment_videos[sn], tts_paths[sn], out)
    if ok:
        vd = get_media_duration(segment_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        fd = get_media_duration(out)
        log(f"  Seg {sn}: v={vd:.1f}s a={ad:.1f}s → {fd:.1f}s ✓")
        aligned.append(os.path.abspath(out))

# Step 7c: 拼接所有段
concat = os.path.abspath(f"{OUTPUT}/concat_no_bgm.mp4")
concatenate_clips(aligned, concat)
log(f"  Concat: {get_media_duration(concat):.1f}s")

# Step 7d: 添加字幕
log(f"  Adding subtitles...")
aligned_segs = set()
for seg in segments:
    sn = seg["segment_number"]
    aligned_path = f"{OUTPUT}/aligned/seg_{sn:02d}.mp4"
    if os.path.abspath(aligned_path) in aligned:
        aligned_segs.add(sn)

srt_path = os.path.abspath(f"{OUTPUT}/subtitles.srt")
current_time = 0.0
srt_entries = []
for seg in segments:
    sn = seg["segment_number"]
    if sn not in aligned_segs: continue
    ad = get_media_duration(tts_paths[sn])
    start_h, start_m = divmod(int(current_time), 3600)
    start_m, start_s = divmod(start_m, 60)
    start_ms = int((current_time % 1) * 1000)
    end_time = current_time + ad
    end_h, end_m = divmod(int(end_time), 3600)
    end_m, end_s = divmod(end_m, 60)
    end_ms = int((end_time % 1) * 1000)
    nt = seg.get("narration_text", "")
    srt_entries.append(
        f"{len(srt_entries)+1}\n"
        f"{start_h:02d}:{start_m:02d}:{start_s:02d},{start_ms:03d} --> "
        f"{end_h:02d}:{end_m:02d}:{end_s:02d},{end_ms:03d}\n"
        f"{nt}\n"
    )
    current_time = end_time

with open(srt_path, "w", encoding="utf-8") as f:
    f.write("\n".join(srt_entries))

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

# Step 7e: 叠加BGM
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

# 检查每段的TTS是否超过段视频时长（freeze风险已大大降低）
for seg in segments:
    sn = seg["segment_number"]
    if sn in segment_videos and sn in tts_paths:
        vd = get_media_duration(segment_videos[sn])
        ad = get_media_duration(tts_paths[sn])
        if ad > vd + 1.5:
            issues.append(f"Seg {sn}: freeze risk (TTS={ad:.1f}s > video={vd:.1f}s)")

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

if total_generated < total_subs:
    issues.append(f"Missing sub-shot videos: {total_generated}/{total_subs}")

# 连续性检查
prev_sid = None
for seg in segments:
    sn = seg["segment_number"]
    sid = seg.get("scene_id", "")
    if prev_sid and sid == prev_sid:
        log(f"  Seg {sn-1}→{sn}: same scene, last-frame continuity ✓")
    elif prev_sid:
        log(f"  Seg {sn-1}→{sn}: scene change ✓")
    prev_sid = sid

if issues:
    log(f"\n  ⚠ ISSUES ({len(issues)}):")
    for issue in issues: log(f"    - {issue}")
    log(f"  Quality gate: FAILED")
else:
    log(f"\n  ✓ Quality gate: PASSED")

log(f"\n{'='*60}")
log(f"★ {OUTPUT}/final_video.mp4 ({dur:.1f}s, {size:.1f}MB)")
log(f"{'='*60}")
