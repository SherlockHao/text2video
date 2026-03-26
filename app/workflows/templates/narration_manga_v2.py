"""
旁白漫剧 V2 工作流模板 — Narration-driven manga drama (V2)
单旁白音轨 + 9:16 竖屏 + 4×4 Gemini 宫格 + 串行视频生成 + 三层音频混合

10 Stages:
  1. storyboard        — LLM 分镜（含旁白剧本 + 角色档案）
  2. char_refs         — 角色三视图参考图 (Jimeng T2I)
  3. scene_refs        — 场景参考图 (Gemini + 角色参考)
  4. storyboard_grids  — 4×4 宫格分镜图 (Gemini 4K, 9:16 portrait)
  5. video_prompts     — 4K 切图 + LLM 分镜视频指令 (15段)
  6. narration_tts     — 单旁白 TTS + 时长校准
  7. video_gen         — Kling V3 image2video (serial, sound=on, 9:16)
  8. subtitle_burn     — 旁白字幕压制 (FFmpeg drawtext)
  9. assembly          — 720×1280 @30fps + 三层音频混合 + BGM
  10. quality_gate     — 质量检测
"""

import json
import math
import os
import re
import shutil
import subprocess
import time
import asyncio
import base64

import requests as http_requests

from app.workflows.base import BaseWorkflow, WorkflowContext, StageResult
from app.workflows.registry import register_workflow
from app.workflows.interactive import InteractiveOpsMixin
from app.workflows.templates._shared import (
    _resolve_cjk_font,
    _ffmpeg_safe_text,
    _strip_shot_labels,
    _detect_grid_panels,
    _validated_chat_json,
    _preprocess_bgm,
    _measure_mean_volume,
)
from vendor.qwen.client import chat_json
from vendor.jimeng.t2i import generate_image
from vendor.gemini.client import generate_image_with_refs

# ── 常量 ─────────────────────────────────────────────────────────

MAX_INPUT_LENGTH = 15000
LLM_MAX_RETRIES = 3

NEGATIVE_PROMPT = (
    "模糊, 低质量, 面部扭曲, 多余手指, 变形, 形变, "
    "闪烁, 突然切换场景, 真人实拍, 写实风格, "
    "文字, 水印, 签名, 边框, "
    "风格突变, 色彩偏移, 角色不一致, 多余肢体"
)

CAMERA_MAP = {
    "push_in": "镜头贴近主体前移，压缩空间",
    "pull_back": "镜头缓缓后退，展开场景全貌",
    "pan": "镜头横向平移扫景",
    "tracking": "镜头同步跟随主体移动",
    "orbit": "镜头缓慢环绕拍摄",
    "static": "镜头固定不动",
    "zoom_in": "镜头贴近主体前移",
    "zoom_out": "镜头缓缓后退",
    "pan_left": "镜头向左平移",
    "pan_right": "镜头向右平移",
    "dolly_in": "镜头平滑向前推进",
    "tilt_up": "镜头缓慢上摇",
    "tilt_down": "镜头缓慢下摇",
}

# MiniMax 可用中文音色（旁白用）
MINIMAX_NARRATOR_VOICES = {
    "female-shaonv": "少女音，清亮活泼的年轻女声",
    "female-yujie": "御姐音，成熟知性的女声",
    "female-chengshu": "成熟女性，温柔沉稳",
    "female-tianmei": "甜美女性，柔软甜蜜",
    "presenter_female": "女性主持人，端庄大方",
    "audiobook_female_1": "女性有声书1，温柔叙述",
    "audiobook_female_2": "女性有声书2，知性讲述",
    "Wise_Woman": "智慧女性，从容淡定",
    "Calm_Woman": "沉静女性，安宁平和",
    "male-qn-qingse": "青涩青年，年轻清爽的男声",
    "male-qn-jingying": "精英青年，沉稳干练的男声",
    "male-qn-badao": "霸道青年，低沉有力的男声",
    "presenter_male": "男性主持人，标准浑厚",
    "audiobook_male_1": "男性有声书1，温和叙述",
    "audiobook_male_2": "男性有声书2，沉稳讲述",
    "Deep_Voice_Man": "低沉男声，深邃有磁性",
    "Imposing_Manner": "威严男声，气场强大",
}


# ── Storyboard Prompt ────────────────────────────────────────────

NARRATION_STORYBOARD_SYSTEM_PROMPT = """你是一个漫剧推广视频策划师（旁白解说风格）。

你将阅读一段小说文本，完成以下两个任务。

【任务1】识别"有效冲突单元"
- 有效：有明确起因+冲突+情绪高点，有悬念空间
- 有几个说几个，不要凑数

【任务2】每个单元输出以下字段：
1. title — 标题（吸引人）
2. core_conflict — 核心冲突一句话
3. emotion_tone — 情感底色，从以下选择：孤独迷离 / 悬疑紧张 / 震撼共情 / 甜宠轻松 / 热血燃
4. key_scenes — 三个关键场景，每个包含 location（位置）和 description（描述）
5. ending_hook — 结尾钩子
6. characters — 本单元包含的人物名字列表
7. script — 本单元的剧本，是一个旁白/动作列表，每条包含：
   - type: "narration"（旁白文字，20-30字，讲故事推进剧情，绝不描述画面内容）或 "action"（画面描写，描述角色动作和场景变化）
   - character: 涉及的角色名（action 类型的主要角色，narration 类型为 null）
   - content: 旁白内容或动作描写

【旁白规则】
- narration 类型的 content 是旁白文字，纯推演剧情与对话，绝不描述画面内容
- narration 的 content 每句20-30字中文
- 保留原文精华：经典对话、内心独白、氛围描写必须融入旁白
- 情感层次丰富，每段有明确情感基调

# Output Format:
严格遵守且仅输出JSON格式。
{{
  "units": [
    {{
      "unit_number": 1,
      "title": "吸引人的标题",
      "core_conflict": "核心冲突一句话",
      "emotion_tone": "悬疑紧张",
      "key_scenes": [
        {{"location": "位置", "description": "场景描述"}},
        {{"location": "位置", "description": "场景描述"}},
        {{"location": "位置", "description": "场景描述"}}
      ],
      "ending_hook": "结尾钩子",
      "characters": ["角色A", "角色B"],
      "script": [
        {{"type": "action", "character": "角色A", "content": "角色A的动作描写..."}},
        {{"type": "narration", "character": null, "content": "旁白文字，讲述剧情推进..."}},
        {{"type": "action", "character": "角色B", "content": "角色B的动作描写..."}},
        {{"type": "narration", "character": null, "content": "旁白文字，讲述剧情推进..."}}
      ]
    }}
  ],
  "character_profiles": [
    {{
      "name": "角色名",
      "char_id": "char_001",
      "gender": "男/女",
      "age": "年龄描述",
      "appearance_prompt": "角色外貌的文生图提示词，用于生成角色参考图"
    }}
  ]
}}"""

NARRATION_STORYBOARD_USER_PROMPT = """请阅读以下小说文本，识别有效冲突单元，并按要求输出JSON。

【小说文本】：
{input_text}"""


# ── 4x4 宫格分镜 Prompt ──────────────────────────────────────────

GRID_SHOTS_SYSTEM_PROMPT = """你是一个创意视觉化脚本助手（精简关键词版）。

根据提供的剧本，生成一个4x4宫格分镜JSON（16个分镜）。

【规则】
1. 将剧本拆解为16个关键视觉瞬间
2. 每个分镜的 prompt_text 用英文，严格控制在 20-30 个单词
3. 使用"关键词 + 逗号"的 Tags 形式，禁止长句
4. 组合公式：[景别] + [主体与动作] + [环境] + [风格标签] + [排除词]
5. 每个 prompt_text 末尾必须包含 "no timecode, no subtitles"
6. 风格统一为动漫/漫画风格
7. 每个面板都是 9:16 竖屏构图

【节奏规则】
- 普通剧情：MS/MCU 为主
- 情感高潮：MCU→CU→ECU 递进，不可跳跃
- 打斗：EWS/WS 为主，用情绪切点代替动作展示
- 每3-4镜头必须有一次景别跳变

【结构规则】
- 第1-2个分镜：视觉钩子+情绪钩子
- 最后1-2个分镜：悬念或情感高点

【输出格式】严格JSON：
{{
  "style_tags": ["tag1", "tag2", "tag3"],
  "shots": [
    {{"shot_number": 1, "prompt_text": "英文关键词prompt..."}},
    ...共16个
  ]
}}"""

GRID_SHOTS_USER_PROMPT = """【剧本单元】：
标题：{title}
情感底色：{emotion_tone}
核心冲突：{core_conflict}

【剧本内容】：
{script_json}

【角色外貌参考】：
{characters_json}

请生成16个分镜的英文 prompt（每个面板为 9:16 竖屏构图）。"""

# Gemini 宫格图生成 prompt 模板 — 9:16 portrait
GRID_IMAGE_PROMPT_TEMPLATE = """Generate a 4x4 storyboard grid image (16 panels in a single image, 4 rows × 4 columns). The overall image MUST be in 9:16 portrait aspect ratio. Each panel should also be 9:16 portrait.

【CHARACTER REFERENCES】
{char_ref_labels}

【CORE INSTRUCTION】
Use the reference images as the subject anchor. Pay close attention to the spatial layout of the environment, the relative positions of characters and all objects in the scene. Generate coherent sequential storyboard panels from different camera angles that follow the story progression. MAINTAIN ABSOLUTE CONSISTENCY with the reference images' art style. Output the image. Output the image.

【CONSISTENCY RULES】
- Character faces and costumes MUST be absolutely identical to reference images, quote character fixed descriptions verbatim.
- No elements that conflict with the genre style.
- Maintain consistent spatial layout and relative positions of characters and objects.

【CAMERA GRAMMAR】
- 180-degree rule: do not cross the axis between subjects within the same scene (avoid jump cuts).
- 30-degree rule: adjacent panels must have >30 degree camera angle difference.

【RHYTHM RULES】
- Normal scenes: 3-5s per panel, MS/MCU as primary shots.
- Emotional climax: MCU→CU→ECU progression, no skipping.
- Action: 1-2s per panel, EWS/WS as primary, use emotion beats not complex choreography.
- Every 3-4 panels must have a shot scale change.

【ACTION RULES】
- No complex fight choreography.
- Use emotion cut points: Wind-up(MCU) → Clash(ECU eyes) → Burst(EWS+FX) → Result(CU expression).

【STRUCTURE RULES】
- Panels 1-2: Visual hook + emotional hook.
- Panels 15-16: Suspense or emotional peak.

【16 PANEL DESCRIPTIONS】
{shots_text}

Generate a single 4x4 grid image containing all 16 panels. Each panel should be clearly separated. {style_tags}. No text, no numbers, no labels on panels."""


# ── 分镜视频 Prompt（旁白版，无对话字段）──────────────────────────

