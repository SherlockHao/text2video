"""
对话漫剧工作流模板 — Dialogue-driven manga drama
人物有自己的对话语言（替代旁白）。

10 Stages:
  1. storyboard        — LLM 分镜（含角色对话 + 角色档案）
  2. char_refs         — 角色三视图参考图 (Jimeng T2I)
  3. char_voices       — 角色音色库 (LLM 匹配 + MiniMax TTS + 回忆混响)
  4. scene_refs        — 场景参考图 (Gemini + 角色参考)
  5. storyboard_grids  — 4×4 宫格分镜图 (Gemini 4K)
  6. video_prompts     — 4K 切图 + LLM 分镜视频指令 (15段)
  7. dialogue_tts      — 多角色 TTS + 时长校准
  8. video_gen         — Kling V3 image2video + lip-sync
  9. subtitle_burn     — 字幕压制 (FFmpeg drawtext)
  10. assembly         — 统一帧率 + 拼接 + BGM
"""

import json
import os
import time
import asyncio
import subprocess

from app.workflows.base import BaseWorkflow, WorkflowContext, StageResult
from app.workflows.registry import register_workflow
from app.workflows.interactive import InteractiveOpsMixin
from vendor.qwen.client import chat_json
from vendor.jimeng.t2i import generate_image
from vendor.gemini.client import generate_image_with_refs

# ── 常量 ─────────────────────────────────────────────────────────

MAX_INPUT_LENGTH = 15000  # 最大输入字数
LLM_MAX_RETRIES = 3       # LLM 输出校验失败重试次数

import re as _re_module

def _strip_shot_labels(text: str) -> str:
    """去掉 prompt 开头的景别缩写（EWS, CU, MS 等）避免 Gemini 渲染为文字"""
    return _re_module.sub(
        r'^(Extreme Wide Shot|EWS|Wide Shot|WS|Long Shot|LS|'
        r'Medium Shot|MS|Medium Close[- ]?Up|MCU|Close[- ]?Up|CU|'
        r'Extreme Close[- ]?Up|ECU|POV|Full Shot|FS|'
        r'Low [Aa]ngle|High [Aa]ngle|Silhouette [Ss]hot|Final [Cc]lose[- ]?[Uu]p)'
        r'[,\s]+', '', text).strip()


def _validated_chat_json(system_prompt, user_prompt, required_keys,
                         temperature=0.5, max_tokens=8192, list_key=None,
                         list_length=None):
    """调用 LLM 并校验返回 JSON 的必需字段，失败重试。

    Args:
        required_keys: 顶层必需字段列表
        list_key: 如果指定，检查该字段是否为列表
        list_length: 如果指定，检查列表长度是否匹配
    """
    for attempt in range(LLM_MAX_RETRIES):
        try:
            result = chat_json(system_prompt, user_prompt,
                               temperature=temperature, max_tokens=max_tokens)

            # 校验顶层字段
            missing = [k for k in required_keys if k not in result]
            if missing:
                print(f"  LLM 校验失败 (attempt {attempt+1}): 缺少字段 {missing}")
                continue

            # 校验列表字段
            if list_key:
                lst = result.get(list_key, [])
                if not isinstance(lst, list) or len(lst) == 0:
                    print(f"  LLM 校验失败 (attempt {attempt+1}): {list_key} 非列表或为空")
                    continue
                if list_length and len(lst) != list_length:
                    print(f"  LLM 校验失败 (attempt {attempt+1}): "
                          f"{list_key} 长度 {len(lst)} != {list_length}")
                    continue

            return result

        except Exception as e:
            print(f"  LLM 调用异常 (attempt {attempt+1}): {e}")

    raise RuntimeError(f"LLM 调用 {LLM_MAX_RETRIES} 次均失败")

# MiniMax 可用中文音色
MINIMAX_VOICES = {
    # 男声
    "male-qn-qingse": "青涩青年，年轻清爽的男声",
    "male-qn-jingying": "精英青年，沉稳干练的男声",
    "male-qn-badao": "霸道青年，低沉有力的男声",
    "male-qn-daxuesheng": "大学生，阳光活泼的男声",
    "presenter_male": "男性主持人，标准浑厚",
    "audiobook_male_1": "男性有声书1，温和叙述",
    "audiobook_male_2": "男性有声书2，沉稳讲述",
    "Deep_Voice_Man": "低沉男声，深邃有磁性",
    "Young_Knight": "年轻骑士，英气少年",
    "Determined_Man": "坚定男声，刚毅果断",
    "Imposing_Manner": "威严男声，气场强大",
    "cute_boy": "可爱男孩，稚嫩童声",
    # 女声
    "female-shaonv": "少女音，清亮活泼的年轻女声",
    "female-yujie": "御姐音，成熟知性的女声",
    "female-chengshu": "成熟女性，温柔沉稳",
    "female-tianmei": "甜美女性，柔软甜蜜",
    "presenter_female": "女性主持人，端庄大方",
    "audiobook_female_1": "女性有声书1，温柔叙述",
    "audiobook_female_2": "女性有声书2，知性讲述",
    "Wise_Woman": "智慧女性，从容淡定",
    "Calm_Woman": "沉静女性，安宁平和",
}

# LLM 音色匹配 Prompt
VOICE_MATCH_SYSTEM_PROMPT = """你是一个语音导演。根据角色的声音特征描述，从可用音色列表中选择最匹配的音色ID。
同时为每个角色生成一句符合其性格的自我介绍台词（20-40字，第一人称）。
同时根据角色性格选择最合适的情感：happy/sad/angry/fearful/disgusted/surprised/calm

严格输出JSON格式：
{{
  "matches": [
    {{
      "char_id": "角色ID",
      "voice_id": "选中的音色ID",
      "reason": "选择理由（一句话）",
      "intro_text": "角色自我介绍台词",
      "emotion": "情感"
    }}
  ]
}}"""

VOICE_MATCH_USER_PROMPT = """【角色列表】：
{characters_json}

【可用音色】：
{voices_json}

请为每个角色选择最匹配的音色，并生成自我介绍台词。"""


# ── Storyboard Prompt ────────────────────────────────────────────

DIALOGUE_STORYBOARD_SYSTEM_PROMPT = """你是一个漫剧推广视频策划师。

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
7. script — 本单元的剧本，是一个对话/动作列表，每条包含：
   - type: "dialogue"（台词）或 "action"（动作/画面描写）
   - character: 说话或动作的角色名（action 类型可以为 null 表示环境描写）
   - content: 台词内容或动作描写

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
        {{"type": "action", "character": null, "content": "环境描写..."}},
        {{"type": "dialogue", "character": "角色A", "content": "台词内容..."}},
        {{"type": "action", "character": "角色B", "content": "角色B的动作描写..."}},
        {{"type": "dialogue", "character": "角色B", "content": "台词内容..."}}
      ]
    }}
  ],
  "character_profiles": [
    {{
      "name": "角色名",
      "char_id": "char_001",
      "gender": "男/女",
      "age": "年龄描述",
      "appearance_prompt": "角色外貌的文生图提示词，用于生成角色参考图",
      "voice_trait": "声音特征描述（如：低沉沙哑/清亮少女/沧桑中年）"
    }}
  ]
}}"""

DIALOGUE_STORYBOARD_USER_PROMPT = """请阅读以下小说文本，识别有效冲突单元，并按要求输出JSON。

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

请生成16个分镜的英文 prompt。"""

# Gemini 宫格图生成 prompt 模板
GRID_IMAGE_PROMPT_TEMPLATE = """Generate a 4x4 storyboard grid image (16 panels in a single image, 4 rows × 4 columns). The overall image MUST be in 16:9 widescreen aspect ratio. Each panel should also be 16:9 widescreen.

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

# ── 分镜视频 Prompt ──────────────────────────────────────────────

VIDEO_SEGMENTS_SYSTEM_PROMPT = """你是一个专业的漫剧视频分镜导演。

你将收到一个剧本单元的完整信息和16个分镜关键帧描述。你需要将相邻两帧组成一个视频分镜段（共15段），并为每段输出详细的视频生成指令。

【规则】
1. 每段视频由"首帧(帧N)"和"尾帧(帧N+1)"定义
2. 判断首尾帧是否属于同一场景（same_scene=true），如果场景跳变则标记 same_scene=false
3. 如果该段包含角色台词（is_dialogue=true），标注台词内容、说话角色、角色朝向，且镜头运动要克制（少转场）
4. 根据内容类型估算时长：台词段=台词字数÷4秒（向上取整，最小3秒），纯动作=3-5秒，情感特写=3秒，环境建立=4-6秒。所有段最小3秒。
5. 标注涉及的角色（用 char_id 关联）和可能需要的场景参考图
6. 判断该段是否为回忆/闪回场景（is_memory=true），依据剧本中的"回忆"、"闪回"、"过去"等描写

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
      "is_dialogue": true,
      "dialogue": {{
        "character": "角色名",
        "char_id": "char_001",
        "content": "台词内容",
        "facing": "朝向（如：面向镜头/侧面/背对镜头）"
      }},
      "characters_in_frame": ["char_001", "char_002"],
      "scene_ref_id": "u1_s1",
      "estimated_duration": 5,
      "video_prompt": "中文视频生成提示词，描述画面动态变化"
    }}
  ]
}}

注意：
- dialogue 字段仅在 is_dialogue=true 时存在
- is_memory=true 表示回忆/闪回场景
- scene_ref_id 对应之前生成的场景参考图ID（格式: u{{unit}}_s{{scene}}），选最接近的
- video_prompt 要描述从首帧到尾帧的动态变化过程"""

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

请为相邻帧组合生成15段视频分镜指令。"""


# ── Workflow ─────────────────────────────────────────────────────

@register_workflow
class DialogueMangaWorkflow(InteractiveOpsMixin, BaseWorkflow):
    name = "dialogue_manga"
    display_name = "对话漫剧"
    stages = [
        "storyboard",
        "char_refs",
        "char_voices",
        "scene_refs",
        "storyboard_grids",
        "video_prompts",
        "dialogue_tts",
        "video_gen",
        "subtitle_burn",
        "assembly",
    ]

    # ================================================================
    # Stage 1: Dialogue Storyboard
    # ================================================================
    def stage_storyboard(self, ctx: WorkflowContext) -> StageResult:
        # 字数检查
        input_len = len(ctx.input_text)
        if input_len > MAX_INPUT_LENGTH:
            return StageResult(
                success=False,
                message=f"输入文本 {input_len} 字超过上限 {MAX_INPUT_LENGTH} 字，"
                        f"请先使用 novel_splitter 分集后再输入单集文本。"
            )

        sb_path = f"{ctx.output_dir}/storyboard.json"

        if os.path.exists(sb_path) and os.path.getsize(sb_path) > 100:
            ctx.log(f"  ★ 断点恢复: 加载已有 storyboard.json")
            with open(sb_path) as f:
                sb = json.load(f)
        else:
            ctx.log(f"  输入: {input_len} 字")
            user_prompt = DIALOGUE_STORYBOARD_USER_PROMPT.format(
                input_text=ctx.input_text
            )
            sb = _validated_chat_json(
                system_prompt=DIALOGUE_STORYBOARD_SYSTEM_PROMPT,
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
        ctx.segments = units  # 复用 segments 字段存储 units
        ctx.characters = sb.get("character_profiles", [])

        # 日志输出
        ctx.log(f"  {len(units)} 个冲突单元, {len(ctx.characters)} 个角色")
        for c in ctx.characters:
            ctx.log(f"    角色: {c['name']} ({c.get('char_id','?')}) "
                    f"{c.get('gender','?')} | 声音: {c.get('voice_trait','?')}")

        for u in units:
            un = u.get("unit_number", "?")
            title = u.get("title", "")
            tone = u.get("emotion_tone", "")
            script = u.get("script", [])
            dialogues = [s for s in script if s.get("type") == "dialogue"]
            actions = [s for s in script if s.get("type") == "action"]
            chars = u.get("characters", [])

            ctx.log(f"\n  ── 单元 {un}: {title} [{tone}] ──")
            ctx.log(f"    冲突: {u.get('core_conflict', '')}")
            ctx.log(f"    人物: {', '.join(chars)}")
            ctx.log(f"    剧本: {len(dialogues)} 条对话, {len(actions)} 条动作")
            ctx.log(f"    钩子: {u.get('ending_hook', '')}")

            # 打印关键场景
            for i, sc in enumerate(u.get("key_scenes", [])):
                ctx.log(f"    场景{i+1}: [{sc.get('location','')}] {sc.get('description','')[:60]}")

            # 打印前几条剧本
            for j, line in enumerate(script[:6]):
                t = line.get("type", "?")
                ch = line.get("character", "")
                ct = line.get("content", "")[:60]
                if t == "dialogue":
                    ctx.log(f"    💬 {ch}: \"{ct}\"")
                else:
                    ctx.log(f"    🎬 {f'[{ch}] ' if ch else ''}{ct}")
            if len(script) > 6:
                ctx.log(f"    ... (还有 {len(script)-6} 条)")

        return StageResult(success=True)

    # ================================================================
    # Stage 2: Character Reference Images (三视图)
    # ================================================================
    def stage_char_refs(self, ctx: WorkflowContext) -> StageResult:
        os.makedirs(f"{ctx.output_dir}/characters", exist_ok=True)

        for c in ctx.characters:
            cid = c["char_id"]
            asset_key = f"char_ref:{cid}"

            # 断点恢复
            if not ctx.candidates.is_invalidated(asset_key):
                sel = ctx.candidates.get_selected_path(asset_key)
                if sel and os.path.exists(sel) and os.path.getsize(sel) > 100:
                    ctx.char_images[cid] = sel
                    ctx.log(f"  {c['name']} ({cid}): ★ 已存在")
                    continue
            ctx.candidates.clear_invalidation(asset_key)

            appearance = c.get("appearance_prompt", "")
            gender = c.get("gender", "")
            gender_hint = "男性角色" if "男" in gender else "女性角色" if "女" in gender else ""

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
                output_dir=f"{ctx.output_dir}/characters",
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
    # Stage 3: Character Voices (语音音色库)
    # ================================================================
    def stage_char_voices(self, ctx: WorkflowContext) -> StageResult:
        os.makedirs(f"{ctx.output_dir}/characters", exist_ok=True)

        # ── Step 1: LLM 匹配 voice_trait → MiniMax voice_id ──
        voice_map_path = f"{ctx.output_dir}/voice_map.json"

        if os.path.exists(voice_map_path) and os.path.getsize(voice_map_path) > 10:
            ctx.log(f"  ★ 断点恢复: 加载已有 voice_map.json")
            with open(voice_map_path) as f:
                voice_map = json.load(f)
        else:
            chars_for_llm = [
                {
                    "char_id": c["char_id"],
                    "name": c["name"],
                    "gender": c.get("gender", ""),
                    "voice_trait": c.get("voice_trait", ""),
                }
                for c in ctx.characters
            ]

            ctx.log(f"  LLM 匹配音色: {len(chars_for_llm)} 个角色")
            result = _validated_chat_json(
                system_prompt=VOICE_MATCH_SYSTEM_PROMPT,
                user_prompt=VOICE_MATCH_USER_PROMPT.format(
                    characters_json=json.dumps(chars_for_llm, ensure_ascii=False, indent=2),
                    voices_json=json.dumps(MINIMAX_VOICES, ensure_ascii=False, indent=2),
                ),
                required_keys=["matches"],
                list_key="matches",
                temperature=0.3,
                max_tokens=2048,
            )

            # 构建 voice_map: char_id → {voice_id, intro_text, emotion, reason}
            voice_map = {}
            for m in result.get("matches", []):
                voice_map[m["char_id"]] = {
                    "voice_id": m["voice_id"],
                    "intro_text": m["intro_text"],
                    "emotion": m.get("emotion", "calm"),
                    "reason": m.get("reason", ""),
                }

            with open(voice_map_path, "w", encoding="utf-8") as f:
                json.dump(voice_map, f, ensure_ascii=False, indent=2)

        # 打印匹配结果
        for c in ctx.characters:
            cid = c["char_id"]
            vm = voice_map.get(cid, {})
            ctx.log(f"  {c['name']}: voice_id={vm.get('voice_id','?')} "
                    f"emotion={vm.get('emotion','?')} | {vm.get('reason','')}")
            ctx.log(f"    台词: \"{vm.get('intro_text', '')}\"")

        # ── Step 2: MiniMax TTS 生成语音样本 ──
        async def _gen_voices():
            from app.ai.providers.minimax_tts import MiniMaxTTSProvider
            provider = MiniMaxTTSProvider()

            for c in ctx.characters:
                cid = c["char_id"]
                name = c["name"]
                vm = voice_map.get(cid, {})
                voice_id = vm.get("voice_id", "male-qn-qingse")
                intro_text = vm.get("intro_text", f"我是{name}。")
                emotion = vm.get("emotion", "calm")

                # ── 主音色样本 ──
                asset_key = f"char_voice:{cid}"
                if not ctx.candidates.is_invalidated(asset_key):
                    sel = ctx.candidates.get_selected_path(asset_key)
                    if sel and os.path.exists(sel) and os.path.getsize(sel) > 100:
                        ctx.log(f"  {name} ({cid}) 主音色: ★ 已存在")
                        # 继续检查回忆版
                    else:
                        sel = None
                else:
                    ctx.candidates.clear_invalidation(asset_key)
                    sel = None

                if not sel:
                    job_id = await provider.submit_job({
                        "text": intro_text,
                        "voice_id": voice_id,
                        "speed": 0.9,
                        "emotion": emotion,
                    })
                    status = await provider.poll_job(job_id)
                    if status.result_data:
                        ver = ctx.candidates.next_version(asset_key)
                        path = f"{ctx.output_dir}/characters/voice_{cid}_v{ver}.mp3"
                        with open(path, "wb") as f:
                            f.write(status.result_data)
                        rel = os.path.relpath(path, ctx.output_dir)
                        ctx.candidates.register(asset_key, rel)
                        ctx.log(f"  {name} ({cid}) 主音色: ✓ voice={voice_id} (v{ver})")
                    else:
                        ctx.log(f"  {name} ({cid}) 主音色: ✗ {status.error}")
                    await asyncio.sleep(1)

                # ── 回忆版（加混响） ──
                asset_key_mem = f"char_voice_memory:{cid}"
                if not ctx.candidates.is_invalidated(asset_key_mem):
                    sel_mem = ctx.candidates.get_selected_path(asset_key_mem)
                    if sel_mem and os.path.exists(sel_mem) and os.path.getsize(sel_mem) > 100:
                        ctx.log(f"  {name} ({cid}) 回忆版: ★ 已存在")
                        continue
                else:
                    ctx.candidates.clear_invalidation(asset_key_mem)

                # 找到主音色文件
                main_sel = ctx.candidates.get_selected_path(f"char_voice:{cid}")
                if not main_sel or not os.path.exists(main_sel):
                    ctx.log(f"  {name} ({cid}) 回忆版: ✗ 主音色不存在，跳过")
                    continue

                ver_mem = ctx.candidates.next_version(asset_key_mem)
                mem_path = f"{ctx.output_dir}/characters/voice_{cid}_memory_v{ver_mem}.mp3"

                # FFmpeg 加混响：aecho 滤镜模拟回忆感
                cmd = [
                    "ffmpeg", "-y", "-i", main_sel,
                    "-af", "aecho=0.8:0.7:40|60:0.3|0.2,highpass=f=80,lowpass=f=6000",
                    mem_path,
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=15)
                if result.returncode == 0 and os.path.exists(mem_path):
                    rel_mem = os.path.relpath(mem_path, ctx.output_dir)
                    ctx.candidates.register(asset_key_mem, rel_mem)
                    ctx.log(f"  {name} ({cid}) 回忆版: ✓ +混响 (v{ver_mem})")
                else:
                    ctx.log(f"  {name} ({cid}) 回忆版: ✗ FFmpeg 失败")

        asyncio.run(_gen_voices())

        # ── 保存元数据 ──
        meta_path = f"{ctx.output_dir}/characters/voice_library.json"
        library = {}
        for c in ctx.characters:
            cid = c["char_id"]
            vm = voice_map.get(cid, {})
            library[cid] = {
                "name": c["name"],
                "voice_id": vm.get("voice_id", ""),
                "emotion": vm.get("emotion", "calm"),
                "intro_text": vm.get("intro_text", ""),
                "main_audio": ctx.candidates.get_selected_path(f"char_voice:{cid}") or "",
                "memory_audio": ctx.candidates.get_selected_path(f"char_voice_memory:{cid}") or "",
            }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(library, f, ensure_ascii=False, indent=2)
        ctx.log(f"\n  音色库已保存: {meta_path}")

        return StageResult(success=True)

    # ================================================================
    # Stage 4: Scene Reference Images (场景参考图, Gemini + 角色参考)
    # ================================================================
    def stage_scene_refs(self, ctx: WorkflowContext) -> StageResult:
        os.makedirs(f"{ctx.output_dir}/scenes", exist_ok=True)

        # 构建角色名 → char_id 映射
        char_name_map = {}
        for c in ctx.characters:
            char_name_map[c["name"]] = c["char_id"]
            # 也处理括号别名，如 "陈锈 (孤星)"
            base_name = c["name"].split("(")[0].split("（")[0].strip()
            char_name_map[base_name] = c["char_id"]

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            title = unit.get("title", "")
            ctx.log(f"\n  ── 单元 {un}: {title} ──")

            for si, scene in enumerate(unit.get("key_scenes", [])):
                location = scene.get("location", "")
                description = scene.get("description", "")
                asset_key = f"scene_ref:u{un}_s{si+1}"

                # 断点恢复
                if not ctx.candidates.is_invalidated(asset_key):
                    sel = ctx.candidates.get_selected_path(asset_key)
                    if sel and os.path.exists(sel) and os.path.getsize(sel) > 100:
                        ctx.log(f"    场景{si+1} [{location}]: ★ 已存在")
                        continue
                ctx.candidates.clear_invalidation(asset_key)

                # 找出此场景涉及的角色参考图
                unit_chars = unit.get("characters", [])
                ref_images = []
                ref_labels = []
                for char_name in unit_chars:
                    cid = char_name_map.get(char_name)
                    if cid and cid in ctx.char_images:
                        ref_images.append(ctx.char_images[cid])
                        char_profile = next((c for c in ctx.characters if c["char_id"] == cid), {})
                        appearance = char_profile.get("appearance_prompt", "")[:80]
                        ref_labels.append(
                            f'Character reference for "{char_name}": {appearance}'
                        )

                # Gemini prompt
                prompt = (
                    f"Generate an anime scene image. "
                    f"Location: {location}. "
                    f"Scene description: {description}. "
                    f"Use the character reference images to maintain character consistency. "
                    f"Anime style, manga aesthetic, dramatic lighting, high quality, 16:9 aspect ratio. "
                    f"No text, no watermark."
                )

                version = ctx.candidates.next_version(asset_key)
                out_path = f"{ctx.output_dir}/scenes/scene_u{un}_s{si+1}_v{version}.png"

                result = generate_image_with_refs(
                    prompt=prompt,
                    ref_images=ref_images if ref_images else None,
                    ref_labels=ref_labels if ref_labels else None,
                    output_path=out_path,
                )

                if result:
                    rel = os.path.relpath(result, ctx.output_dir)
                    ctx.candidates.register(asset_key, rel)
                    ctx.log(f"    场景{si+1} [{location}]: ✓ (v{version}, {len(ref_images)}角色参考)")
                else:
                    ctx.log(f"    场景{si+1} [{location}]: ✗ 生成失败")

                time.sleep(2)

        return StageResult(success=True)

    # ================================================================
    # Stage 5: Storyboard Grids (4x4 宫格分镜图)
    # ================================================================
    def stage_storyboard_grids(self, ctx: WorkflowContext) -> StageResult:
        os.makedirs(f"{ctx.output_dir}/grids", exist_ok=True)

        # 构建角色名 → char_id 映射
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

            # 断点恢复
            if not ctx.candidates.is_invalidated(asset_key):
                sel = ctx.candidates.get_selected_path(asset_key)
                if sel and os.path.exists(sel) and os.path.getsize(sel) > 100:
                    ctx.log(f"  单元 {un} [{title}]: ★ 已存在")
                    continue
            ctx.candidates.clear_invalidation(asset_key)

            ctx.log(f"\n  ── 单元 {un}: {title} ──")

            # Step A: LLM 生成 16 个分镜 prompt
            grid_json_path = f"{ctx.output_dir}/grids/grid_u{un}_shots.json"
            if os.path.exists(grid_json_path) and os.path.getsize(grid_json_path) > 100:
                ctx.log(f"    LLM shots: ★ 已存在")
                with open(grid_json_path) as f:
                    grid_data = json.load(f)
            else:
                ctx.log(f"    LLM 生成 16 个分镜 prompt...")
                grid_data = _validated_chat_json(
                    system_prompt=GRID_SHOTS_SYSTEM_PROMPT,
                    user_prompt=GRID_SHOTS_USER_PROMPT.format(
                        title=title,
                        emotion_tone=unit.get("emotion_tone", ""),
                        core_conflict=unit.get("core_conflict", ""),
                        script_json=json.dumps(unit.get("script", []), ensure_ascii=False, indent=2),
                        characters_json=json.dumps(chars_appearance, ensure_ascii=False, indent=2),
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
                    char_profile = next((c for c in ctx.characters if c["char_id"] == cid), {})
                    appearance = char_profile.get("appearance_prompt", "")[:80]
                    ref_labels.append(
                        f'Character "{char_name}": {appearance}'
                    )

            # 也加入已生成的场景参考图
            for si in range(len(unit.get("key_scenes", []))):
                scene_sel = ctx.candidates.get_selected_path(f"scene_ref:u{un}_s{si+1}")
                if scene_sel and os.path.exists(scene_sel):
                    ref_images.append(scene_sel)
                    loc = unit["key_scenes"][si].get("location", "")
                    ref_labels.append(f'Scene reference: {loc}')

            # Step C: 组装 Gemini prompt
            char_ref_labels = "\n".join(
                [f"- Image {i+1}: {lbl}" for i, lbl in enumerate(ref_labels)]
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
            ctx.log(f"    Gemini 生成 4x4 宫格图 ({len(ref_images)} 参考图)...")
            version = ctx.candidates.next_version(asset_key)
            out_path = f"{ctx.output_dir}/grids/grid_u{un}_v{version}.png"

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
                ctx.log(f"    ✗ 宫格图生成失败")

            time.sleep(3)

        return StageResult(success=True)

    # ================================================================
    # Stage 6: Video Prompts (4K切图 + 分镜视频指令)
    # ================================================================
    def stage_video_prompts(self, ctx: WorkflowContext) -> StageResult:
        from PIL import Image

        os.makedirs(f"{ctx.output_dir}/frames", exist_ok=True)

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            title = unit.get("title", "")
            ctx.log(f"\n  ── 单元 {un}: {title} ──")

            # ── Step A: 从 4K 宫格图切出 16 帧 ──
            grid_sel = ctx.candidates.get_selected_path(f"grid:u{un}")
            if not grid_sel or not os.path.exists(grid_sel):
                ctx.log(f"    ✗ 宫格图不存在，跳过")
                continue

            frames_dir = f"{ctx.output_dir}/frames/u{un}"
            os.makedirs(frames_dir, exist_ok=True)

            existing_frames = [f for f in os.listdir(frames_dir)
                               if f.startswith("frame_") and f.endswith(".png")]
            if len(existing_frames) >= 16:
                ctx.log(f"    切图: ★ 已存在 ({len(existing_frames)} 帧)")
            else:
                grid_img = Image.open(grid_sel)
                cell_w = grid_img.width // 4
                cell_h = grid_img.height // 4
                ctx.log(f"    切图: {grid_img.width}x{grid_img.height} → 每格 {cell_w}x{cell_h}")

                for row in range(4):
                    for col in range(4):
                        idx = row * 4 + col + 1
                        frame_path = f"{frames_dir}/frame_{idx:02d}.png"
                        if os.path.exists(frame_path) and os.path.getsize(frame_path) > 500:
                            continue
                        cell = grid_img.crop((
                            col * cell_w, row * cell_h,
                            (col + 1) * cell_w, (row + 1) * cell_h,
                        ))
                        cell.save(frame_path)

                ctx.log(f"    ✓ 16 帧已切出 ({cell_w}x{cell_h})")

            # 注册每帧到 CandidateManager
            for fidx in range(1, 17):
                frame_path = f"{frames_dir}/frame_{fidx:02d}.png"
                if os.path.exists(frame_path):
                    fkey = f"frame:u{un}_f{fidx:02d}"
                    if not ctx.candidates.list_candidates(fkey):
                        rel = os.path.relpath(frame_path, ctx.output_dir)
                        ctx.candidates.register(fkey, rel)

            # ── Step B: LLM 生成 15 段分镜视频指令 ──
            vp_path = f"{ctx.output_dir}/grids/video_segments_u{un}.json"

            if os.path.exists(vp_path) and os.path.getsize(vp_path) > 100:
                ctx.log(f"    分镜指令: ★ 已存在")
                with open(vp_path) as f:
                    vp_data = json.load(f)
            else:
                # 加载 shots 描述
                shots_path = f"{ctx.output_dir}/grids/grid_u{un}_shots.json"
                if os.path.exists(shots_path):
                    with open(shots_path) as f:
                        shots_data = json.load(f)
                    shots = shots_data.get("shots", [])
                else:
                    shots = []

                # 构建可用场景 ref 列表
                scene_refs_list = []
                for si, sc in enumerate(unit.get("key_scenes", [])):
                    ref_id = f"u{un}_s{si+1}"
                    scene_refs_list.append({
                        "ref_id": ref_id,
                        "location": sc.get("location", ""),
                        "description": sc.get("description", ""),
                    })

                chars_for_llm = [
                    {"char_id": c["char_id"], "name": c["name"], "gender": c.get("gender", "")}
                    for c in ctx.characters
                ]

                ctx.log(f"    LLM 生成 15 段分镜视频指令...")
                vp_data = _validated_chat_json(
                    system_prompt=VIDEO_SEGMENTS_SYSTEM_PROMPT,
                    user_prompt=VIDEO_SEGMENTS_USER_PROMPT.format(
                        unit_number=un,
                        title=title,
                        emotion_tone=unit.get("emotion_tone", ""),
                        core_conflict=unit.get("core_conflict", ""),
                        script_json=json.dumps(unit.get("script", []), ensure_ascii=False, indent=2),
                        characters_json=json.dumps(chars_for_llm, ensure_ascii=False, indent=2),
                        scene_refs_json=json.dumps(scene_refs_list, ensure_ascii=False, indent=2),
                        shots_json=json.dumps(shots, ensure_ascii=False, indent=2),
                    ),
                    required_keys=["video_segments"],
                    list_key="video_segments",
                    list_length=15,
                    temperature=0.4,
                    max_tokens=8192,
                )

                with open(vp_path, "w", encoding="utf-8") as f:
                    json.dump(vp_data, f, ensure_ascii=False, indent=2)

            # ── 打印摘要 ──
            segments = vp_data.get("video_segments", [])
            total_dur = sum(s.get("estimated_duration", 0) for s in segments)
            dialogue_count = sum(1 for s in segments if s.get("is_dialogue"))
            scene_change_count = sum(1 for s in segments
                                     if not s.get("same_scene_as_prev", True))

            ctx.log(f"    {len(segments)} 段, 预估总时长 {total_dur}s, "
                    f"{dialogue_count} 段含台词, {scene_change_count} 次场景跳变")

            for s in segments[:5]:
                sn = s.get("segment_number", "?")
                cam = s.get("camera_type", "")
                mov = s.get("camera_movement", "")
                dur = s.get("estimated_duration", 0)
                emo = s.get("emotion", "")
                dlg_str = ""
                if s.get("is_dialogue") and s.get("dialogue"):
                    d = s["dialogue"]
                    facing = d.get("facing", "")
                    dlg_str = (f'\n      💬 {d.get("character","")}'
                               f'({facing}): "{d.get("content","")[:25]}..."')
                same = "→" if s.get("same_scene_as_prev") else "⟳"
                ctx.log(f"    {same} 段{sn}: [{cam}/{mov}] {dur}s {emo}{dlg_str}")
            if len(segments) > 5:
                ctx.log(f"    ... (还有 {len(segments)-5} 段)")

        return StageResult(success=True)

    # ================================================================
    # Stage 7: Dialogue TTS (台词语音 + 时长校准)
    # ================================================================
    def stage_dialogue_tts(self, ctx: WorkflowContext) -> StageResult:
        import re
        import math
        from app.services.ffmpeg_utils import get_media_duration

        os.makedirs(f"{ctx.output_dir}/audio", exist_ok=True)

        # 加载音色映射
        voice_map_path = f"{ctx.output_dir}/voice_map.json"
        with open(voice_map_path) as f:
            voice_map = json.load(f)

        async def _gen_all_tts():
            from app.ai.providers.minimax_tts import MiniMaxTTSProvider
            provider = MiniMaxTTSProvider()

            for ui, unit in enumerate(ctx.segments):
                un = unit.get("unit_number", ui + 1)
                vp_path = f"{ctx.output_dir}/grids/video_segments_u{un}.json"
                if not os.path.exists(vp_path):
                    continue

                with open(vp_path) as f:
                    vp_data = json.load(f)
                segments = vp_data.get("video_segments", [])

                ctx.log(f"\n  ── 单元 {un}: TTS ──")
                updated = False

                for seg in segments:
                    sn = seg["segment_number"]

                    # 非台词段：只确保 final_duration >= 3
                    if not seg.get("is_dialogue"):
                        seg["final_duration"] = max(seg.get("estimated_duration", 3), 3)
                        continue

                    # 已有 TTS 且有 final_duration → 跳过
                    if seg.get("tts_path") and seg.get("final_duration"):
                        tts_p = seg["tts_path"]
                        if os.path.exists(tts_p) and os.path.getsize(tts_p) > 100:
                            ctx.log(f"    段{sn}: ★ 已存在")
                            continue

                    d = seg["dialogue"]
                    char_id = d.get("char_id", "")
                    content = d.get("content", "")
                    is_memory = seg.get("is_memory", False)

                    # 去括号注释
                    clean_text = re.sub(r'（[^）]*）', '', content)
                    clean_text = re.sub(r'\([^)]*\)', '', clean_text).strip()
                    if not clean_text:
                        seg["final_duration"] = max(seg.get("estimated_duration", 3), 3)
                        continue

                    # 选择音色：回忆场景用回忆版的音色参数（实际音频后处理加混响）
                    vm = voice_map.get(char_id, {})
                    voice_id = vm.get("voice_id", "male-qn-qingse")
                    emotion = vm.get("emotion", "calm")

                    # 生成 TTS
                    job_id = await provider.submit_job({
                        "text": clean_text,
                        "voice_id": voice_id,
                        "speed": 0.9,
                        "emotion": emotion,
                    })
                    status = await provider.poll_job(job_id)

                    if status.result_data:
                        audio_path = f"{ctx.output_dir}/audio/u{un}_seg{sn:02d}_dialogue.mp3"
                        with open(audio_path, "wb") as f:
                            f.write(status.result_data)

                        # 回忆场景：加混响
                        if is_memory:
                            mem_path = f"{ctx.output_dir}/audio/u{un}_seg{sn:02d}_dialogue_memory.mp3"
                            subprocess.run([
                                "ffmpeg", "-y", "-i", audio_path,
                                "-af", "aecho=0.8:0.7:40|60:0.3|0.2,highpass=f=80,lowpass=f=6000",
                                mem_path,
                            ], capture_output=True, timeout=15)
                            if os.path.exists(mem_path):
                                audio_path = mem_path

                        tts_dur = get_media_duration(audio_path)
                        final_dur = max(seg.get("estimated_duration", 3), math.ceil(tts_dur), 3)

                        seg["tts_path"] = os.path.abspath(audio_path)
                        seg["tts_duration"] = tts_dur
                        seg["final_duration"] = final_dur
                        updated = True

                        # 注册到 CandidateManager
                        tts_asset_key = f"dialogue_tts:u{un}_seg{sn:02d}"
                        rel = os.path.relpath(audio_path, ctx.output_dir)
                        if not ctx.candidates.list_candidates(tts_asset_key):
                            ctx.candidates.register(tts_asset_key, rel)

                        mem_tag = " [回忆版]" if is_memory else ""
                        ctx.log(f"    段{sn}: ✓ {d['character']} TTS={tts_dur:.1f}s → final={final_dur}s{mem_tag}")
                    else:
                        seg["final_duration"] = max(seg.get("estimated_duration", 3), 3)
                        ctx.log(f"    段{sn}: ✗ TTS 失败")

                    await asyncio.sleep(0.5)

                # 回写
                if updated:
                    with open(vp_path, "w", encoding="utf-8") as f:
                        json.dump(vp_data, f, ensure_ascii=False, indent=2)

                total_dur = sum(s.get("final_duration", 0) for s in segments)
                ctx.log(f"    总时长: {total_dur}s")

        asyncio.run(_gen_all_tts())
        return StageResult(success=True)

    # ================================================================
    # Stage 8: Video Generation (Kling V3 + lip-sync)
    # ================================================================
    def stage_video_gen(self, ctx: WorkflowContext) -> StageResult:
        import base64
        import requests as http_requests
        from vendor.kling.client import KlingClient
        from app.services.ffmpeg_utils import get_media_duration

        client = KlingClient()
        os.makedirs(f"{ctx.output_dir}/videos", exist_ok=True)

        def _download(url, path, retries=3):
            for attempt in range(retries):
                try:
                    r = http_requests.get(url, timeout=180)
                    with open(path, "wb") as f:
                        f.write(r.content)
                    if os.path.getsize(path) > 1000:
                        return True
                except Exception as e:
                    print(f"  下载重试 {attempt+1}/{retries}: {type(e).__name__}")
                    time.sleep(5)
            return False

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            vp_path = f"{ctx.output_dir}/grids/video_segments_u{un}.json"
            if not os.path.exists(vp_path):
                continue

            with open(vp_path) as f:
                vp_data = json.load(f)
            segments = vp_data.get("video_segments", [])

            ctx.log(f"\n  ── 单元 {un}: 视频生成 ({len(segments)} 段) ──")

            for seg in segments:
                sn = seg["segment_number"]
                final_path = f"{ctx.output_dir}/videos/u{un}_seg{sn:02d}_final.mp4"

                # 断点恢复: 优先检查 CandidateManager
                video_asset_key = f"video:u{un}_seg{sn:02d}"
                sel_video = ctx.candidates.get_selected_path(video_asset_key)
                if sel_video and os.path.exists(sel_video) and os.path.getsize(sel_video) > 1000:
                    ctx.log(f"    段{sn}: ★ 已存在 (candidates)")
                    continue
                if os.path.exists(final_path) and os.path.getsize(final_path) > 1000:
                    # 迁移旧文件到 CandidateManager
                    rel = os.path.relpath(final_path, ctx.output_dir)
                    ctx.candidates.register(video_asset_key, rel)
                    ctx.log(f"    段{sn}: ★ 已存在")
                    continue

                frames_dir = f"{ctx.output_dir}/frames/u{un}"
                frame_start = f"{frames_dir}/frame_{seg['start_frame']:02d}.png"

                # 角色参考图
                char_refs = []
                for cid in seg.get("characters_in_frame", []):
                    if cid in ctx.char_images:
                        char_refs.append({"image": client.encode_image(ctx.char_images[cid])})

                # 构建 image2video 参数
                duration = str(max(seg.get("final_duration", 3), 3))
                i2v_params = {
                    "model_name": "kling-v3",
                    "image": client.encode_image(frame_start),  # 始终用首帧
                    "prompt": seg.get("video_prompt", ""),
                    "mode": "std",
                    "duration": duration,
                    "aspect_ratio": "16:9",
                }
                # 角色参考
                if char_refs:
                    i2v_params["subject_reference"] = char_refs[:1]  # Kling 限制

                # 提交 image2video (重试3次)
                task_id = None
                for attempt in range(3):
                    try:
                        result = client._post("/v1/videos/image2video", i2v_params)
                        if result.get("code") == 0:
                            task_id = result["data"]["task_id"]
                            break
                        ctx.log(f"    段{sn}: image2video 重试 {attempt+1} code={result.get('code')}")
                    except Exception as e:
                        ctx.log(f"    段{sn}: image2video 重试 {attempt+1} {type(e).__name__}")
                    time.sleep(10)

                if not task_id:
                    ctx.log(f"    段{sn}: ✗ image2video 提交失败")
                    continue

                # 轮询
                data = client.poll_task(task_id, task_type="video", max_wait=600, interval=10)
                if not data:
                    ctx.log(f"    段{sn}: ✗ image2video 超时")
                    continue

                video_info = data["task_result"]["videos"][0]
                video_id = video_info.get("id", "")

                # 决定是否需要 lip-sync
                is_dialogue = seg.get("is_dialogue", False)
                is_memory = seg.get("is_memory", False)
                facing = seg.get("dialogue", {}).get("facing", "") if is_dialogue else ""
                need_lipsync = is_dialogue and not is_memory and "背" not in facing

                if need_lipsync and seg.get("tts_path"):
                    # lip-sync: audio2video
                    tts_path = seg["tts_path"]
                    if os.path.exists(tts_path):
                        with open(tts_path, "rb") as f:
                            audio_b64 = base64.b64encode(f.read()).decode()

                        token = client._get_token()
                        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                        lip_task_id = None

                        for attempt in range(3):
                            try:
                                lip_r = http_requests.post(
                                    "https://openapi.klingai.com/v1/videos/lip-sync",
                                    headers=headers,
                                    json={"input": {
                                        "video_id": video_id,
                                        "mode": "audio2video",
                                        "audio_type": "file",
                                        "audio_file": audio_b64,
                                    }},
                                    timeout=30,
                                ).json()
                                if lip_r.get("code") == 0:
                                    lip_task_id = lip_r["data"]["task_id"]
                                    break
                            except Exception as e:
                                ctx.log(f"    段{sn}: lip-sync 重试 {attempt+1}")
                            time.sleep(5)

                        if lip_task_id:
                            # 轮询 lip-sync
                            for i in range(60):
                                time.sleep(10)
                                try:
                                    lr = http_requests.get(
                                        f"https://openapi.klingai.com/v1/videos/lip-sync/{lip_task_id}",
                                        headers={"Authorization": f"Bearer {client._get_token()}"},
                                        timeout=30,
                                    ).json()
                                    status = lr.get("data", {}).get("task_status", "")
                                    if status == "succeed":
                                        lip_url = lr["data"]["task_result"]["videos"][0]["url"]
                                        _download(lip_url, final_path)
                                        ctx.log(f"    段{sn}: ✓ lip-sync ({duration}s)")
                                        break
                                    elif status == "failed":
                                        ctx.log(f"    段{sn}: ✗ lip-sync 失败, 用原视频")
                                        _download(video_info["url"], final_path)
                                        break
                                except Exception:
                                    pass
                            else:
                                _download(video_info["url"], final_path)
                        else:
                            _download(video_info["url"], final_path)
                            ctx.log(f"    段{sn}: ✗ lip-sync 提交失败, 用原视频")
                    else:
                        _download(video_info["url"], final_path)
                else:
                    # 非 lip-sync：直接下载
                    _download(video_info["url"], final_path)
                    tag = ""
                    if is_dialogue and is_memory:
                        tag = " [回忆台词,无lip-sync]"
                    elif is_dialogue and "背" in facing:
                        tag = " [背对,无lip-sync]"
                    ctx.log(f"    段{sn}: ✓ ({duration}s){tag}")

                # 注册视频到 CandidateManager
                if os.path.exists(final_path) and os.path.getsize(final_path) > 1000:
                    rel = os.path.relpath(final_path, ctx.output_dir)
                    if not ctx.candidates.list_candidates(video_asset_key):
                        ctx.candidates.register(video_asset_key, rel)
                    else:
                        # 已有候选但文件可能是新版本
                        ctx.candidates.register(video_asset_key, rel)

                time.sleep(2)

        return StageResult(success=True)

    # ================================================================
    # Stage 9: Subtitle Burn (字幕压制)
    # ================================================================
    def stage_subtitle_burn(self, ctx: WorkflowContext) -> StageResult:
        font_path = "/System/Library/AssetsV2/com_apple_MobileAsset_Font7/3419f2a427639ad8c8e139149a287865a90fa17e.asset/AssetData/PingFang.ttc"
        # fallback
        if not os.path.exists(font_path):
            font_path = "/System/Library/Fonts/STHeiti Medium.ttc"

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            vp_path = f"{ctx.output_dir}/grids/video_segments_u{un}.json"
            if not os.path.exists(vp_path):
                continue

            with open(vp_path) as f:
                segments = json.load(f).get("video_segments", [])

            ctx.log(f"\n  ── 单元 {un}: 字幕压制 ──")

            for seg in segments:
                sn = seg["segment_number"]
                if not seg.get("is_dialogue") or not seg.get("dialogue"):
                    continue

                video_in = f"{ctx.output_dir}/videos/u{un}_seg{sn:02d}_final.mp4"
                video_out = f"{ctx.output_dir}/videos/u{un}_seg{sn:02d}_subtitled.mp4"

                if os.path.exists(video_out) and os.path.getsize(video_out) > 1000:
                    ctx.log(f"    段{sn}: ★ 字幕已存在")
                    continue

                if not os.path.exists(video_in):
                    continue

                d = seg["dialogue"]
                char_name = d.get("character", "")
                content = d.get("content", "")
                # 去括号注释用于显示
                import re
                clean = re.sub(r'（[^）]*）', '', content)
                clean = re.sub(r'\([^)]*\)', '', clean).strip()

                safe_text = clean.replace("'", "'\\''").replace(":", "\\:")
                safe_name = char_name.replace("'", "'\\''")

                filter_str = (
                    f"drawtext=fontfile='{font_path}':fontsize=28:fontcolor=white:"
                    f"borderw=2:bordercolor=black:"
                    f"x=(w-text_w)/2:y=h-th-60:"
                    f"text='{safe_text}',"
                    f"drawtext=fontfile='{font_path}':fontsize=22:fontcolor=#FFD700:"
                    f"borderw=1.5:bordercolor=black:"
                    f"x=(w-text_w)/2:y=h-th-95:"
                    f"text='{safe_name}'"
                )

                cmd = ["ffmpeg", "-y", "-i", video_in, "-vf", filter_str,
                       "-c:a", "copy", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                       video_out]
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                if result.returncode == 0:
                    ctx.log(f"    段{sn}: ✓ {char_name}字幕")
                else:
                    ctx.log(f"    段{sn}: ✗ 字幕压制失败")

        return StageResult(success=True)

    # ================================================================
    # Stage 10: Assembly (统一帧率 + 拼接 + BGM)
    # ================================================================
    def stage_assembly(self, ctx: WorkflowContext) -> StageResult:
        from app.services.ffmpeg_utils import get_media_duration
        import requests as http_requests

        for ui, unit in enumerate(ctx.segments):
            un = unit.get("unit_number", ui + 1)
            vp_path = f"{ctx.output_dir}/grids/video_segments_u{un}.json"
            if not os.path.exists(vp_path):
                continue

            final_output = f"{ctx.output_dir}/videos/u{un}_output.mp4"
            if os.path.exists(final_output) and os.path.getsize(final_output) > 1000:
                ctx.log(f"\n  ── 单元 {un}: ★ 已存在 ──")
                continue

            with open(vp_path) as f:
                segments = json.load(f).get("video_segments", [])

            ctx.log(f"\n  ── 单元 {un}: 组装 ({len(segments)} 段) ──")

            # ── Step A: 收集各段视频（字幕版优先） ──
            clip_paths = []
            for seg in segments:
                sn = seg["segment_number"]
                subtitled = f"{ctx.output_dir}/videos/u{un}_seg{sn:02d}_subtitled.mp4"
                raw = f"{ctx.output_dir}/videos/u{un}_seg{sn:02d}_final.mp4"

                if os.path.exists(subtitled) and os.path.getsize(subtitled) > 1000:
                    clip_paths.append(subtitled)
                elif os.path.exists(raw) and os.path.getsize(raw) > 1000:
                    clip_paths.append(raw)
                else:
                    ctx.log(f"    段{sn}: ✗ 视频不存在，跳过")

            if not clip_paths:
                ctx.log(f"    无可用视频")
                continue

            # ── Step B: 统一 1280x720 @30fps ──
            ctx.log(f"    统一 1280x720 @30fps...")
            unified_clips = []
            for i, c in enumerate(clip_paths):
                unified = f"{ctx.output_dir}/videos/u{un}_unified_{i:02d}.mp4"

                # 检查是否有音频轨
                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_streams", c],
                    capture_output=True, text=True)
                has_audio = "codec_type=audio" in probe.stdout

                vf = "fps=30,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"

                if has_audio:
                    cmd = ["ffmpeg", "-y", "-i", c, "-vf", vf,
                           "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", unified]
                else:
                    cmd = ["ffmpeg", "-y", "-i", c,
                           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                           "-vf", vf,
                           "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                           "-c:a", "aac", "-b:a", "128k", "-shortest", unified]

                result = subprocess.run(cmd, capture_output=True, timeout=30)
                if result.returncode == 0:
                    unified_clips.append(unified)
                else:
                    ctx.log(f"    ✗ 统一失败: {os.path.basename(c)}")

            # ── Step C: 拼接 ──
            ctx.log(f"    拼接 {len(unified_clips)} 段...")
            concat_list = f"{ctx.output_dir}/videos/concat_u{un}.txt"
            with open(concat_list, "w") as f:
                for c in unified_clips:
                    f.write(f"file '{os.path.abspath(c)}'\n")

            concat_out = f"{ctx.output_dir}/videos/u{un}_concat.mp4"
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                   "-c", "copy", concat_out]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode != 0:
                ctx.log(f"    ✗ 拼接失败")
                continue

            video_dur = get_media_duration(concat_out)
            ctx.log(f"    拼接完成: {video_dur:.1f}s")

            # ── Step D: BGM 生成 + 叠加 ──
            bgm_path = f"{ctx.output_dir}/audio/u{un}_bgm.mp3"

            if not os.path.exists(bgm_path) or os.path.getsize(bgm_path) < 100:
                ctx.log(f"    生成 BGM...")
                # LLM 生成音乐 prompt
                from vendor.qwen.client import chat_with_system
                music_prompt = chat_with_system(
                    "你是影视配乐师。根据剧本信息生成一个 AI 音乐生成的英文 prompt，50-80词，只输出 prompt。",
                    f"标题：{unit.get('title','')}\n情感：{unit.get('emotion_tone','')}\n"
                    f"冲突：{unit.get('core_conflict','')}\n时长：{int(video_dur)}秒",
                    temperature=0.7, max_tokens=200,
                )

                # ElevenLabs 音乐生成
                try:
                    r = http_requests.post(
                        "https://api.elevenlabs.io/v1/music/generate",
                        headers={
                            "xi-api-key": "sk_d9b38f734ef736fff51faa39f7d1080009ebf1ed9c5263f9",
                            "Content-Type": "application/json",
                        },
                        json={"prompt": music_prompt, "duration_seconds": int(video_dur) + 2},
                        timeout=120,
                    )
                    if r.status_code == 200:
                        with open(bgm_path, "wb") as f:
                            f.write(r.content)
                        ctx.log(f"    BGM: ✓ ElevenLabs ({get_media_duration(bgm_path):.1f}s)")
                    else:
                        ctx.log(f"    BGM: ✗ ElevenLabs {r.status_code}")
                except Exception as e:
                    ctx.log(f"    BGM: ✗ {e}")

            if os.path.exists(bgm_path) and os.path.getsize(bgm_path) > 100:
                # 叠加 BGM (音量 0.15, 淡入2s, 淡出2s)
                fade_out_start = max(0, video_dur - 2)
                cmd = [
                    "ffmpeg", "-y",
                    "-i", concat_out, "-i", bgm_path,
                    "-filter_complex",
                    f"[1:a]volume=0.15,afade=t=in:d=2,afade=t=out:st={fade_out_start:.0f}:d=2[bgm];"
                    f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                    "-map", "0:v", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                    final_output,
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=60)
                if result.returncode == 0:
                    dur = get_media_duration(final_output)
                    size = os.path.getsize(final_output) // 1024
                    ctx.log(f"    ✓ 最终输出: u{un}_output.mp4 ({dur:.1f}s, {size}KB)")
                else:
                    # BGM 叠加失败，用无 BGM 版本
                    os.rename(concat_out, final_output)
                    ctx.log(f"    BGM 叠加失败，使用无 BGM 版本")
            else:
                os.rename(concat_out, final_output)
                ctx.log(f"    无 BGM，直接输出")

        return StageResult(success=True)

    # ================================================================
    # Reroll: 宫格帧抽卡
    # ================================================================
    # ================================================================
    # Review 操作（对话漫剧专用）
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
            dialogue_count = sum(1 for s in script if s.get("type") == "dialogue")
            units_summary.append({
                "unit_number": u.get("unit_number"),
                "title": u.get("title", ""),
                "core_conflict": u.get("core_conflict", ""),
                "emotion_tone": u.get("emotion_tone", ""),
                "characters": u.get("characters", []),
                "dialogue_count": dialogue_count,
                "script_length": len(script),
            })
        characters = []
        for cp in sb.get("character_profiles", []):
            characters.append({
                "char_id": cp.get("char_id"),
                "name": cp.get("name"),
                "gender": cp.get("gender"),
                "age": cp.get("age"),
                "voice_trait": cp.get("voice_trait", ""),
            })
        return {"units": units_summary, "characters": characters}

    def op_review_status(self, output_dir: str) -> dict:
        """返回整体进度状态"""
        stages_status = {}

        # storyboard
        sb_path = os.path.join(output_dir, "storyboard.json")
        sb_exists = os.path.exists(sb_path) and os.path.getsize(sb_path) > 100
        stages_status["storyboard"] = "completed" if sb_exists else "pending"

        # characters
        char_dir = os.path.join(output_dir, "characters")
        char_refs = [f for f in os.listdir(char_dir) if f.startswith("charref_") and f.endswith(".png")] if os.path.isdir(char_dir) else []
        stages_status["char_refs"] = "completed" if char_refs else "pending"

        # voice
        voice_map_path = os.path.join(output_dir, "voice_map.json")
        voice_lib_path = os.path.join(output_dir, "characters", "voice_library.json")
        stages_status["char_voices"] = "completed" if os.path.exists(voice_lib_path) else "pending"

        # scene_refs
        scene_dir = os.path.join(output_dir, "scenes")
        scene_files = [f for f in os.listdir(scene_dir) if f.endswith(".png")] if os.path.isdir(scene_dir) else []
        stages_status["scene_refs"] = "completed" if scene_files else "pending"

        # grids
        grids_dir = os.path.join(output_dir, "grids")
        grid_pngs = [f for f in os.listdir(grids_dir) if f.startswith("grid_u") and f.endswith(".png")] if os.path.isdir(grids_dir) else []
        stages_status["storyboard_grids"] = "completed" if grid_pngs else "pending"

        # video_prompts (video_segments json files)
        vp_files = [f for f in os.listdir(grids_dir) if f.startswith("video_segments_u") and f.endswith(".json")] if os.path.isdir(grids_dir) else []
        stages_status["video_prompts"] = "completed" if vp_files else "pending"

        # Count units from storyboard
        num_units = 0
        if sb_exists:
            try:
                with open(sb_path) as f:
                    sb = json.load(f)
                num_units = len(sb.get("units", []))
            except Exception:
                pass

        # dialogue_tts
        audio_dir = os.path.join(output_dir, "audio")
        tts_files = [f for f in os.listdir(audio_dir) if f.endswith(".mp3")] if os.path.isdir(audio_dir) else []
        stages_status["dialogue_tts"] = "completed" if tts_files else "pending"

        # video_gen
        video_dir = os.path.join(output_dir, "videos")
        video_files = [f for f in os.listdir(video_dir) if f.endswith(".mp4")] if os.path.isdir(video_dir) else []
        stages_status["video_gen"] = "completed" if video_files else "pending"

        # assembly — 实际输出是 videos/u{n}_output.mp4
        output_videos = [f for f in (os.listdir(video_dir) if os.path.isdir(video_dir) else [])
                         if f.endswith("_output.mp4")]
        stages_status["assembly"] = "completed" if output_videos else "pending"

        # Partial detection for grids/videos
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
                "output_videos": [os.path.join("videos", f) for f in output_videos],
            },
        }

    def op_review_characters(self, output_dir: str) -> dict:
        """返回角色资产（三视图路径 + 音色信息）"""
        # Voice library
        voice_lib_path = os.path.join(output_dir, "characters", "voice_library.json")
        voice_lib = {}
        if os.path.exists(voice_lib_path):
            with open(voice_lib_path) as f:
                voice_lib = json.load(f)

        # Voice map
        voice_map_path = os.path.join(output_dir, "voice_map.json")
        voice_map = {}
        if os.path.exists(voice_map_path):
            with open(voice_map_path) as f:
                voice_map = json.load(f)

        # Character profiles from storyboard
        sb_path = os.path.join(output_dir, "storyboard.json")
        char_profiles = {}
        if os.path.exists(sb_path):
            with open(sb_path) as f:
                sb = json.load(f)
            for cp in sb.get("character_profiles", []):
                char_profiles[cp.get("char_id")] = cp

        # Build result
        char_dir = os.path.join(output_dir, "characters")
        characters = []
        all_char_ids = set(list(voice_lib.keys()) + list(voice_map.keys()) + list(char_profiles.keys()))
        for cid in sorted(all_char_ids):
            profile = char_profiles.get(cid, {})
            vl = voice_lib.get(cid, {})
            vm = voice_map.get(cid, {})

            # Find ref images
            ref_images = []
            if os.path.isdir(char_dir):
                for f in sorted(os.listdir(char_dir)):
                    if f.startswith(f"charref_{cid}_") and f.endswith(".png"):
                        ref_images.append(os.path.relpath(os.path.join(char_dir, f), output_dir))

            # Voice samples (normalize to relative-to-output_dir)
            voice_samples = []
            for audio_key in ("main_audio", "memory_audio"):
                audio_val = vl.get(audio_key)
                if audio_val:
                    # Convert to relative-to-output_dir regardless of format
                    abs_path = os.path.abspath(audio_val) if not os.path.isabs(audio_val) else audio_val
                    voice_samples.append(os.path.relpath(abs_path, output_dir))

            characters.append({
                "char_id": cid,
                "name": profile.get("name") or vl.get("name", ""),
                "gender": profile.get("gender", ""),
                "age": profile.get("age", ""),
                "voice_id": vm.get("voice_id") or vl.get("voice_id", ""),
                "emotion": vm.get("emotion") or vl.get("emotion", ""),
                "ref_images": ref_images,
                "voice_samples": voice_samples,
            })

        return {"characters": characters}

    def op_review_unit(self, output_dir: str, unit_number: int) -> dict:
        """返回某个 unit 的详细信息"""
        vp_path = os.path.join(output_dir, "grids", f"video_segments_u{unit_number}.json")
        if not os.path.exists(vp_path):
            return {"error": f"video_segments_u{unit_number}.json not found"}
        with open(vp_path) as f:
            vp_data = json.load(f)

        segments = []
        for seg in vp_data.get("video_segments", []):
            sn = seg.get("segment_number")
            entry = {
                "segment_number": sn,
                "start_frame": seg.get("start_frame"),
                "end_frame": seg.get("end_frame"),
                "is_dialogue": seg.get("is_dialogue", False),
                "is_memory": seg.get("is_memory", False),
                "camera_type": seg.get("camera_type", ""),
                "camera_movement": seg.get("camera_movement", ""),
                "emotion": seg.get("emotion", ""),
                "scene_description": seg.get("scene_description", ""),
                "estimated_duration": seg.get("estimated_duration"),
                "final_duration": seg.get("final_duration"),
                "characters_in_frame": seg.get("characters_in_frame", []),
            }
            # Dialogue info
            if seg.get("dialogue"):
                d = seg["dialogue"]
                entry["dialogue"] = {
                    "char_id": d.get("char_id", ""),
                    "character": d.get("character", ""),
                    "content": d.get("content", ""),
                }
            # Frame path — 帧文件在 frames/u{unit}/frame_XX.png
            frame_dir = os.path.join(output_dir, "frames", f"u{unit_number}")
            frame_files = []
            if os.path.isdir(frame_dir):
                # start_frame 对应的帧文件
                sf = seg.get("start_frame")
                ef = seg.get("end_frame")
                for fidx in ([sf, ef] if sf and ef else []):
                    fp = os.path.join(frame_dir, f"frame_{fidx:02d}.png")
                    if os.path.exists(fp):
                        frame_files.append(os.path.relpath(fp, output_dir))
                    else:
                        # 也检查带版本号的文件
                        for fn in sorted(os.listdir(frame_dir)):
                            if fn.startswith(f"frame_{fidx:02d}") and fn.endswith(".png"):
                                frame_files.append(os.path.relpath(os.path.join(frame_dir, fn), output_dir))
                                break
            entry["frame_paths"] = frame_files

            # Video path
            video_dir = os.path.join(output_dir, "videos")
            video_pattern = f"u{unit_number}_seg{sn:02d}"
            video_files = []
            if os.path.isdir(video_dir):
                for vf in sorted(os.listdir(video_dir)):
                    if video_pattern in vf and vf.endswith(".mp4"):
                        video_files.append(os.path.relpath(os.path.join(video_dir, vf), output_dir))
            entry["video_paths"] = video_files

            # TTS path
            if seg.get("tts_path"):
                tts_abs = seg["tts_path"]
                entry["tts_path"] = os.path.relpath(tts_abs, output_dir) if os.path.isabs(tts_abs) else tts_abs

            segments.append(entry)

        # Also load grid info
        grid_path = os.path.join(output_dir, "grids", f"grid_u{unit_number}_shots.json")
        grid_info = None
        if os.path.exists(grid_path):
            with open(grid_path) as f:
                grid_info = json.load(f)

        return {
            "unit_number": unit_number,
            "segments": segments,
            "grid_shots": grid_info,
        }

    def op_review_assets(self, output_dir: str, asset_type: str) -> dict:
        """返回指定类型的资产列表"""
        result = {"type": asset_type, "assets": []}

        if asset_type == "scene_refs":
            scene_dir = os.path.join(output_dir, "scenes")
            if os.path.isdir(scene_dir):
                for f in sorted(os.listdir(scene_dir)):
                    if f.endswith(".png"):
                        result["assets"].append({
                            "path": os.path.relpath(os.path.join(scene_dir, f), output_dir),
                            "filename": f,
                        })

        elif asset_type == "grids":
            grids_dir = os.path.join(output_dir, "grids")
            if os.path.isdir(grids_dir):
                for f in sorted(os.listdir(grids_dir)):
                    if f.endswith(".png"):
                        result["assets"].append({
                            "path": os.path.relpath(os.path.join(grids_dir, f), output_dir),
                            "filename": f,
                        })

        elif asset_type == "frames":
            frame_dir = os.path.join(output_dir, "frames")
            if os.path.isdir(frame_dir):
                for f in sorted(os.listdir(frame_dir)):
                    if f.endswith(".png"):
                        result["assets"].append({
                            "path": os.path.relpath(os.path.join(frame_dir, f), output_dir),
                            "filename": f,
                        })

        elif asset_type == "videos":
            video_dir = os.path.join(output_dir, "videos")
            if os.path.isdir(video_dir):
                for f in sorted(os.listdir(video_dir)):
                    if f.endswith(".mp4"):
                        fpath = os.path.join(video_dir, f)
                        entry = {
                            "path": os.path.relpath(fpath, output_dir),
                            "filename": f,
                            "size_mb": round(os.path.getsize(fpath) / 1024 / 1024, 1),
                        }
                        result["assets"].append(entry)

        else:
            # Fallback: try CandidateManager
            from app.workflows.candidates import CandidateManager
            cm = CandidateManager(output_dir)
            cm.migrate_from_existing(output_dir)
            all_assets = cm.get_all_for_type(asset_type)
            for key, entry in all_assets.items():
                candidates = cm.list_candidates(key)
                result["assets"].append({"key": key, "candidates": candidates})

        return result

    # ================================================================
    # Reroll 操作（对话漫剧专用）
    # ================================================================

    def op_reroll_frame(self, output_dir: str, unit_number: int,
                        frame_number: int) -> dict:
        """抽卡单个宫格帧。如有未用备选则切换，否则重新生成整个宫格图并切帧。"""
        from PIL import Image
        from app.workflows.candidates import CandidateManager

        cm = CandidateManager(output_dir)
        cm.load()

        asset_key = f"frame:u{unit_number}_f{frame_number:02d}"

        # 1. 检查是否有未使用的备选版本
        candidates = cm.list_candidates(asset_key)
        if candidates:
            selected = [c for c in candidates if c["is_selected"]]
            unselected = [c for c in candidates if not c["is_selected"] and c["exists"]]
            if unselected:
                # FIFO: 选最早的未使用版本
                target = unselected[0]
                cm.select(asset_key, target["version"])
                print(f"  [reroll_frame] 切换到备选版本 v{target['version']}")
                return {
                    "success": True,
                    "message": f"切换到备选版本 v{target['version']}",
                    "path": target["abs_path"],
                    "candidates": cm.list_candidates(asset_key),
                }

        # 2. 检查版本数限制
        if len(candidates) >= 3:
            return {
                "success": False,
                "message": f"帧 u{unit_number}_f{frame_number:02d} 已达最大抽卡次数 (3)",
            }

        # 3. 重新生成整个 4x4 宫格图
        print(f"  [reroll_frame] 重新生成单元 {unit_number} 的 4x4 宫格图...")

        # 加载 storyboard
        sb_path = os.path.join(output_dir, "storyboard.json")
        if not os.path.exists(sb_path):
            return {"success": False, "message": "storyboard.json 不存在"}
        with open(sb_path) as f:
            sb = json.load(f)

        # 找到目标单元
        unit = None
        for u in sb.get("units", []):
            if u.get("unit_number") == unit_number:
                unit = u
                break
        if not unit:
            return {"success": False, "message": f"单元 {unit_number} 不存在"}

        characters = sb.get("character_profiles", [])
        char_name_map = {}
        for c in characters:
            char_name_map[c["name"]] = c["char_id"]
            base_name = c["name"].split("(")[0].split("（")[0].strip()
            char_name_map[base_name] = c["char_id"]

        chars_appearance = [
            {"name": c["name"], "appearance": c.get("appearance_prompt", "")}
            for c in characters
        ]

        # 加载 shots prompt
        shots_path = os.path.join(output_dir, "grids", f"grid_u{unit_number}_shots.json")
        if not os.path.exists(shots_path):
            return {"success": False, "message": "shots.json 不存在，请先运行 storyboard_grids"}
        with open(shots_path) as f:
            grid_data = json.load(f)
        shots = grid_data.get("shots", [])
        style_tags = grid_data.get("style_tags", [])
        if isinstance(style_tags, list):
            style_tags = ", ".join(style_tags)

        # 收集角色参考图
        unit_chars = unit.get("characters", [])
        ref_images = []
        ref_labels = []
        for char_name in unit_chars:
            cid = char_name_map.get(char_name)
            if cid:
                char_ref_sel = cm.get_selected_path(f"char_ref:{cid}")
                if char_ref_sel and os.path.exists(char_ref_sel):
                    ref_images.append(char_ref_sel)
                    char_profile = next((c for c in characters if c["char_id"] == cid), {})
                    appearance = char_profile.get("appearance_prompt", "")[:80]
                    ref_labels.append(f'Character "{char_name}": {appearance}')

        # 加入场景参考图
        for si in range(len(unit.get("key_scenes", []))):
            scene_sel = cm.get_selected_path(f"scene_ref:u{unit_number}_s{si+1}")
            if scene_sel and os.path.exists(scene_sel):
                ref_images.append(scene_sel)
                loc = unit["key_scenes"][si].get("location", "")
                ref_labels.append(f'Scene reference: {loc}')

        # 组装 Gemini prompt
        char_ref_labels = "\n".join(
            [f"- Image {i+1}: {lbl}" for i, lbl in enumerate(ref_labels)]
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

        # 生成宫格图
        grid_asset_key = f"grid:u{unit_number}"
        grid_version = cm.next_version(grid_asset_key)
        os.makedirs(os.path.join(output_dir, "grids"), exist_ok=True)
        out_path = os.path.join(output_dir, "grids", f"grid_u{unit_number}_v{grid_version}.png")

        try:
            result = generate_image_with_refs(
                prompt=gemini_prompt,
                ref_images=ref_images if ref_images else None,
                ref_labels=ref_labels if ref_labels else None,
                output_path=out_path,
                image_size="4K",
            )
        except Exception as e:
            return {"success": False, "message": f"宫格图生成失败: {e}"}

        if not result:
            return {"success": False, "message": "宫格图生成失败"}

        # 注册新宫格图
        rel_grid = os.path.relpath(result, output_dir)
        cm.register(grid_asset_key, rel_grid)
        print(f"  [reroll_frame] 新宫格图 v{grid_version}")

        # 切出 16 帧
        grid_img = Image.open(result)
        cell_w = grid_img.width // 4
        cell_h = grid_img.height // 4
        frames_dir = os.path.join(output_dir, "frames", f"u{unit_number}")
        os.makedirs(frames_dir, exist_ok=True)

        target_path = None
        for row in range(4):
            for col in range(4):
                idx = row * 4 + col + 1
                fkey = f"frame:u{unit_number}_f{idx:02d}"
                fversion = cm.next_version(fkey)
                frame_path = os.path.join(frames_dir, f"frame_{idx:02d}_v{fversion}.png")
                cell = grid_img.crop((
                    col * cell_w, row * cell_h,
                    (col + 1) * cell_w, (row + 1) * cell_h,
                ))
                cell.save(frame_path)
                rel = os.path.relpath(frame_path, output_dir)

                if idx == frame_number:
                    # 目标帧: 注册并设为选中（register 自动选中）
                    cm.register(fkey, rel)
                    target_path = frame_path
                else:
                    # 其他帧: 注册为备选，不改变选中状态
                    old_selected = None
                    existing = cm.list_candidates(fkey)
                    for c in existing:
                        if c["is_selected"]:
                            old_selected = c["version"]
                            break
                    cm.register(fkey, rel)
                    if old_selected is not None:
                        cm.select(fkey, old_selected)

        print(f"  [reroll_frame] 16 帧已切出，目标帧 f{frame_number:02d} 已更新")
        return {
            "success": True,
            "message": f"重新生成宫格图 v{grid_version}，帧 f{frame_number:02d} 已更新",
            "path": target_path,
            "candidates": cm.list_candidates(asset_key),
        }

    # ================================================================
    # Reroll: video_gen 按段抽卡
    # ================================================================
    def op_reroll_video_segment(self, output_dir: str, unit_number: int,
                                segment_number: int) -> dict:
        """重新生成单个视频段。"""
        import base64
        import requests as http_requests
        from app.workflows.candidates import CandidateManager
        from vendor.kling.client import KlingClient
        from app.services.ffmpeg_utils import get_media_duration

        cm = CandidateManager(output_dir)
        cm.load()
        client = KlingClient()

        # 加载 video_segments
        vp_path = os.path.join(output_dir, "grids", f"video_segments_u{unit_number}.json")
        if not os.path.exists(vp_path):
            return {"success": False, "message": f"video_segments_u{unit_number}.json 不存在"}
        with open(vp_path) as f:
            vp_data = json.load(f)

        segments = vp_data.get("video_segments", [])
        seg = None
        for s in segments:
            if s["segment_number"] == segment_number:
                seg = s
                break
        if not seg:
            return {"success": False, "message": f"段 {segment_number} 不存在"}

        # 加载角色参考图
        sb_path = os.path.join(output_dir, "storyboard.json")
        if os.path.exists(sb_path):
            with open(sb_path) as f:
                sb = json.load(f)
            characters = sb.get("character_profiles", [])
        else:
            characters = []

        # 构建 char_images 映射
        char_images = {}
        for c in characters:
            cid = c["char_id"]
            sel = cm.get_selected_path(f"char_ref:{cid}")
            if sel and os.path.exists(sel):
                char_images[cid] = sel

        # 首尾帧
        frames_dir = os.path.join(output_dir, "frames", f"u{unit_number}")
        frame_start_path = os.path.join(frames_dir, f"frame_{seg['start_frame']:02d}.png")
        # 也尝试从 CandidateManager 获取选中的帧
        fkey_start = f"frame:u{unit_number}_f{seg['start_frame']:02d}"
        sel_start = cm.get_selected_path(fkey_start)
        if sel_start and os.path.exists(sel_start):
            frame_start_path = sel_start

        if not os.path.exists(frame_start_path):
            return {"success": False, "message": f"首帧不存在: {frame_start_path}"}

        # 角色参考
        char_refs = []
        for cid in seg.get("characters_in_frame", []):
            if cid in char_images:
                char_refs.append({"image": client.encode_image(char_images[cid])})

        # 构建 image2video 参数
        duration = str(max(seg.get("final_duration", seg.get("estimated_duration", 3)), 3))
        i2v_params = {
            "model_name": "kling-v3",
            "image": client.encode_image(frame_start_path),  # 始终用首帧
            "prompt": seg.get("video_prompt", ""),
            "mode": "std",
            "duration": duration,
            "aspect_ratio": "16:9",
        }
        if char_refs:
            i2v_params["subject_reference"] = char_refs[:1]

        # 提交 image2video
        task_id = None
        try:
            for attempt in range(3):
                result = client._post("/v1/videos/image2video", i2v_params)
                if result.get("code") == 0:
                    task_id = result["data"]["task_id"]
                    break
                print(f"  [reroll_video] 段{segment_number}: 重试 {attempt+1}")
                time.sleep(10)
        except Exception as e:
            return {"success": False, "message": f"image2video 提交失败: {e}"}

        if not task_id:
            return {"success": False, "message": "image2video 提交失败"}

        # 轮询
        data = client.poll_task(task_id, task_type="video", max_wait=600, interval=10)
        if not data:
            return {"success": False, "message": "image2video 超时"}

        video_info = data["task_result"]["videos"][0]
        video_id = video_info.get("id", "")

        video_asset_key = f"video:u{unit_number}_seg{segment_number:02d}"
        version = cm.next_version(video_asset_key)
        os.makedirs(os.path.join(output_dir, "videos"), exist_ok=True)
        final_path = os.path.join(output_dir, "videos",
                                  f"u{unit_number}_seg{segment_number:02d}_v{version}.mp4")

        def _download(url, path, retries=3):
            for attempt in range(retries):
                try:
                    r = http_requests.get(url, timeout=180)
                    with open(path, "wb") as fw:
                        fw.write(r.content)
                    if os.path.getsize(path) > 1000:
                        return True
                except Exception as e:
                    print(f"  下载重试 {attempt+1}/{retries}: {type(e).__name__}")
                    time.sleep(5)
            return False

        # 决定是否需要 lip-sync
        is_dialogue = seg.get("is_dialogue", False)
        is_memory = seg.get("is_memory", False)
        facing = seg.get("dialogue", {}).get("facing", "") if is_dialogue else ""
        need_lipsync = is_dialogue and not is_memory and "背" not in facing

        if need_lipsync and seg.get("tts_path"):
            tts_path = seg["tts_path"]
            if os.path.exists(tts_path):
                with open(tts_path, "rb") as f:
                    audio_b64 = base64.b64encode(f.read()).decode()

                token = client._get_token()
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                lip_task_id = None

                for attempt in range(3):
                    try:
                        lip_r = http_requests.post(
                            "https://openapi.klingai.com/v1/videos/lip-sync",
                            headers=headers,
                            json={"input": {
                                "video_id": video_id,
                                "mode": "audio2video",
                                "audio_type": "file",
                                "audio_file": audio_b64,
                            }},
                            timeout=30,
                        ).json()
                        if lip_r.get("code") == 0:
                            lip_task_id = lip_r["data"]["task_id"]
                            break
                    except Exception as e:
                        print(f"  [reroll_video] lip-sync 重试 {attempt+1}")
                    time.sleep(5)

                if lip_task_id:
                    for i in range(60):
                        time.sleep(10)
                        try:
                            lr = http_requests.get(
                                f"https://openapi.klingai.com/v1/videos/lip-sync/{lip_task_id}",
                                headers={"Authorization": f"Bearer {client._get_token()}"},
                                timeout=30,
                            ).json()
                            status = lr.get("data", {}).get("task_status", "")
                            if status == "succeed":
                                lip_url = lr["data"]["task_result"]["videos"][0]["url"]
                                _download(lip_url, final_path)
                                print(f"  [reroll_video] 段{segment_number}: lip-sync 完成")
                                break
                            elif status == "failed":
                                _download(video_info["url"], final_path)
                                print(f"  [reroll_video] 段{segment_number}: lip-sync 失败, 用原视频")
                                break
                        except Exception:
                            pass
                    else:
                        _download(video_info["url"], final_path)
                else:
                    _download(video_info["url"], final_path)
            else:
                _download(video_info["url"], final_path)
        else:
            _download(video_info["url"], final_path)

        if not os.path.exists(final_path) or os.path.getsize(final_path) < 1000:
            return {"success": False, "message": "视频下载失败"}

        rel = os.path.relpath(final_path, output_dir)
        cm.register(video_asset_key, rel)

        dur = get_media_duration(final_path)
        sz = os.path.getsize(final_path) / 1024 / 1024
        print(f"  [reroll_video] 段{segment_number}: v{version} ({dur:.1f}s, {sz:.1f}MB)")
        return {
            "success": True,
            "message": f"视频段 u{unit_number}_seg{segment_number:02d} 重新生成 v{version}",
            "path": final_path,
            "duration": dur,
            "size_mb": round(sz, 1),
            "candidates": cm.list_candidates(video_asset_key),
        }

    # ================================================================
    # Reroll: dialogue_tts 按段抽卡
    # ================================================================
    def op_reroll_dialogue_tts(self, output_dir: str, unit_number: int,
                               segment_number: int, voice_id: str = None) -> dict:
        """重新生成单个台词段的 TTS。"""
        import re
        import math
        from app.workflows.candidates import CandidateManager
        from app.services.ffmpeg_utils import get_media_duration

        cm = CandidateManager(output_dir)
        cm.load()

        # 加载 video_segments
        vp_path = os.path.join(output_dir, "grids", f"video_segments_u{unit_number}.json")
        if not os.path.exists(vp_path):
            return {"success": False, "message": f"video_segments_u{unit_number}.json 不存在"}
        with open(vp_path) as f:
            vp_data = json.load(f)

        segments = vp_data.get("video_segments", [])
        seg = None
        seg_idx = None
        for i, s in enumerate(segments):
            if s["segment_number"] == segment_number:
                seg = s
                seg_idx = i
                break
        if not seg:
            return {"success": False, "message": f"段 {segment_number} 不存在"}

        if not seg.get("is_dialogue") or not seg.get("dialogue"):
            return {"success": False, "message": f"段 {segment_number} 不是台词段"}

        d = seg["dialogue"]
        char_id = d.get("char_id", "")
        content = d.get("content", "")

        # 去括号注释
        clean_text = re.sub(r'（[^）]*）', '', content)
        clean_text = re.sub(r'\([^)]*\)', '', clean_text).strip()
        if not clean_text:
            return {"success": False, "message": "台词内容为空"}

        # 选择音色
        voice_map_path = os.path.join(output_dir, "voice_map.json")
        if os.path.exists(voice_map_path):
            with open(voice_map_path) as f:
                voice_map = json.load(f)
        else:
            voice_map = {}

        vm = voice_map.get(char_id, {})
        final_voice_id = voice_id or vm.get("voice_id", "male-qn-qingse")
        emotion = vm.get("emotion", "calm")

        # 生成 TTS
        async def _gen():
            from app.ai.providers.minimax_tts import MiniMaxTTSProvider
            provider = MiniMaxTTSProvider()
            job_id = await provider.submit_job({
                "text": clean_text,
                "voice_id": final_voice_id,
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

        tts_asset_key = f"dialogue_tts:u{unit_number}_seg{segment_number:02d}"
        version = cm.next_version(tts_asset_key)
        os.makedirs(os.path.join(output_dir, "audio"), exist_ok=True)
        audio_path = os.path.join(output_dir, "audio",
                                  f"u{unit_number}_seg{segment_number:02d}_dialogue_v{version}.mp3")
        with open(audio_path, "wb") as f:
            f.write(data)

        # 回忆场景：加混响
        is_memory = seg.get("is_memory", False)
        if is_memory:
            mem_path = audio_path.replace(".mp3", "_memory.mp3")
            result = subprocess.run([
                "ffmpeg", "-y", "-i", audio_path,
                "-af", "aecho=0.8:0.7:40|60:0.3|0.2,highpass=f=80,lowpass=f=6000",
                mem_path,
            ], capture_output=True, timeout=15)
            if result.returncode == 0 and os.path.exists(mem_path):
                audio_path = mem_path

        tts_dur = get_media_duration(audio_path)
        final_dur = max(seg.get("estimated_duration", 3), math.ceil(tts_dur), 3)

        # 更新 video_segments JSON
        seg["tts_path"] = os.path.abspath(audio_path)
        seg["tts_duration"] = tts_dur
        seg["final_duration"] = final_dur
        with open(vp_path, "w", encoding="utf-8") as f:
            json.dump(vp_data, f, ensure_ascii=False, indent=2)

        # 注册到 CandidateManager
        rel = os.path.relpath(audio_path, output_dir)
        cm.register(tts_asset_key, rel)

        print(f"  [reroll_tts] 段{segment_number}: v{version} voice={final_voice_id} "
              f"tts={tts_dur:.1f}s final={final_dur}s")
        return {
            "success": True,
            "message": f"TTS u{unit_number}_seg{segment_number:02d} 重新生成 v{version}",
            "path": audio_path,
            "tts_duration": tts_dur,
            "final_duration": final_dur,
            "voice_id": final_voice_id,
            "candidates": cm.list_candidates(tts_asset_key),
        }