VIDEO_SEGMENTS_SYSTEM_PROMPT = """你是一个专业的旁白漫剧视频分镜导演。

你将收到一个剧本单元的完整信息和16个分镜关键帧描述。你需要将相邻两帧组成一个视频分镜段（共15段），并为每段输出详细的视频生成指令。

【规则】
1. 每段视频由"首帧(帧N)"和"尾帧(帧N+1)"定义
2. 判断首尾帧是否属于同一场景（same_scene=true），如果场景跳变则标记 same_scene=false
3. 本工作流为旁白风格，没有角色对话。video_prompt 禁止出现"说话""开口""口型""讲述""台词""对话"等与人物发声有关的描写。只描述画面动态、镜头运动、表情变化。
4. 根据内容类型估算时长：旁白段=旁白字数÷4秒（向上取整，最小3秒），纯动作=3-5秒，情感特写=3秒，环境建立=4-6秒。所有段最小3秒。
5. 标注涉及的角色（用 char_id 关联）和可能需要的场景参考图
6. 判断该段是否为回忆/闪回场景（is_memory=true），依据剧本中的"回忆"、"闪回"、"过去"等描写
7. 为每段分配对应的旁白文字(narration_text)，从剧本 script 中 type="narration" 的条目按顺序映射。如果该段没有对应旁白，narration_text 留空字符串。

【输出格式】严格JSON：
{{
  "video_segments": [
    {{
      "segment_number": 1,
      "start_frame": 1,
      "end_frame": 2,
      "same_scene_as_prev": false,
      "is_memory": false,
      "scene_description": "中文场景描述",
      "camera_type": "景别（如：中景/特写/远景）",
      "camera_movement": "镜头运动（如：push_in/pan/static/tracking）",
      "emotion": "情感（如：紧张/悲伤/热血/平静）",
      "narration_text": "对应的旁白文字（20-30字中文），或空字符串",
      "characters_in_frame": ["char_001", "char_002"],
      "scene_ref_id": "u1_s1",
      "estimated_duration": 5,
      "video_prompt": "中文视频生成提示词，描述画面动态变化，禁止包含说话/口型描写"
    }}
  ]
}}

注意：
- 没有 is_dialogue 和 dialogue 字段
- is_memory=true 表示回忆/闪回场景
- scene_ref_id 对应之前生成的场景参考图ID（格式: u{{unit}}_s{{scene}}），选最接近的
- video_prompt 要描述从首帧到尾帧的动态变化过程
- narration_text 只从剧本 script 中 type="narration" 的内容映射，按顺序分配"""

VIDEO_SEGMENTS_USER_PROMPT = """【剧本单元 {unit_number}】：{title}
情感底色：{emotion_tone}
核心冲突：{core_conflict}

【完整剧本】：
{script_json}

【角色列表】（请用 char_id 关联）：
{characters_json}

【可用场景参考图】：
{scene_refs_json}

【16个分镜关键帧描述】：
{shots_json}

请为相邻帧组合生成15段视频分镜指令（旁白版，无对话字段）。"""


# ── 辅助函数 ─────────────────────────────────────────────────────

def _file_ok(path):
    """检查文件是否存在且非空。"""
    return path and os.path.exists(path) and os.path.getsize(path) > 100


def _download_with_retry(url, path, retries=3, timeout=180):
    """带重试的文件下载。"""
    for attempt in range(retries):
        try:
            r = http_requests.get(url, timeout=timeout)
            with open(path, "wb") as f:
                f.write(r.content)
            if os.path.getsize(path) > 1000:
                return True
        except Exception as e:
            print(f"  Download attempt {attempt+1}/{retries} failed: "
                  f"{type(e).__name__}", flush=True)
            time.sleep(5 * (attempt + 1))
    return False



# ── Workflow ─────────────────────────────────────────────────────

@register_workflow
class NarrationMangaV2Workflow(InteractiveOpsMixin, BaseWorkflow):
    name = "narration_manga_v2"
    display_name = "旁白漫剧 V2"
    stages = [
        "storyboard",
        "char_refs",
        "scene_refs",
        "storyboard_grids",
        "video_prompts",
        "narration_tts",
        "video_gen",
        "subtitle_burn",
        "assembly",
        "quality_gate",
    ]

    def get_output_subdirs(self):
        return [
            "characters", "scenes", "grids", "frames",
            "audio", "videos", "aligned", "segments",
        ]

    # ================================================================
    # Stage 1: Narration Storyboard
    # ================================================================
    def stage_storyboard(self, ctx: WorkflowContext) -> StageResult:
        input_len = len(ctx.input_text)
        if input_len > MAX_INPUT_LENGTH:
            return StageResult(
                success=False,
                message=(f"输入文本 {input_len} 字超过上限 {MAX_INPUT_LENGTH} 字，"
                         f"请先使用 novel_splitter 分集后再输入单集文本。"),
            )

        sb_path = os.path.join(ctx.output_dir, "storyboard.json")

        if os.path.exists(sb_path) and os.path.getsize(sb_path) > 100:
            ctx.log("  ★ 断点恢复: 加载已有 storyboard.json")
            with open(sb_path) as f:
                sb = json.load(f)
        else:
            ctx.log(f"  输入: {input_len} 字")
            user_prompt = NARRATION_STORYBOARD_USER_PROMPT.format(
                input_text=ctx.input_text,
            )
            sb = _validated_chat_json(
                system_prompt=NARRATION_STORYBOARD_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                required_keys=["units", "character_profiles"],
                list_key="units",
                temperature=0.5,
                max_tokens=8192,
            )
            with open(sb_path, "w", encoding="utf-8") as f:
                json.dump(sb, f, ensure_ascii=False, indent=2)

        # 解析到 context
        ctx.storyboard = sb
        units = sb.get("units", [])
        ctx.segments = units
        ctx.characters = sb.get("character_profiles", [])

        # 日志
        ctx.log(f"  {len(units)} 个冲突单元, {len(ctx.characters)} 个角色")
        for c in ctx.characters:
            ctx.log(f"    角色: {c['name']} ({c.get('char_id','?')}) "
                    f"{c.get('gender','?')}")

        for u in units:
            un = u.get("unit_number", "?")
            title = u.get("title", "")
            tone = u.get("emotion_tone", "")
            script = u.get("script", [])
            narrations = [s for s in script if s.get("type") == "narration"]
            actions = [s for s in script if s.get("type") == "action"]
            chars = u.get("characters", [])

            ctx.log(f"\n  -- 单元 {un}: {title} [{tone}] --")
            ctx.log(f"    冲突: {u.get('core_conflict', '')}")
            ctx.log(f"    人物: {', '.join(chars)}")
            ctx.log(f"    剧本: {len(narrations)} 条旁白, {len(actions)} 条动作")
            ctx.log(f"    钩子: {u.get('ending_hook', '')}")

            for i, sc in enumerate(u.get("key_scenes", [])):
                ctx.log(f"    场景{i+1}: [{sc.get('location','')}] "
                        f"{sc.get('description','')[:60]}")

            for j, line in enumerate(script[:6]):
                t = line.get("type", "?")
                ch = line.get("character", "")
                ct = line.get("content", "")[:60]
                if t == "narration":
                    ctx.log(f"    [旁白]: \"{ct}\"")
                else:
                    ctx.log(f"    [动作] {f'[{ch}] ' if ch else ''}{ct}")
            if len(script) > 6:
                ctx.log(f"    ... (还有 {len(script)-6} 条)")

        return StageResult(success=True)

    # ================================================================
    # Stage 2: Character Reference Images (三视图)
    # ================================================================
    def stage_char_refs(self, ctx: WorkflowContext) -> StageResult:
        os.makedirs(os.path.join(ctx.output_dir, "characters"), exist_ok=True)

        for c in ctx.characters:
            cid = c["char_id"]
            asset_key = f"char_ref:{cid}"

            if not ctx.candidates.is_invalidated(asset_key):
                sel = ctx.candidates.get_selected_path(asset_key)
                if sel and os.path.exists(sel) and os.path.getsize(sel) > 100:
                    ctx.char_images[cid] = sel
                    ctx.log(f"  {c['name']} ({cid}): ★ 已存在")
                    continue
            ctx.candidates.clear_invalidation(asset_key)

            appearance = c.get("appearance_prompt", "")
            gender = c.get("gender", "")
            gender_hint = ("男性角色" if "男" in gender
                           else "女性角色" if "女" in gender else "")

            prompt = (
                "杰作, 最高质量, 高度精细, 4K, "
                "动漫风格, 漫画风格, 赛璐璐上色, 鲜艳色彩, "
                "角色设定图, 白色背景, 三视图, 正面视图+侧面视图+背面视图, "
                f"{gender_hint}, {appearance}, "
                "全身立绘, 表情自然, 姿态端正, "
                "纯净白色背景, 摄影棚灯光, "
                "无文字, 无水印, 高清锐利, 单人"
            )

            version = ctx.candidates.next_version(asset_key)
            paths = generate_image(
                prompt, width=1472, height=832,
                output_dir=os.path.join(ctx.output_dir, "characters"),
                prefix=f"charref_{cid}_v{version}",
            )
            if paths:
                rel = os.path.relpath(paths[0], ctx.output_dir)
                ctx.candidates.register(asset_key, rel)
                ctx.char_images[cid] = paths[0]
                ctx.log(f"  {c['name']} ({cid}): ✓ 三视图 (v{version})")
            else:
                ctx.log(f"  {c['name']} ({cid}): ✗ 生成失败")

            time.sleep(3)

        return StageResult(success=True)

    # ================================================================
    # Stage 3: Scene Reference Images (Gemini + 角色参考)
    # ================================================================
    def stage_scene_refs(self, ctx: WorkflowContext) -> StageResult:
        os.makedirs(os.path.join(ctx.output_dir, "scenes"), exist_ok=True)

        char_name_map = {}
        for c in ctx.characters:
            char_name_map[c["name"]] = c["char_id"]
            base_name = c["name"].split("(")[0].split("（")[0].strip()
            char_name_map[base_name] = c["char_id"]

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            title = unit.get("title", "")
            ctx.log(f"\n  -- 单元 {un}: {title} --")

            for si, scene in enumerate(unit.get("key_scenes", [])):
                location = scene.get("location", "")
                description = scene.get("description", "")
                asset_key = f"scene_ref:u{un}_s{si+1}"

                if not ctx.candidates.is_invalidated(asset_key):
                    sel = ctx.candidates.get_selected_path(asset_key)
                    if sel and os.path.exists(sel) and os.path.getsize(sel) > 100:
                        ctx.log(f"    场景{si+1} [{location}]: ★ 已存在")
                        continue
                ctx.candidates.clear_invalidation(asset_key)

                unit_chars = unit.get("characters", [])
                ref_images = []
                ref_labels = []
                for char_name in unit_chars:
                    cid = char_name_map.get(char_name)
                    if cid and cid in ctx.char_images:
                        ref_images.append(ctx.char_images[cid])
                        char_profile = next(
                            (cp for cp in ctx.characters
                             if cp["char_id"] == cid), {})
                        appearance = char_profile.get(
                            "appearance_prompt", "")[:80]
                        ref_labels.append(
                            f'Art style reference (DO NOT draw this character, '
                            f'use ONLY for matching art style, color palette, and line work)')

                # 纯环境空镜，不含人物
                prompt = (
                    f"Generate an anime background scene image in 9:16 portrait aspect ratio "
                    f"— EMPTY ENVIRONMENT ONLY. "
                    f"Location: {location}. "
                    f"Environment description: {description}. "
                    f"This is a pure environment/background art with NO characters, NO people, "
                    f"NO human figures, NO silhouettes. Show only the location, architecture, "
                    f"objects, lighting, and atmosphere. "
                    f"Use the reference images ONLY to match the art style (color palette, "
                    f"line style, cel-shading level), NOT to include any characters. "
                    f"Anime style, manga aesthetic, dramatic lighting, high quality. "
                    f"No text, no watermark, no characters."
                )

                version = ctx.candidates.next_version(asset_key)
                out_path = os.path.join(
                    ctx.output_dir, "scenes",
                    f"scene_u{un}_s{si+1}_v{version}.png")

                result = generate_image_with_refs(
                    prompt=prompt,
                    ref_images=ref_images if ref_images else None,
                    ref_labels=ref_labels if ref_labels else None,
                    output_path=out_path,
                )

                if result:
                    rel = os.path.relpath(result, ctx.output_dir)
                    ctx.candidates.register(asset_key, rel)
                    ctx.log(f"    场景{si+1} [{location}]: ✓ "
                            f"(v{version}, {len(ref_images)}角色参考)")
                else:
                    ctx.log(f"    场景{si+1} [{location}]: ✗ 生成失败")

                time.sleep(2)

        return StageResult(success=True)

    # ================================================================
    # Stage 4: Storyboard Grids (4x4 宫格, 9:16 portrait)
    # ================================================================
    def stage_storyboard_grids(self, ctx: WorkflowContext) -> StageResult:
        os.makedirs(os.path.join(ctx.output_dir, "grids"), exist_ok=True)

        char_name_map = {}
        for c in ctx.characters:
            char_name_map[c["name"]] = c["char_id"]
            base_name = c["name"].split("(")[0].split("（")[0].strip()
            char_name_map[base_name] = c["char_id"]

        chars_appearance = [
            {"name": c["name"], "appearance": c.get("appearance_prompt", "")}
            for c in ctx.characters
        ]

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            title = unit.get("title", "")
            asset_key = f"grid:u{un}"

            if not ctx.candidates.is_invalidated(asset_key):
                sel = ctx.candidates.get_selected_path(asset_key)
                if sel and os.path.exists(sel) and os.path.getsize(sel) > 100:
                    ctx.log(f"  单元 {un} [{title}]: ★ 已存在")
                    continue
            ctx.candidates.clear_invalidation(asset_key)

            ctx.log(f"\n  -- 单元 {un}: {title} --")

            # Step A: LLM 生成 16 个分镜 prompt
            grid_json_path = os.path.join(
                ctx.output_dir, "grids", f"grid_u{un}_shots.json")
            if (os.path.exists(grid_json_path)
                    and os.path.getsize(grid_json_path) > 100):
                ctx.log("    LLM shots: ★ 已存在")
                with open(grid_json_path) as f:
                    grid_data = json.load(f)
            else:
                ctx.log("    LLM 生成 16 个分镜 prompt...")
                grid_data = _validated_chat_json(
                    system_prompt=GRID_SHOTS_SYSTEM_PROMPT,
                    user_prompt=GRID_SHOTS_USER_PROMPT.format(
                        title=title,
                        emotion_tone=unit.get("emotion_tone", ""),
                        core_conflict=unit.get("core_conflict", ""),
                        script_json=json.dumps(
                            unit.get("script", []),
                            ensure_ascii=False, indent=2),
                        characters_json=json.dumps(
                            chars_appearance,
                            ensure_ascii=False, indent=2),
                    ),
                    required_keys=["shots"],
                    list_key="shots",
                    list_length=16,
                    temperature=0.5,
                    max_tokens=4096,
                )
                with open(grid_json_path, "w", encoding="utf-8") as f:
                    json.dump(grid_data, f, ensure_ascii=False, indent=2)

            shots = grid_data.get("shots", [])
            style_tags = grid_data.get("style_tags", [])
            if isinstance(style_tags, list):
                style_tags = ", ".join(style_tags)
            ctx.log(f"    LLM: {len(shots)} shots, style={style_tags}")

            # Step B: 收集角色参考图
            unit_chars = unit.get("characters", [])
            ref_images = []
            ref_labels = []
            for char_name in unit_chars:
                cid = char_name_map.get(char_name)
                if cid and cid in ctx.char_images:
                    ref_images.append(ctx.char_images[cid])
                    char_profile = next(
                        (cp for cp in ctx.characters
                         if cp["char_id"] == cid), {})
                    appearance = char_profile.get(
                        "appearance_prompt", "")[:80]
                    ref_labels.append(
                        f'Character "{char_name}": {appearance}')

            # 也加入已生成的场景参考图
            for si in range(len(unit.get("key_scenes", []))):
                scene_sel = ctx.candidates.get_selected_path(
                    f"scene_ref:u{un}_s{si+1}")
                if scene_sel and os.path.exists(scene_sel):
                    ref_images.append(scene_sel)
                    loc = unit["key_scenes"][si].get("location", "")
                    ref_labels.append(f'Scene reference: {loc}')

            # Step C: 组装 Gemini prompt
            char_ref_labels = "\n".join(
                [f"- Image {i+1}: {lbl}"
                 for i, lbl in enumerate(ref_labels)]
            ) if ref_labels else "No character references available."

            shots_text = "\n".join(
                [f'Panel {s.get("shot_number", i+1)}: '
                 f'{_strip_shot_labels(s.get("prompt_text", s.get("prompt", "")))}'
                 for i, s in enumerate(shots)]
            )

            gemini_prompt = GRID_IMAGE_PROMPT_TEMPLATE.format(
                char_ref_labels=char_ref_labels,
                shots_text=shots_text,
                style_tags=style_tags,
            )

            # Step D: Gemini 生成宫格图
            ctx.log(f"    Gemini 生成 4x4 宫格图 "
                    f"({len(ref_images)} 参考图, 9:16 portrait)...")
            version = ctx.candidates.next_version(asset_key)
            out_path = os.path.join(
                ctx.output_dir, "grids",
                f"grid_u{un}_v{version}.png")

            result = generate_image_with_refs(
                prompt=gemini_prompt,
                ref_images=ref_images if ref_images else None,
                ref_labels=ref_labels if ref_labels else None,
                output_path=out_path,
                image_size="4K",
            )

            if result:
                rel = os.path.relpath(result, ctx.output_dir)
                ctx.candidates.register(asset_key, rel)
                ctx.log(f"    ✓ 宫格图 (v{version})")
            else:
                ctx.log("    ✗ 宫格图生成失败")

            time.sleep(3)

        return StageResult(success=True)

    # ================================================================
    # Stage 5: Video Prompts (4K切图 + 分镜视频指令, portrait)
    # ================================================================
    def stage_video_prompts(self, ctx: WorkflowContext) -> StageResult:
        from PIL import Image

        os.makedirs(os.path.join(ctx.output_dir, "frames"), exist_ok=True)

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            title = unit.get("title", "")
            ctx.log(f"\n  -- 单元 {un}: {title} --")

            # -- Step A: 从 4K 宫格图切出 16 帧 (portrait) --
            grid_sel = ctx.candidates.get_selected_path(f"grid:u{un}")
            if not grid_sel or not os.path.exists(grid_sel):
                ctx.log("    ✗ 宫格图不存在，跳过")
                continue

            frames_dir = os.path.join(ctx.output_dir, "frames", f"u{un}")
            os.makedirs(frames_dir, exist_ok=True)

            existing_frames = [
                f for f in os.listdir(frames_dir)
                if f.startswith("frame_") and f.endswith(".png")
            ]
            if len(existing_frames) >= 16:
                ctx.log(f"    切图: ★ 已存在 ({len(existing_frames)} 帧)")
            else:
                grid_img = Image.open(grid_sel)
                ctx.log(f"    切图: {grid_img.width}x{grid_img.height}")

                crop_boxes, resize_target = _detect_grid_panels(grid_img)
                for row in range(4):
                    for col in range(4):
                        idx = row * 4 + col + 1
                        frame_path = os.path.join(
                            frames_dir, f"frame_{idx:02d}.png")
                        if (os.path.exists(frame_path)
                                and os.path.getsize(frame_path) > 500):
                            continue
                        cell = grid_img.crop(crop_boxes[row][col])
                        cell = cell.resize(resize_target, Image.LANCZOS)
                        cell.save(frame_path)

                ctx.log(f"    ✓ 16 帧已切出 "
                        f"({resize_target[0]}x{resize_target[1]})")

            # 注册每帧到 CandidateManager
            for fidx in range(1, 17):
                frame_path = os.path.join(
                    frames_dir, f"frame_{fidx:02d}.png")
                if os.path.exists(frame_path):
                    fkey = f"frame:u{un}_f{fidx:02d}"
                    if not ctx.candidates.list_candidates(fkey):
                        rel = os.path.relpath(frame_path, ctx.output_dir)
                        ctx.candidates.register(fkey, rel)

            # -- Step B: LLM 生成 15 段分镜视频指令（旁白版） --
            vp_path = os.path.join(
                ctx.output_dir, "grids",
                f"video_segments_u{un}.json")

            if os.path.exists(vp_path) and os.path.getsize(vp_path) > 100:
                ctx.log("    分镜指令: ★ 已存在")
                with open(vp_path) as f:
                    vp_data = json.load(f)
            else:
                shots_path = os.path.join(
                    ctx.output_dir, "grids",
                    f"grid_u{un}_shots.json")
                if os.path.exists(shots_path):
                    with open(shots_path) as f:
                        shots_data = json.load(f)
                    shots = shots_data.get("shots", [])
                else:
                    shots = []

                scene_refs_list = []
                for si, sc in enumerate(unit.get("key_scenes", [])):
                    ref_id = f"u{un}_s{si+1}"
                    scene_refs_list.append({
                        "ref_id": ref_id,
                        "location": sc.get("location", ""),
                        "description": sc.get("description", ""),
                    })

                chars_for_llm = [
                    {"char_id": c["char_id"], "name": c["name"],
                     "gender": c.get("gender", "")}
                    for c in ctx.characters
                ]

                ctx.log("    LLM 生成 15 段分镜视频指令（旁白版）...")
                vp_data = _validated_chat_json(
                    system_prompt=VIDEO_SEGMENTS_SYSTEM_PROMPT,
                    user_prompt=VIDEO_SEGMENTS_USER_PROMPT.format(
                        unit_number=un,
                        title=title,
                        emotion_tone=unit.get("emotion_tone", ""),
                        core_conflict=unit.get("core_conflict", ""),
                        script_json=json.dumps(
                            unit.get("script", []),
                            ensure_ascii=False, indent=2),
                        characters_json=json.dumps(
                            chars_for_llm,
                            ensure_ascii=False, indent=2),
                        scene_refs_json=json.dumps(
                            scene_refs_list,
                            ensure_ascii=False, indent=2),
                        shots_json=json.dumps(
                            shots,
                            ensure_ascii=False, indent=2),
                    ),
                    required_keys=["video_segments"],
                    list_key="video_segments",
                    list_length=15,
                    temperature=0.4,
                    max_tokens=8192,
                )

                with open(vp_path, "w", encoding="utf-8") as f:
                    json.dump(vp_data, f, ensure_ascii=False, indent=2)

            # -- 打印摘要 --
            segments = vp_data.get("video_segments", [])
            total_dur = sum(
                s.get("estimated_duration", 0) for s in segments)
            narration_count = sum(
                1 for s in segments if s.get("narration_text"))
            scene_change_count = sum(
                1 for s in segments
                if not s.get("same_scene_as_prev", True))

            ctx.log(f"    {len(segments)} 段, 预估总时长 {total_dur}s, "
                    f"{narration_count} 段含旁白, "
                    f"{scene_change_count} 次场景跳变")

            for s in segments[:5]:
                sn = s.get("segment_number", "?")
                cam = s.get("camera_type", "")
                mov = s.get("camera_movement", "")
                dur = s.get("estimated_duration", 0)
                emo = s.get("emotion", "")
                nt = s.get("narration_text", "")
                narr_str = ""
                if nt:
                    narr_str = f'\n      [旁白]: "{nt[:25]}..."'
                same = "→" if s.get("same_scene_as_prev") else "⟳"
                ctx.log(f"    {same} 段{sn}: [{cam}/{mov}] "
                        f"{dur}s {emo}{narr_str}")
            if len(segments) > 5:
                ctx.log(f"    ... (还有 {len(segments)-5} 段)")

        return StageResult(success=True)

    # ================================================================
    # Stage 6: Narration TTS (单旁白 + 时长校准)
    # ================================================================
    def stage_narration_tts(self, ctx: WorkflowContext) -> StageResult:
        import math
        from app.services.ffmpeg_utils import get_media_duration
        from vendor.qwen.tts import qwen_tts, QWEN_VOICES
        from app.workflows.templates._shared import (
            NARRATION_VOICE_MATCH_SYSTEM_PROMPT,
        )

        os.makedirs(os.path.join(ctx.output_dir, "audio"), exist_ok=True)

        # ── Step 1: LLM 选择旁白音色 + 生成 instruct 指令 ──
        voice_config_path = os.path.join(ctx.output_dir, "narration_voice.json")
        if os.path.exists(voice_config_path):
            with open(voice_config_path) as f:
                voice_config = json.load(f)
            ctx.log(f"  ★ 断点恢复: 旁白音色 {voice_config['voice_id']}")
        else:
            # 取剧本完整信息传给 LLM
            unit = ctx.segments[0] if ctx.segments else {}
            title = unit.get("title", "")
            emotion_tone = unit.get("emotion_tone", "悬疑紧张")
            core_conflict = unit.get("core_conflict", "")
            ending_hook = unit.get("ending_hook", "")
            # 提取旁白文本摘要
            script = unit.get("script", [])
            narrations = [s["content"] for s in script if s.get("type") == "narration"]
            narration_preview = " / ".join(narrations[:3])
            # 角色信息
            chars_summary = ", ".join(
                f"{c['name']}({c.get('gender','?')})" for c in ctx.characters[:5]
            ) if ctx.characters else ""

            voice_config = _validated_chat_json(
                system_prompt=NARRATION_VOICE_MATCH_SYSTEM_PROMPT,
                user_prompt=(
                    f"【剧本标题】{title}\n"
                    f"【情感基调】{emotion_tone}\n"
                    f"【核心冲突】{core_conflict}\n"
                    f"【结尾钩子】{ending_hook}\n"
                    f"【角色】{chars_summary}\n"
                    f"【旁白摘要】{narration_preview}\n\n"
                    f"【可用音色】：\n{json.dumps(QWEN_VOICES, ensure_ascii=False, indent=2)}"
                ),
                required_keys=["voice_id", "tts_instructions"],
                temperature=0.3,
                max_tokens=512,
            )
            with open(voice_config_path, "w", encoding="utf-8") as f:
                json.dump(voice_config, f, ensure_ascii=False, indent=2)

        voice_id = voice_config.get("voice_id", "Serena")
        base_instructions = voice_config.get("tts_instructions", "沉稳专业的旁白叙述风格")
        ctx.log(f"  旁白音色: {voice_id} (Qwen TTS)")
        ctx.log(f"  风格指令: {base_instructions}")

        # ── Step 2: 逐段生成 TTS ──
        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            vp_path = os.path.join(
                ctx.output_dir, "grids",
                f"video_segments_u{un}.json")
            if not os.path.exists(vp_path):
                continue

            with open(vp_path) as f:
                vp_data = json.load(f)
            segments = vp_data.get("video_segments", [])

            ctx.log(f"\n  -- 单元 {un}: Narration TTS (Qwen) --")
            updated = False

            for seg in segments:
                sn = seg["segment_number"]
                narration = seg.get("narration_text", "")

                if not narration:
                    seg["final_duration"] = max(
                        seg.get("estimated_duration", 3), 3)
                    continue

                # 已有 TTS → 跳过
                if seg.get("tts_path") and seg.get("final_duration"):
                    tts_p = seg["tts_path"]
                    if (os.path.exists(tts_p)
                            and os.path.getsize(tts_p) > 100):
                        ctx.log(f"    段{sn}: ★ 已存在")
                        continue

                # 根据段落情感微调 instructions
                seg_emotion = seg.get("emotion", "")
                if seg_emotion and seg_emotion != "calm":
                    instructions = f"{base_instructions}，当前段落情感：{seg_emotion}"
                else:
                    instructions = base_instructions

                # 调用 Qwen TTS
                audio_data = qwen_tts(
                    text=narration,
                    voice=voice_id,
                    instructions=instructions,
                )

                if audio_data:
                    audio_path = os.path.join(
                        ctx.output_dir, "audio",
                        f"u{un}_seg{sn:02d}_narration.wav")
                    with open(audio_path, "wb") as f:
                        f.write(audio_data)

                    tts_dur = get_media_duration(audio_path)
                    final_dur = max(
                        seg.get("estimated_duration", 3),
                        math.ceil(tts_dur), 3)

                    seg["tts_path"] = os.path.abspath(audio_path)
                    seg["tts_duration"] = tts_dur
                    seg["final_duration"] = final_dur
                    updated = True

                    tts_asset_key = f"narration_tts:u{un}_seg{sn:02d}"
                    rel = os.path.relpath(audio_path, ctx.output_dir)
                    if not ctx.candidates.list_candidates(tts_asset_key):
                        ctx.candidates.register(tts_asset_key, rel)

                    ctx.log(f"    段{sn}: ✓ TTS={tts_dur:.1f}s → "
                            f"final={final_dur}s")
                else:
                    seg["final_duration"] = max(
                        seg.get("estimated_duration", 3), 3)
                    ctx.log(f"    段{sn}: ✗ TTS 失败")

                time.sleep(0.3)  # rate limit

            if updated:
                with open(vp_path, "w", encoding="utf-8") as f:
                    json.dump(vp_data, f, ensure_ascii=False, indent=2)

            total_dur = sum(
                s.get("final_duration", 0) for s in segments)
            ctx.log(f"    总时长: {total_dur}s")

        return StageResult(success=True)

    # ================================================================
    # Stage 7: Video Generation (Kling V3, serial, sound=on, 9:16)
    # ================================================================
    def stage_video_gen(self, ctx: WorkflowContext) -> StageResult:
        from vendor.kling.client import KlingClient
        from app.services.ffmpeg_utils import get_media_duration

        client = KlingClient()
        os.makedirs(os.path.join(ctx.output_dir, "videos"), exist_ok=True)

        def _download(url, path, retries=3):
            for attempt in range(retries):
                try:
                    r = http_requests.get(url, timeout=180)
                    with open(path, "wb") as f:
                        f.write(r.content)
                    if os.path.getsize(path) > 1000:
                        return True
                except Exception as e:
                    print(f"  下载重试 {attempt+1}/{retries}: "
                          f"{type(e).__name__}")
                    time.sleep(5)
            return False

        total_generated = 0
        total_segments = 0

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            vp_path = os.path.join(
                ctx.output_dir, "grids",
                f"video_segments_u{un}.json")
            if not os.path.exists(vp_path):
                continue

            with open(vp_path) as f:
                vp_data = json.load(f)
            segments = vp_data.get("video_segments", [])
            total_segments += len(segments)

            ctx.log(f"\n  -- 单元 {un}: 视频生成 "
                    f"({len(segments)} 段, serial) --")

            for seg in segments:
                sn = seg["segment_number"]
                final_path = os.path.join(
                    ctx.output_dir, "videos",
                    f"u{un}_seg{sn:02d}_final.mp4")

                # 断点恢复
                video_asset_key = f"video:u{un}_seg{sn:02d}"
                sel_video = ctx.candidates.get_selected_path(
                    video_asset_key)
                if (sel_video and os.path.exists(sel_video)
                        and os.path.getsize(sel_video) > 1000):
                    ctx.log(f"    段{sn}: ★ 已存在 (candidates)")
                    total_generated += 1
                    continue
                if (os.path.exists(final_path)
                        and os.path.getsize(final_path) > 1000):
                    rel = os.path.relpath(final_path, ctx.output_dir)
                    ctx.candidates.register(video_asset_key, rel)
                    ctx.log(f"    段{sn}: ★ 已存在")
                    total_generated += 1
                    continue

                # 首帧
                frames_dir = os.path.join(
                    ctx.output_dir, "frames", f"u{un}")
                frame_start = os.path.join(
                    frames_dir,
                    f"frame_{seg['start_frame']:02d}.png")
                # 也从 CandidateManager 获取
                fkey_start = (
                    f"frame:u{un}_f{seg['start_frame']:02d}")
                sel_start = ctx.candidates.get_selected_path(
                    fkey_start)
                if sel_start and os.path.exists(sel_start):
                    frame_start = sel_start

                if not os.path.exists(frame_start):
                    ctx.log(f"    段{sn}: ✗ 首帧不存在，跳过")
                    continue

                # 角色参考图
                char_refs = []
                for cid in seg.get("characters_in_frame", []):
                    if cid in ctx.char_images:
                        char_refs.append({
                            "image": client.encode_image(
                                ctx.char_images[cid]),
                        })

                # 构建 image2video 参数
                duration = str(max(
                    seg.get("final_duration",
                            seg.get("estimated_duration", 3)), 3))
                video_prompt = seg.get("video_prompt", "")

                i2v_params = {
                    "model_name": "kling-v3",
                    "image": client.encode_image(frame_start),
                    "prompt": video_prompt,
                    "mode": "std",
                    "duration": duration,
                    "aspect_ratio": "9:16",
                    "sound": "on",
                }
                if char_refs:
                    i2v_params["subject_reference"] = char_refs[:1]

                # 提交 image2video (重试3次)
                task_id = None
                for attempt in range(3):
                    try:
                        result = client._post(
                            "/v1/videos/image2video", i2v_params)
                        if result.get("code") == 0:
                            task_id = result["data"]["task_id"]
                            break
                        code = result.get("code", -1)
                        if code == 1303:
                            ctx.log(f"    段{sn}: 并行限制, "
                                    f"等待90s...")
                            time.sleep(90)
                            continue
                        ctx.log(f"    段{sn}: image2video 重试 "
                                f"{attempt+1} code={code}")
                    except Exception as e:
                        ctx.log(f"    段{sn}: image2video 重试 "
                                f"{attempt+1} {type(e).__name__}")
                    time.sleep(10 * (attempt + 1))

                if not task_id:
                    ctx.log(f"    段{sn}: ✗ image2video 提交失败")
                    continue

                # 轮询
                data = client.poll_task(
                    task_id, task_type="video",
                    max_wait=600, interval=10)
                if not data:
                    ctx.log(f"    段{sn}: ✗ image2video 超时")
                    continue

                video_info = data["task_result"]["videos"][0]

                # 下载 (无 lip-sync, 旁白在 assembly 叠加)
                if not _download(video_info["url"], final_path):
                    ctx.log(f"    段{sn}: ✗ 下载失败")
                    continue

                # 注册
                rel = os.path.relpath(final_path, ctx.output_dir)
                ctx.candidates.register(video_asset_key, rel)
                total_generated += 1

                dur_v = get_media_duration(final_path)
                sz = os.path.getsize(final_path) / 1024 / 1024
                ctx.log(f"    段{sn}: ✓ ({dur_v:.1f}s, {sz:.1f}MB) "
                        f"sound=on")

                # 串行：等待后再继续下一段
                time.sleep(5)

        ctx.log(f"\n  视频生成完成: "
                f"{total_generated}/{total_segments} 段")
        return StageResult(success=True)

    # ================================================================
    # Stage 8: Subtitle Burn (旁白字幕, narration only)
    # ================================================================
    def stage_subtitle_burn(self, ctx: WorkflowContext) -> StageResult:
        font_path = _resolve_cjk_font()
        if not font_path:
            ctx.log("  ⚠ 未找到 CJK 字体，跳过字幕压制。"
                    "请安装 fonts-noto-cjk。")
            return StageResult(
                success=True,
                message="No CJK font found, subtitles skipped")

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            vp_path = os.path.join(
                ctx.output_dir, "grids",
                f"video_segments_u{un}.json")
            if not os.path.exists(vp_path):
                continue

            with open(vp_path) as f:
                segments = json.load(f).get("video_segments", [])

            ctx.log(f"\n  -- 单元 {un}: 字幕压制 --")

            # 字幕参数：9:16 竖屏 720px 宽，fontsize=28，留边距 40px
            # 每行最大字符数: (720 - 40*2) / 28 ≈ 22 个中文字
            MAX_CHARS_PER_LINE = 20
            FONT_SIZE = 28

            def _wrap_and_split(text, duration):
                """将文本折行，长文本按时长拆成多段。

                Returns:
                    list of (start_sec, end_sec, display_text)
                """
                # 按 MAX_CHARS_PER_LINE 折行
                lines = []
                while text:
                    if len(text) <= MAX_CHARS_PER_LINE:
                        lines.append(text)
                        break
                    # 找标点断句
                    cut = MAX_CHARS_PER_LINE
                    for punct in "，。！？；、":
                        idx = text[:MAX_CHARS_PER_LINE].rfind(punct)
                        if idx > MAX_CHARS_PER_LINE // 2:
                            cut = idx + 1
                            break
                    lines.append(text[:cut])
                    text = text[cut:]

                # 如果总共 ≤ 2 行，一次性显示
                if len(lines) <= 2:
                    display = "\n".join(lines)
                    return [(0, duration, display)]

                # 超过 2 行：拆成 2 段，各显示一半时长
                mid = len(lines) // 2
                part1 = "\n".join(lines[:mid])
                part2 = "\n".join(lines[mid:])
                half = duration / 2
                return [
                    (0, half, part1),
                    (half, duration, part2),
                ]

            for seg in segments:
                sn = seg["segment_number"]
                narration = seg.get("narration_text", "")
                if not narration:
                    continue

                video_in = os.path.join(
                    ctx.output_dir, "videos",
                    f"u{un}_seg{sn:02d}_final.mp4")
                video_out = os.path.join(
                    ctx.output_dir, "videos",
                    f"u{un}_seg{sn:02d}_subtitled.mp4")

                if (os.path.exists(video_out)
                        and os.path.getsize(video_out) > 1000):
                    ctx.log(f"    段{sn}: ★ 字幕已存在")
                    continue

                if not os.path.exists(video_in):
                    continue

                duration = seg.get("final_duration", 5)
                parts = _wrap_and_split(narration, duration)

                # 构建 drawtext filter（支持多段分时显示）
                filters = []
                for start, end, text in parts:
                    safe = _ffmpeg_safe_text(text)
                    f = (
                        f"drawtext=fontfile='{font_path}':"
                        f"fontsize={FONT_SIZE}:fontcolor=white:"
                        f"borderw=2:bordercolor=black:"
                        f"x=(w-text_w)/2:y=h-th-60:"
                        f"text='{safe}':"
                        f"enable='between(t,{start:.1f},{end:.1f})'"
                    )
                    filters.append(f)

                filter_str = ",".join(filters)

                cmd = [
                    "ffmpeg", "-y", "-i", video_in,
                    "-vf", filter_str,
                    "-c:a", "copy",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    video_out,
                ]
                result = subprocess.run(
                    cmd, capture_output=True, timeout=30)
                if result.returncode == 0:
                    line_info = f"{len(parts)}段" if len(parts) > 1 else "1段"
                    ctx.log(f"    段{sn}: ✓ 旁白字幕 ({line_info})")
                else:
                    ctx.log(f"    段{sn}: ✗ 字幕压制失败")

        return StageResult(success=True)

    # ================================================================
    # Stage 9: Assembly (720x1280 @30fps + 3-layer audio)
    # ================================================================
    def stage_assembly(self, ctx: WorkflowContext) -> StageResult:
        from app.services.ffmpeg_utils import get_media_duration

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            vp_path = os.path.join(
                ctx.output_dir, "grids",
                f"video_segments_u{un}.json")
            if not os.path.exists(vp_path):
                continue

            final_output = os.path.join(
                ctx.output_dir, "videos", f"u{un}_output.mp4")
            if (os.path.exists(final_output)
                    and os.path.getsize(final_output) > 1000):
                ctx.log(f"\n  -- 单元 {un}: ★ 已存在 --")
                continue

            with open(vp_path) as f:
                segments = json.load(f).get("video_segments", [])

            ctx.log(f"\n  -- 单元 {un}: 组装 ({len(segments)} 段) --")

            # -- Step A: 收集各段视频（字幕版优先） --
            clip_paths = []
            for seg in segments:
                sn = seg["segment_number"]
                subtitled = os.path.join(
                    ctx.output_dir, "videos",
                    f"u{un}_seg{sn:02d}_subtitled.mp4")
                raw = os.path.join(
                    ctx.output_dir, "videos",
                    f"u{un}_seg{sn:02d}_final.mp4")

                if (os.path.exists(subtitled)
                        and os.path.getsize(subtitled) > 1000):
                    clip_paths.append(subtitled)
                elif (os.path.exists(raw)
                      and os.path.getsize(raw) > 1000):
                    clip_paths.append(raw)
                else:
                    ctx.log(f"    段{sn}: ✗ 视频不存在，跳过")

            if not clip_paths:
                ctx.log("    无可用视频")
                continue

            # -- Step B: 统一 720x1280 @30fps (9:16 portrait) --
            ctx.log("    统一 720x1280 @30fps...")
            unified_clips = []
            for i, c in enumerate(clip_paths):
                unified = os.path.join(
                    ctx.output_dir, "videos",
                    f"u{un}_unified_{i:02d}.mp4")

                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet",
                     "-show_streams", c],
                    capture_output=True, text=True, timeout=10)
                has_audio = "codec_type=audio" in probe.stdout

                vf = ("fps=30,scale=720:1280:"
                      "force_original_aspect_ratio=decrease,"
                      "pad=720:1280:(ow-iw)/2:(oh-ih)/2")

                if has_audio:
                    cmd = [
                        "ffmpeg", "-y", "-i", c, "-vf", vf,
                        "-c:v", "libx264", "-preset", "fast",
                        "-crf", "18",
                        "-c:a", "aac", "-b:a", "128k",
                        "-ar", "44100", unified,
                    ]
                else:
                    cmd = [
                        "ffmpeg", "-y", "-i", c,
                        "-f", "lavfi", "-i",
                        "anullsrc=r=44100:cl=stereo",
                        "-vf", vf,
                        "-c:v", "libx264", "-preset", "fast",
                        "-crf", "18",
                        "-c:a", "aac", "-b:a", "128k",
                        "-shortest", unified,
                    ]

                result = subprocess.run(
                    cmd, capture_output=True, timeout=60)
                if result.returncode == 0:
                    unified_clips.append(unified)
                else:
                    ctx.log(f"    ✗ 统一失败: {os.path.basename(c)}")

            if not unified_clips:
                ctx.log("    无统一后视频")
                continue

            # -- Step C: 拼接 --
            ctx.log(f"    拼接 {len(unified_clips)} 段...")
            concat_list = os.path.join(
                ctx.output_dir, "videos", f"concat_u{un}.txt")
            with open(concat_list, "w") as f:
                for c in unified_clips:
                    f.write(f"file '{os.path.abspath(c)}'\n")

            concat_out = os.path.join(
                ctx.output_dir, "videos", f"u{un}_concat.mp4")
            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_list, "-c", "copy", concat_out,
            ]
            result = subprocess.run(
                cmd, capture_output=True, timeout=120)
            if result.returncode != 0:
                ctx.log("    ✗ 拼接失败")
                continue

            video_dur = get_media_duration(concat_out)
            ctx.log(f"    拼接完成: {video_dur:.1f}s")

            # -- Step D: 生成旁白时间轴音频 --
            # 将每段旁白 TTS 按视频段时序拼成一条完整旁白音轨
            narration_track = os.path.join(
                ctx.output_dir, "audio",
                f"u{un}_narration_track.mp3")
            self._build_narration_track(
                ctx, segments, unified_clips, un, narration_track)

            # -- Step E: BGM 生成 --
            bgm_path = os.path.join(
                ctx.output_dir, "audio", f"u{un}_bgm.mp3")
            if (not os.path.exists(bgm_path)
                    or os.path.getsize(bgm_path) < 100):
                ctx.log("    生成 BGM...")
                from vendor.qwen.client import chat_with_system
                music_prompt = chat_with_system(
                    "你是影视配乐师。根据剧本信息生成一个 AI 音乐生成的英文 prompt，"
                    "50-80词，只输出 prompt。要求：纯器乐配乐(instrumental only)，"
                    "禁止人声/歌词/哼唱/合唱，只用乐器和音效。",
                    f"标题：{unit.get('title','')}\n"
                    f"情感：{unit.get('emotion_tone','')}\n"
                    f"冲突：{unit.get('core_conflict','')}\n"
                    f"时长：{int(video_dur)}秒",
                    temperature=0.7, max_tokens=200,
                )

                try:
                    elevenlabs_key = os.environ.get(
                        "ELEVENLABS_API_KEY", "")
                    r = http_requests.post(
                        "https://api.elevenlabs.io/v1/music/generate",
                        headers={
                            "xi-api-key": elevenlabs_key,
                            "Content-Type": "application/json",
                        },
                        json={
                            "prompt": music_prompt,
                            "duration_seconds": int(video_dur) + 2,
                        },
                        timeout=120,
                    )
                    if r.status_code == 200:
                        with open(bgm_path, "wb") as f:
                            f.write(r.content)
                        ctx.log(f"    BGM: ✓ ElevenLabs "
                                f"({get_media_duration(bgm_path):.1f}s)")
                    else:
                        ctx.log(f"    BGM: ✗ ElevenLabs "
                                f"{r.status_code}")
                except Exception as e:
                    ctx.log(f"    BGM: ✗ {e}")

            # -- Step E2: BGM 预处理（VAD 裁剪首尾静音 + 循环填充）--
            bgm_processed_path = os.path.join(
                ctx.output_dir, "audio", f"u{un}_bgm_processed.mp3")
            if os.path.exists(bgm_path) and os.path.getsize(bgm_path) > 100:
                result = _preprocess_bgm(
                    bgm_path, video_dur, bgm_processed_path)
                if result:
                    bgm_path = bgm_processed_path

            # -- Step F: 三层音频混合 --
            # Layer 1: Video original audio (sound=on) → -35dB
            # Layer 2: Narration TTS → mean=-15dB
            # Layer 3: BGM (instrumental) → mean=-28dB
            has_narration = (os.path.exists(narration_track)
                            and os.path.getsize(narration_track) > 100)
            has_bgm = (os.path.exists(bgm_path)
                       and os.path.getsize(bgm_path) > 100)

            if has_narration or has_bgm:
                # 计算旁白音量调整
                narr_adjust_db = 0.0
                if has_narration:
                    narr_mean, narr_max = _measure_mean_volume(
                        narration_track, duration=video_dur)
                    narr_target_db = -15
                    narr_adjust_db = narr_target_db - narr_mean
                    # 防 clipping
                    if narr_adjust_db > 0:
                        max_after = narr_max + narr_adjust_db
                        if max_after > -1.0:
                            narr_adjust_db = min(
                                narr_adjust_db, -1.0 - narr_max)
                    ctx.log(f"    旁白: mean={narr_mean:.1f}dB → "
                            f"adjust={narr_adjust_db:.1f}dB")

                # 计算 BGM 音量调整
                bgm_adjust_db = 0.0
                if has_bgm:
                    bgm_mean, bgm_max = _measure_mean_volume(
                        bgm_path, duration=video_dur)
                    bgm_target_db = -28
                    bgm_adjust_db = bgm_target_db - bgm_mean
                    if bgm_adjust_db > 0:
                        max_after = bgm_max + bgm_adjust_db
                        if max_after > -1.0:
                            bgm_adjust_db = min(
                                bgm_adjust_db, -1.0 - bgm_max)
                    ctx.log(f"    BGM: mean={bgm_mean:.1f}dB → "
                            f"adjust={bgm_adjust_db:.1f}dB")

                fade_out_start = max(0, video_dur - 1)

                # 构建 filter_complex
                inputs = ["-i", concat_out]
                filter_parts = []
                mix_labels = []

                # Video audio → -35dB
                filter_parts.append(
                    "[0:a]volume=-35dB[vid_audio]")
                mix_labels.append("[vid_audio]")

                input_idx = 1
                if has_narration:
                    inputs += ["-i", narration_track]
                    filter_parts.append(
                        f"[{input_idx}:a]"
                        f"volume={narr_adjust_db:.1f}dB[narr]")
                    mix_labels.append("[narr]")
                    input_idx += 1

                if has_bgm:
                    inputs += ["-i", bgm_path]
                    filter_parts.append(
                        f"[{input_idx}:a]"
                        f"volume={bgm_adjust_db:.1f}dB,"
                        f"afade=t=out:st={fade_out_start:.0f}:d=1"
                        f"[bgm_adj]")
                    mix_labels.append("[bgm_adj]")
                    input_idx += 1

                n_inputs = len(mix_labels)
                mix_str = "".join(mix_labels)
                filter_parts.append(
                    f"{mix_str}amix=inputs={n_inputs}:"
                    f"duration=first:dropout_transition=2[aout]")

                filter_complex = ";".join(filter_parts)

                cmd = (
                    ["ffmpeg", "-y"]
                    + inputs
                    + ["-filter_complex", filter_complex,
                       "-map", "0:v", "-map", "[aout]",
                       "-c:v", "copy",
                       "-c:a", "aac", "-b:a", "192k",
                       final_output]
                )
                result = subprocess.run(
                    cmd, capture_output=True, timeout=120)
                if result.returncode == 0:
                    dur = get_media_duration(final_output)
                    size = os.path.getsize(final_output) // 1024
                    ctx.log(f"    ✓ 最终输出: u{un}_output.mp4 "
                            f"({dur:.1f}s, {size}KB)")
                else:
                    ctx.log("    ✗ 三层音频混合失败，尝试无 BGM 版本")
                    stderr = result.stderr.decode(
                        errors="replace")[:500]
                    ctx.log(f"    stderr: {stderr}")
                    # fallback: 只混旁白 + 视频音频
                    shutil.copy2(concat_out, final_output)
            else:
                shutil.copy2(concat_out, final_output)
                ctx.log("    无旁白/BGM，直接输出")

        return StageResult(success=True)

    # ================================================================
    # Stage 10: Quality Gate
    # ================================================================
    def stage_quality_gate(self, ctx: WorkflowContext) -> StageResult:
        from app.services.ffmpeg_utils import get_media_duration

        issues = []
        target = ctx.params.get("duration", 60)

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            final_output = os.path.join(
                ctx.output_dir, "videos", f"u{un}_output.mp4")
            if not os.path.exists(final_output):
                issues.append(f"单元 {un}: 最终视频不存在")
                continue

            dur = get_media_duration(final_output)

            # Duration check
            if dur < target * 0.5:
                issues.append(
                    f"单元 {un}: 时长 {dur:.0f}s < 50% of target "
                    f"{target}s")

            # BGM audibility
            concat_out = os.path.join(
                ctx.output_dir, "videos", f"u{un}_concat.mp4")
            if os.path.exists(concat_out):
                sample = str(min(15, dur / 2))
                vc_mean, _ = _measure_mean_volume(concat_out)
                vf_mean, _ = _measure_mean_volume(final_output)
                diff = abs(vc_mean - vf_mean)
                if diff < 1.0:
                    issues.append(
                        f"单元 {un}: BGM not audible "
                        f"(diff={diff:.1f}dB)")
                else:
                    ctx.log(f"  单元 {un} BGM ✓ "
                            f"(diff={diff:.1f}dB)")

            # Video completeness
            vp_path = os.path.join(
                ctx.output_dir, "grids",
                f"video_segments_u{un}.json")
            if os.path.exists(vp_path):
                with open(vp_path) as f:
                    segments = json.load(f).get(
                        "video_segments", [])
                total_segs = len(segments)
                generated = 0
                for seg in segments:
                    sn = seg["segment_number"]
                    vpath = os.path.join(
                        ctx.output_dir, "videos",
                        f"u{un}_seg{sn:02d}_final.mp4")
                    if (os.path.exists(vpath)
                            and os.path.getsize(vpath) > 1000):
                        generated += 1
                if generated < total_segs:
                    issues.append(
                        f"单元 {un}: 视频 {generated}/{total_segs}")

                # Narration coverage
                narr_segs = [
                    s for s in segments if s.get("narration_text")]
                narr_with_tts = [
                    s for s in narr_segs
                    if s.get("tts_path")
                    and os.path.exists(s["tts_path"])]
                if len(narr_with_tts) < len(narr_segs):
                    issues.append(
                        f"单元 {un}: 旁白 TTS "
                        f"{len(narr_with_tts)}/{len(narr_segs)}")

        ctx.quality_issues = issues
        ctx.quality_passed = len(issues) == 0

        if issues:
            ctx.log(f"\n  ⚠ ISSUES ({len(issues)}):")
            for issue in issues:
                ctx.log(f"    - {issue}")
            ctx.log("  Quality gate: FAILED")
        else:
            ctx.log("\n  ✓ Quality gate: PASSED")

        return StageResult(success=True)

    # ================================================================
    # Internal helpers
    # ================================================================

    def _build_narration_track(self, ctx, segments, unified_clips,
                               unit_number, output_path):
        """将各段旁白 TTS 按时序拼成一条完整旁白音轨。

        对每段视频，如有 TTS 则在该段起始时刻插入旁白音频，
        无 TTS 的段落保持静音。
        """
        from app.services.ffmpeg_utils import get_media_duration

        # 计算各段起始时间
        offsets = []
        current_offset = 0.0
        for i, c in enumerate(unified_clips):
            offsets.append(current_offset)
            if os.path.exists(c):
                current_offset += get_media_duration(c)
            else:
                current_offset += 3.0

        total_dur = current_offset
        if total_dur <= 0:
            return

        # 构建 filter_complex: 从静音基底开始，逐个 overlay TTS
        tts_inputs = []
        adelay_parts = []
        input_idx = 0

        for i, seg in enumerate(segments):
            tts_path = seg.get("tts_path", "")
            if not tts_path or not os.path.exists(tts_path):
                continue
            if i >= len(offsets):
                continue

            delay_ms = int(offsets[i] * 1000)
            tts_inputs.append(tts_path)
            adelay_parts.append((input_idx, delay_ms))
            input_idx += 1

        if not tts_inputs:
            return

        # 构建 ffmpeg 命令
        cmd = ["ffmpeg", "-y"]
        # 静音基底
        cmd += ["-f", "lavfi", "-i",
                f"anullsrc=r=44100:cl=stereo:d={total_dur:.2f}"]
        for tp in tts_inputs:
            cmd += ["-i", tp]

        filter_parts = []
        mix_inputs = ["[0:a]"]
        for j, (_, delay_ms) in enumerate(adelay_parts):
            label = f"tts{j}"
            filter_parts.append(
                f"[{j+1}:a]adelay={delay_ms}|{delay_ms},"
                f"apad=whole_dur={total_dur:.2f}[{label}]")
            mix_inputs.append(f"[{label}]")

        n = len(mix_inputs)
        mix_str = "".join(mix_inputs)
        filter_parts.append(
            f"{mix_str}amix=inputs={n}:"
            f"duration=first:normalize=0[out]")

        filter_complex = ";".join(filter_parts)
        cmd += ["-filter_complex", filter_complex,
                "-map", "[out]",
                "-c:a", "libmp3lame", "-b:a", "192k",
                output_path]

        result = subprocess.run(
            cmd, capture_output=True, timeout=120)
        if result.returncode == 0:
            ctx.log(f"    旁白音轨: ✓ ({total_dur:.1f}s)")
        else:
            stderr = result.stderr.decode(errors="replace")[:300]
            ctx.log(f"    旁白音轨: ✗ {stderr}")

    # ================================================================
    # Review 操作（旁白漫剧 V2 专用覆写）
    # ================================================================

    def op_review_storyboard(self, output_dir: str) -> dict:
        """返回分镜脚本摘要（所有 units + characters）"""
        sb_path = os.path.join(output_dir, "storyboard.json")
        if not os.path.exists(sb_path):
            return {"error": "storyboard.json not found"}
        with open(sb_path) as f:
            sb = json.load(f)
        units_summary = []
        for u in sb.get("units", []):
            script = u.get("script", [])
            narration_count = sum(
                1 for s in script if s.get("type") == "narration")
            action_count = sum(
                1 for s in script if s.get("type") == "action")
            units_summary.append({
                "unit_number": u.get("unit_number"),
                "title": u.get("title", ""),
                "core_conflict": u.get("core_conflict", ""),
                "emotion_tone": u.get("emotion_tone", ""),
                "characters": u.get("characters", []),
                "narration_count": narration_count,
                "action_count": action_count,
                "script_length": len(script),
            })
        characters = []
        for cp in sb.get("character_profiles", []):
            characters.append({
                "char_id": cp.get("char_id"),
                "name": cp.get("name"),
                "gender": cp.get("gender"),
                "age": cp.get("age"),
            })
        return {"units": units_summary, "characters": characters}

    def op_review_status(self, output_dir: str) -> dict:
        """返回整体进度状态"""
        stages_status = {}

        sb_path = os.path.join(output_dir, "storyboard.json")
        sb_exists = (os.path.exists(sb_path)
                     and os.path.getsize(sb_path) > 100)
        stages_status["storyboard"] = (
            "completed" if sb_exists else "pending")

        char_dir = os.path.join(output_dir, "characters")
        char_refs = (
            [f for f in os.listdir(char_dir)
             if f.startswith("charref_") and f.endswith(".png")]
            if os.path.isdir(char_dir) else [])
        stages_status["char_refs"] = (
            "completed" if char_refs else "pending")

        scene_dir = os.path.join(output_dir, "scenes")
        scene_files = (
            [f for f in os.listdir(scene_dir) if f.endswith(".png")]
            if os.path.isdir(scene_dir) else [])
        stages_status["scene_refs"] = (
            "completed" if scene_files else "pending")

        grids_dir = os.path.join(output_dir, "grids")
        grid_pngs = (
            [f for f in os.listdir(grids_dir)
             if f.startswith("grid_u") and f.endswith(".png")]
            if os.path.isdir(grids_dir) else [])
        stages_status["storyboard_grids"] = (
            "completed" if grid_pngs else "pending")

        vp_files = (
            [f for f in os.listdir(grids_dir)
             if f.startswith("video_segments_u") and f.endswith(".json")]
            if os.path.isdir(grids_dir) else [])
        stages_status["video_prompts"] = (
            "completed" if vp_files else "pending")

        num_units = 0
        if sb_exists:
            try:
                with open(sb_path) as f:
                    sb = json.load(f)
                num_units = len(sb.get("units", []))
            except Exception:
                pass

        audio_dir = os.path.join(output_dir, "audio")
        tts_files = (
            [f for f in os.listdir(audio_dir)
             if f.endswith("_narration.mp3")]
            if os.path.isdir(audio_dir) else [])
        stages_status["narration_tts"] = (
            "completed" if tts_files else "pending")

        video_dir = os.path.join(output_dir, "videos")
        video_files = (
            [f for f in os.listdir(video_dir) if f.endswith(".mp4")]
            if os.path.isdir(video_dir) else [])
        stages_status["video_gen"] = (
            "completed" if video_files else "pending")

        subtitled_files = (
            [f for f in os.listdir(video_dir)
             if f.endswith("_subtitled.mp4")]
            if os.path.isdir(video_dir) else [])
        stages_status["subtitle_burn"] = (
            "completed" if subtitled_files else "pending")

        output_videos = [
            f for f in (os.listdir(video_dir)
                        if os.path.isdir(video_dir) else [])
            if f.endswith("_output.mp4")]
        stages_status["assembly"] = (
            "completed" if output_videos else "pending")

        # Partial detection
        if grid_pngs and num_units > 0 and len(grid_pngs) < num_units:
            stages_status["storyboard_grids"] = "partial"
        if vp_files and num_units > 0 and len(vp_files) < num_units:
            stages_status["video_prompts"] = "partial"

        return {
            "stages": stages_status,
            "stats": {
                "num_units": num_units,
                "num_char_refs": len(char_refs),
                "num_scene_refs": len(scene_files),
                "num_grids": len(grid_pngs),
                "num_video_segments_files": len(vp_files),
                "num_tts_files": len(tts_files),
                "num_videos": len(video_files),
                "output_videos": [
                    os.path.join("videos", f) for f in output_videos],
            },
        }

    def op_review_tts(self, output_dir: str) -> dict:
        """旁白漫剧 V2 版 TTS 审查 — 按 unit/segment 结构返回。"""
        result = []
        for ui in range(1, 20):
            vp_path = os.path.join(
                output_dir, "grids",
                f"video_segments_u{ui}.json")
            if not os.path.exists(vp_path):
                break
            with open(vp_path) as f:
                segments = json.load(f).get("video_segments", [])
            for seg in segments:
                narration = seg.get("narration_text", "")
                if not narration:
                    continue
                entry = {
                    "unit": ui,
                    "segment": seg.get("segment_number"),
                    "narration_text": narration,
                    "emotion": seg.get("emotion", ""),
                    "tts_path": seg.get("tts_path", ""),
                    "tts_duration": seg.get("tts_duration"),
                    "final_duration": seg.get("final_duration"),
                }
                result.append(entry)
        return {"segments": result}

    def op_review_unit(self, output_dir: str, unit_number: int) -> dict:
        """返回某个 unit 的详细信息"""
        vp_path = os.path.join(
            output_dir, "grids",
            f"video_segments_u{unit_number}.json")
        if not os.path.exists(vp_path):
            return {
                "error": f"video_segments_u{unit_number}.json not found"}
        with open(vp_path) as f:
            vp_data = json.load(f)

        segments = []
        for seg in vp_data.get("video_segments", []):
            sn = seg.get("segment_number")
            entry = {
                "segment_number": sn,
                "start_frame": seg.get("start_frame"),
                "end_frame": seg.get("end_frame"),
                "is_memory": seg.get("is_memory", False),
                "camera_type": seg.get("camera_type", ""),
                "camera_movement": seg.get("camera_movement", ""),
                "emotion": seg.get("emotion", ""),
                "scene_description": seg.get(
                    "scene_description", ""),
                "narration_text": seg.get("narration_text", ""),
                "estimated_duration": seg.get("estimated_duration"),
                "final_duration": seg.get("final_duration"),
                "characters_in_frame": seg.get(
                    "characters_in_frame", []),
            }
            # Frame paths
            frame_dir = os.path.join(
                output_dir, "frames", f"u{unit_number}")
            frame_files = []
            if os.path.isdir(frame_dir):
                sf = seg.get("start_frame")
                ef = seg.get("end_frame")
                for fidx in ([sf, ef] if sf and ef else []):
                    fp = os.path.join(
                        frame_dir, f"frame_{fidx:02d}.png")
                    if os.path.exists(fp):
                        frame_files.append(
                            os.path.relpath(fp, output_dir))
                    else:
                        for fn in sorted(os.listdir(frame_dir)):
                            if (fn.startswith(f"frame_{fidx:02d}")
                                    and fn.endswith(".png")):
                                frame_files.append(
                                    os.path.relpath(
                                        os.path.join(frame_dir, fn),
                                        output_dir))
                                break
            entry["frame_paths"] = frame_files

            # Video path
            video_dir = os.path.join(output_dir, "videos")
            video_pattern = f"u{unit_number}_seg{sn:02d}"
            video_files = []
            if os.path.isdir(video_dir):
                for vf in sorted(os.listdir(video_dir)):
                    if video_pattern in vf and vf.endswith(".mp4"):
                        video_files.append(
                            os.path.relpath(
                                os.path.join(video_dir, vf),
                                output_dir))
            entry["video_paths"] = video_files

            # TTS path
            if seg.get("tts_path"):
                tts_abs = seg["tts_path"]
                entry["tts_path"] = (
                    os.path.relpath(tts_abs, output_dir)
                    if os.path.isabs(tts_abs) else tts_abs)

            segments.append(entry)

        # Grid info
        grid_path = os.path.join(
            output_dir, "grids",
            f"grid_u{unit_number}_shots.json")
        grid_info = None
        if os.path.exists(grid_path):
            with open(grid_path) as f:
                grid_info = json.load(f)

        return {
            "unit_number": unit_number,
            "segments": segments,
            "grid_shots": grid_info,
        }

    def op_review_characters(self, output_dir: str) -> dict:
        """返回角色资产（三视图路径，无音色信息）"""
        sb_path = os.path.join(output_dir, "storyboard.json")
        char_profiles = {}
        if os.path.exists(sb_path):
            with open(sb_path) as f:
                sb = json.load(f)
            for cp in sb.get("character_profiles", []):
                char_profiles[cp.get("char_id")] = cp

        char_dir = os.path.join(output_dir, "characters")
        characters = []
        for cid in sorted(char_profiles.keys()):
            profile = char_profiles[cid]
            ref_images = []
            if os.path.isdir(char_dir):
                for f in sorted(os.listdir(char_dir)):
                    if (f.startswith(f"charref_{cid}_")
                            and f.endswith(".png")):
                        ref_images.append(
                            os.path.relpath(
                                os.path.join(char_dir, f),
                                output_dir))

            characters.append({
                "char_id": cid,
                "name": profile.get("name", ""),
                "gender": profile.get("gender", ""),
                "age": profile.get("age", ""),
                "ref_images": ref_images,
            })

        return {"characters": characters}

    def op_review_assets(self, output_dir: str,
                         asset_type: str) -> dict:
        """返回指定类型的资产列表"""
        result = {"type": asset_type, "assets": []}

        if asset_type == "scene_refs":
            scene_dir = os.path.join(output_dir, "scenes")
            if os.path.isdir(scene_dir):
                for f in sorted(os.listdir(scene_dir)):
                    if f.endswith(".png"):
                        result["assets"].append({
                            "path": os.path.relpath(
                                os.path.join(scene_dir, f),
                                output_dir),
                            "filename": f,
                        })

        elif asset_type == "grids":
            grids_dir = os.path.join(output_dir, "grids")
            if os.path.isdir(grids_dir):
                for f in sorted(os.listdir(grids_dir)):
                    if f.endswith(".png"):
                        result["assets"].append({
                            "path": os.path.relpath(
                                os.path.join(grids_dir, f),
                                output_dir),
                            "filename": f,
                        })

        elif asset_type == "frames":
            frame_dir = os.path.join(output_dir, "frames")
            if os.path.isdir(frame_dir):
                for sub in sorted(os.listdir(frame_dir)):
                    sub_path = os.path.join(frame_dir, sub)
                    if os.path.isdir(sub_path):
                        for f in sorted(os.listdir(sub_path)):
                            if f.endswith(".png"):
                                result["assets"].append({
                                    "path": os.path.relpath(
                                        os.path.join(sub_path, f),
                                        output_dir),
                                    "filename": f,
                                    "unit": sub,
                                })

        elif asset_type == "videos":
            video_dir = os.path.join(output_dir, "videos")
            if os.path.isdir(video_dir):
                for f in sorted(os.listdir(video_dir)):
                    if f.endswith(".mp4"):
                        fpath = os.path.join(video_dir, f)
                        result["assets"].append({
                            "path": os.path.relpath(
                                fpath, output_dir),
                            "filename": f,
                            "size_mb": round(
                                os.path.getsize(fpath) / 1024 / 1024,
                                1),
                        })

        else:
            from app.workflows.candidates import CandidateManager
            cm = CandidateManager(output_dir)
            cm.migrate_from_existing(output_dir)
            all_assets = cm.get_all_for_type(asset_type)
            for key, entry in all_assets.items():
                candidates = cm.list_candidates(key)
                result["assets"].append({
                    "key": key, "candidates": candidates})

        return result

    # ================================================================
    # Edit 操作（旁白漫剧 V2 专用覆写）
    # ================================================================

    def op_edit_storyboard(self, output_dir: str, segment: int,
                           field: str, value: str,
                           sub_idx: int = None) -> dict:
        """旁白漫剧 V2 版分镜编辑 — segment 参数对应 unit_number。"""
        sb_path = os.path.join(output_dir, "storyboard.json")
        if not os.path.exists(sb_path):
            return {"error": "storyboard.json not found"}
        with open(sb_path) as f:
            sb = json.load(f)
        target = None
        for u in sb.get("units", []):
            if u.get("unit_number") == segment:
                target = u
                break
        if not target:
            return {"error": f"Unit {segment} not found"}
        allowed_fields = {
            "title", "core_conflict", "emotion_tone", "ending_hook"}
        if field not in allowed_fields:
            return {
                "error": f"Field '{field}' not editable. "
                         f"Allowed: {allowed_fields}"}
        old_value = target.get(field)
        target[field] = value
        with open(sb_path, "w", encoding="utf-8") as f:
            json.dump(sb, f, ensure_ascii=False, indent=2)
        return {
            "unit": segment, "field": field,
            "old_value": old_value, "new_value": value,
        }

    # ================================================================
    # Reroll 操作（旁白漫剧 V2 专用覆写）
    # ================================================================

    def op_reroll_tts(self, output_dir: str, segment: int,
                      voice: str = None, emotion: str = None) -> dict:
        """旁白漫剧 V2 不使用 narration_manga TTS reroll，
        请使用 op_reroll_narration_tts。"""
        return {
            "error": "Use 'reroll narration_tts' for narration_manga_v2 "
                     "(specify --unit and --seg)"}

    def op_reroll_narration_tts(self, output_dir: str,
                                unit_number: int,
                                segment_number: int,
                                voice_id: str = None) -> dict:
        """重新生成单个旁白段的 TTS。"""
        from app.workflows.candidates import CandidateManager
        from app.services.ffmpeg_utils import get_media_duration

        cm = CandidateManager(output_dir)
        cm.load()

        vp_path = os.path.join(
            output_dir, "grids",
            f"video_segments_u{unit_number}.json")
        if not os.path.exists(vp_path):
            return {
                "success": False,
                "message": f"video_segments_u{unit_number}.json 不存在"}
        with open(vp_path) as f:
            vp_data = json.load(f)

        segments = vp_data.get("video_segments", [])
        seg = None
        for s in segments:
            if s["segment_number"] == segment_number:
                seg = s
                break
        if not seg:
            return {
                "success": False,
                "message": f"段 {segment_number} 不存在"}

        narration = seg.get("narration_text", "")
        if not narration:
            return {
                "success": False,
                "message": f"段 {segment_number} 无旁白文字"}

        final_voice = voice_id or "female-shaonv"
        emotion = seg.get("emotion", "calm")
        valid_emotions = {
            "happy", "sad", "angry", "fearful",
            "disgusted", "surprised", "calm", "fluent",
        }
        if emotion == "whisper":
            emotion = "calm"
        if emotion not in valid_emotions:
            emotion = "calm"

        async def _gen():
            from app.ai.providers.minimax_tts import MiniMaxTTSProvider
            provider = MiniMaxTTSProvider()
            job_id = await provider.submit_job({
                "text": narration,
                "voice_id": final_voice,
                "speed": 0.9,
                "emotion": emotion,
            })
            status = await provider.poll_job(job_id)
            return status.result_data

        try:
            data = asyncio.run(_gen())
        except Exception as e:
            return {"success": False, "message": f"TTS 生成失败: {e}"}

        if not data:
            return {"success": False, "message": "TTS 生成失败"}

        tts_asset_key = (
            f"narration_tts:u{unit_number}_seg{segment_number:02d}")
        version = cm.next_version(tts_asset_key)
        os.makedirs(os.path.join(output_dir, "audio"), exist_ok=True)
        audio_path = os.path.join(
            output_dir, "audio",
            f"u{unit_number}_seg{segment_number:02d}"
            f"_narration_v{version}.mp3")
        with open(audio_path, "wb") as f:
            f.write(data)

        tts_dur = get_media_duration(audio_path)
        final_dur = max(
            seg.get("estimated_duration", 3),
            math.ceil(tts_dur), 3)

        seg["tts_path"] = os.path.abspath(audio_path)
        seg["tts_duration"] = tts_dur
        seg["final_duration"] = final_dur
        with open(vp_path, "w", encoding="utf-8") as f:
            json.dump(vp_data, f, ensure_ascii=False, indent=2)

        rel = os.path.relpath(audio_path, output_dir)
        cm.register(tts_asset_key, rel)

        print(f"  [reroll_narration_tts] 段{segment_number}: "
              f"v{version} voice={final_voice} "
              f"tts={tts_dur:.1f}s final={final_dur}s")
        return {
            "success": True,
            "message": (f"TTS u{unit_number}_seg{segment_number:02d} "
                        f"重新生成 v{version}"),
            "path": audio_path,
            "tts_duration": tts_dur,
            "final_duration": final_dur,
            "voice_id": final_voice,
            "candidates": cm.list_candidates(tts_asset_key),
        }

    def op_reroll_video(self, output_dir: str, seg: int,
                        sub: int) -> dict:
        """旁白漫剧 V2 不使用 sub_shot video reroll，
        请使用 op_reroll_video_segment。"""
        return {
            "error": "Use 'reroll video_segment' for narration_manga_v2 "
                     "(specify --unit and --seg)"}

    def op_reroll_video_segment(self, output_dir: str,
                                unit_number: int,
                                segment_number: int) -> dict:
        """重新生成单个视频段。"""
        from app.workflows.candidates import CandidateManager
        from vendor.kling.client import KlingClient
        from app.services.ffmpeg_utils import get_media_duration

        cm = CandidateManager(output_dir)
        cm.load()
        client = KlingClient()

        vp_path = os.path.join(
            output_dir, "grids",
            f"video_segments_u{unit_number}.json")
        if not os.path.exists(vp_path):
            return {
                "success": False,
                "message": (f"video_segments_u{unit_number}.json "
                            f"不存在")}
        with open(vp_path) as f:
            vp_data = json.load(f)

        segments = vp_data.get("video_segments", [])
        seg = None
        for s in segments:
            if s["segment_number"] == segment_number:
                seg = s
                break
        if not seg:
            return {
                "success": False,
                "message": f"段 {segment_number} 不存在"}

        # 加载角色参考图
        sb_path = os.path.join(output_dir, "storyboard.json")
        characters = []
        if os.path.exists(sb_path):
            with open(sb_path) as f:
                sb = json.load(f)
            characters = sb.get("character_profiles", [])

        char_images = {}
        for c in characters:
            cid = c["char_id"]
            sel = cm.get_selected_path(f"char_ref:{cid}")
            if sel and os.path.exists(sel):
                char_images[cid] = sel

        # 首帧
        frames_dir = os.path.join(
            output_dir, "frames", f"u{unit_number}")
        frame_start_path = os.path.join(
            frames_dir,
            f"frame_{seg['start_frame']:02d}.png")
        fkey_start = (
            f"frame:u{unit_number}_f{seg['start_frame']:02d}")
        sel_start = cm.get_selected_path(fkey_start)
        if sel_start and os.path.exists(sel_start):
            frame_start_path = sel_start

        if not os.path.exists(frame_start_path):
            return {
                "success": False,
                "message": f"首帧不存在: {frame_start_path}"}

        # 角色参考
        char_refs = []
        for cid in seg.get("characters_in_frame", []):
            if cid in char_images:
                char_refs.append({
                    "image": client.encode_image(char_images[cid])})

        # 构建参数 (9:16, sound=on)
        duration = str(max(
            seg.get("final_duration",
                     seg.get("estimated_duration", 3)), 3))
        i2v_params = {
            "model_name": "kling-v3",
            "image": client.encode_image(frame_start_path),
            "prompt": seg.get("video_prompt", ""),
            "mode": "std",
            "duration": duration,
            "aspect_ratio": "9:16",
            "sound": "on",
        }
        if char_refs:
            i2v_params["subject_reference"] = char_refs[:1]

        # 提交
        task_id = None
        try:
            for attempt in range(3):
                result = client._post(
                    "/v1/videos/image2video", i2v_params)
                if result.get("code") == 0:
                    task_id = result["data"]["task_id"]
                    break
                print(f"  [reroll_video] 段{segment_number}: "
                      f"重试 {attempt+1}")
                time.sleep(10)
        except Exception as e:
            return {
                "success": False,
                "message": f"image2video 提交失败: {e}"}

        if not task_id:
            return {
                "success": False,
                "message": "image2video 提交失败"}

        # 轮询
        data = client.poll_task(
            task_id, task_type="video",
            max_wait=600, interval=10)
        if not data:
            return {"success": False, "message": "image2video 超时"}

        video_info = data["task_result"]["videos"][0]

        video_asset_key = (
            f"video:u{unit_number}_seg{segment_number:02d}")
        version = cm.next_version(video_asset_key)
        os.makedirs(
            os.path.join(output_dir, "videos"), exist_ok=True)
        final_path = os.path.join(
            output_dir, "videos",
            f"u{unit_number}_seg{segment_number:02d}"
            f"_v{version}.mp4")

        if not _download_with_retry(video_info["url"], final_path):
            return {"success": False, "message": "视频下载失败"}

        rel = os.path.relpath(final_path, output_dir)
        cm.register(video_asset_key, rel)

        dur = get_media_duration(final_path)
        sz = os.path.getsize(final_path) / 1024 / 1024
        print(f"  [reroll_video] 段{segment_number}: "
              f"v{version} ({dur:.1f}s, {sz:.1f}MB)")
        return {
            "success": True,
            "message": (
                f"视频段 u{unit_number}_seg{segment_number:02d} "
                f"重新生成 v{version}"),
            "path": final_path,
            "duration": dur,
            "size_mb": round(sz, 1),
            "candidates": cm.list_candidates(video_asset_key),
        }

    def op_reroll_frame(self, output_dir: str, unit_number: int,
                        frame_number: int) -> dict:
        """抽卡单个宫格帧。重新生成整个宫格图并切帧。"""
        from PIL import Image
        from app.workflows.candidates import CandidateManager

        cm = CandidateManager(output_dir)
        cm.load()

        asset_key = f"frame:u{unit_number}_f{frame_number:02d}"

        # 检查备选
        candidates = cm.list_candidates(asset_key)
        if candidates:
            unselected = [
                c for c in candidates
                if not c["is_selected"] and c["exists"]]
            if unselected:
                target = unselected[0]
                cm.select(asset_key, target["version"])
                print(f"  [reroll_frame] 切换到备选版本 "
                      f"v{target['version']}")
                return {
                    "success": True,
                    "message": (f"切换到备选版本 "
                                f"v{target['version']}"),
                    "path": target["abs_path"],
                    "candidates": cm.list_candidates(asset_key),
                }

        if len(candidates) >= 3:
            return {
                "success": False,
                "message": (
                    f"帧 u{unit_number}_f{frame_number:02d} "
                    f"已达最大抽卡次数 (3)"),
            }

        # 重新生成宫格图
        print(f"  [reroll_frame] 重新生成单元 {unit_number} "
              f"的 4x4 宫格图...")

        sb_path = os.path.join(output_dir, "storyboard.json")
        if not os.path.exists(sb_path):
            return {
                "success": False,
                "message": "storyboard.json 不存在"}
        with open(sb_path) as f:
            sb = json.load(f)

        unit = None
        for u in sb.get("units", []):
            if u.get("unit_number") == unit_number:
                unit = u
                break
        if not unit:
            return {
                "success": False,
                "message": f"单元 {unit_number} 不存在"}

        characters = sb.get("character_profiles", [])
        char_name_map = {}
        for c in characters:
            char_name_map[c["name"]] = c["char_id"]
            base_name = c["name"].split("(")[0].split("（")[0].strip()
            char_name_map[base_name] = c["char_id"]

        # 加载 shots
        shots_path = os.path.join(
            output_dir, "grids",
            f"grid_u{unit_number}_shots.json")
        if not os.path.exists(shots_path):
            return {
                "success": False,
                "message": "shots.json 不存在，"
                           "请先运行 storyboard_grids"}
        with open(shots_path) as f:
            grid_data = json.load(f)
        shots = grid_data.get("shots", [])
        style_tags = grid_data.get("style_tags", [])
        if isinstance(style_tags, list):
            style_tags = ", ".join(style_tags)

        # 收集参考图
        unit_chars = unit.get("characters", [])
        ref_images = []
        ref_labels = []
        for char_name in unit_chars:
            cid = char_name_map.get(char_name)
            if cid:
                char_ref_sel = cm.get_selected_path(
                    f"char_ref:{cid}")
                if (char_ref_sel
                        and os.path.exists(char_ref_sel)):
                    ref_images.append(char_ref_sel)
                    char_profile = next(
                        (cp for cp in characters
                         if cp["char_id"] == cid), {})
                    appearance = char_profile.get(
                        "appearance_prompt", "")[:80]
                    ref_labels.append(
                        f'Character "{char_name}": {appearance}')

        for si in range(len(unit.get("key_scenes", []))):
            scene_sel = cm.get_selected_path(
                f"scene_ref:u{unit_number}_s{si+1}")
            if scene_sel and os.path.exists(scene_sel):
                ref_images.append(scene_sel)
                loc = unit["key_scenes"][si].get("location", "")
                ref_labels.append(f'Scene reference: {loc}')

        # Gemini prompt (9:16)
        char_ref_labels = "\n".join(
            [f"- Image {i+1}: {lbl}"
             for i, lbl in enumerate(ref_labels)]
        ) if ref_labels else "No character references available."

        shots_text = "\n".join(
            [f'Panel {s.get("shot_number", i+1)}: '
             f'{_strip_shot_labels(s.get("prompt_text", s.get("prompt", "")))}'
             for i, s in enumerate(shots)]
        )

        gemini_prompt = GRID_IMAGE_PROMPT_TEMPLATE.format(
            char_ref_labels=char_ref_labels,
            shots_text=shots_text,
            style_tags=style_tags,
        )

        grid_asset_key = f"grid:u{unit_number}"
        grid_version = cm.next_version(grid_asset_key)
        os.makedirs(
            os.path.join(output_dir, "grids"), exist_ok=True)
        out_path = os.path.join(
            output_dir, "grids",
            f"grid_u{unit_number}_v{grid_version}.png")

        try:
            result = generate_image_with_refs(
                prompt=gemini_prompt,
                ref_images=ref_images if ref_images else None,
                ref_labels=ref_labels if ref_labels else None,
                output_path=out_path,
                image_size="4K",
            )
        except Exception as e:
            return {
                "success": False,
                "message": f"宫格图生成失败: {e}"}

        if not result:
            return {"success": False, "message": "宫格图生成失败"}

        rel_grid = os.path.relpath(result, output_dir)
        cm.register(grid_asset_key, rel_grid)
        print(f"  [reroll_frame] 新宫格图 v{grid_version}")

        # 切出 16 帧 (portrait)
        grid_img = Image.open(result)
        frames_dir = os.path.join(
            output_dir, "frames", f"u{unit_number}")
        os.makedirs(frames_dir, exist_ok=True)

        crop_boxes, resize_target = _detect_grid_panels(grid_img)

        target_path = None
        for row in range(4):
            for col in range(4):
                idx = row * 4 + col + 1
                fkey = f"frame:u{unit_number}_f{idx:02d}"
                fversion = cm.next_version(fkey)
                frame_path = os.path.join(
                    frames_dir,
                    f"frame_{idx:02d}_v{fversion}.png")
                cell = grid_img.crop(crop_boxes[row][col])
                cell = cell.resize(
                    resize_target, Image.LANCZOS)
                cell.save(frame_path)
                rel = os.path.relpath(frame_path, output_dir)

                if idx == frame_number:
                    cm.register(fkey, rel)
                    target_path = frame_path
                else:
                    old_selected = None
                    existing = cm.list_candidates(fkey)
                    for c in existing:
                        if c["is_selected"]:
                            old_selected = c["version"]
                            break
                    cm.register(fkey, rel)
                    if old_selected is not None:
                        cm.select(fkey, old_selected)

        print(f"  [reroll_frame] 16 帧已切出，"
              f"目标帧 f{frame_number:02d} 已更新")
        return {
            "success": True,
            "message": (f"重新生成宫格图 v{grid_version}，"
                        f"帧 f{frame_number:02d} 已更新"),
            "path": target_path,
            "candidates": cm.list_candidates(asset_key),
        }
