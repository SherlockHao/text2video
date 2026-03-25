# 新旁白漫剧模版 (narration_manga_v2) 设计问题

> 基于对话漫剧 (dialogue_manga) 的技术栈，创建新的旁白漫剧模版。
> 以下 10 个问题需在开发前明确。

---

## 已确认的决策 (Q1-Q7)

| # | 问题 | 决策 |
|---|------|------|
| Q1 | 画面方向 | **竖屏 9:16** |
| Q2 | 分镜方式 | **4×4 Gemini 宫格** |
| Q3 | TTS | **单声优旁白 + sound=on 环境音效 + ElevenLabs 动态 BGM** |
| Q4 | 视频生成策略 | **Plan C 首帧 only，串行执行** |
| Q5 | 字幕 | **drawtext，只写旁白文字** |
| Q6 | 角色图规格 | **白底三视图 1472×832** |
| Q7 | 质量检测 | **加 quality_gate** |

---

## 已确认的决策 (Q8-Q10)

| # | 问题 | 决策 |
|---|------|------|
| Q8 | sound 策略 | **方案 C: sound=on + 降混**（视频原音 -35dB, 旁白 -15dB） |
| Q9 | 分镜剧本结构 | **复用对话漫剧的 script 结构**（type: narration/action） |
| Q10 | 串行执行 | **宫格切帧为首帧 + 顺序逐段执行 + 每段完成后再提交下一段** |

---

## 设计问题归档（全部已确认）

### Q8: sound 策略

旁白漫剧的每一段都有旁白配音（后期叠加）。Kling V3 的 `sound` 参数怎么设？

| 方案 | 做法 | 优点 | 风险 |
|------|------|------|------|
| **A: 全部 off** | 所有段 sound=off | 干净，旁白不会被干扰 | 无环境音效，全靠 BGM 撑氛围 |
| **B: 全部 on** | 所有段 sound=on | 有环境音效（风声、脚步声等） | 角色画面可能自带 AI 人声，与旁白冲突 |
| **C: on + 降混** | sound=on，assembly 时压低视频原音到 -35dB，旁白 -15dB | 环境音效若隐若现 | 复杂度增加，AI 人声仍可能残留 |

**建议**: 方案 C。环境音效能提升沉浸感，通过大幅降低视频原音（-35dB）+ 旁白主导（-15dB）来避免冲突。即使有少量 AI 人声残留，在 -35dB 下几乎不可感知。

---

### Q9: 分镜剧本结构

对话漫剧的 `unit.script` 是 `[{type: dialogue/action, character, content}]`。旁白漫剧没有对话，剧本结构怎么设计？

**建议方案**:

```json
{
  "units": [
    {
      "unit_number": 1,
      "title": "吸引人的标题",
      "core_conflict": "核心冲突一句话",
      "emotion_tone": "悬疑紧张",
      "key_scenes": [
        {"location": "位置", "description": "场景描述"}
      ],
      "ending_hook": "结尾钩子",
      "characters": ["角色A", "角色B"],
      "narration_segments": [
        {
          "narration_text": "旁白文字（20-30字，讲故事而非描述画面）",
          "scene_description": "对应的画面描写（供视频生成参考）",
          "emotion": "calm"
        },
        {
          "narration_text": "第二段旁白...",
          "scene_description": "画面描写...",
          "emotion": "fearful"
        }
      ]
    }
  ],
  "character_profiles": [
    {
      "name": "角色名",
      "char_id": "char_001",
      "gender": "男",
      "age": "青年",
      "appearance_prompt": "外貌文生图提示词",
      "voice_trait": "低沉沙哑"
    }
  ]
}
```

**要点**:
- `narration_segments` 替代对话漫剧的 `script`
- 每条 narration 有独立的 `emotion` 用于 TTS 情感控制
- `scene_description` 用于后续 LLM 生成 video_prompt 时参考，不直接用于 TTS
- `narration_text` 控制在 20-30 字，讲故事而非描述画面

**替代方案**: 也可以复用对话漫剧的 `script` 结构，全部用 `type: "narration"`：
```json
"script": [
  {"type": "narration", "character": null, "content": "旁白文字"},
  {"type": "action", "character": null, "content": "画面描写"}
]
```
哪种更合适？

---

### Q10: 串行执行的具体含义

Plan C + 串行，确认以下理解是否正确：

| 理解 | 是/否？ |
|------|---------|
| 仍然用宫格切帧作为首帧（不用上一段的尾帧） | ？ |
| 视频生成按顺序一段一段执行（不并发提交多个 Kling 任务） | ？ |
| 每段生成完成后才提交下一段 | ？ |

**方案对比**:

| 方案 | 首帧来源 | 执行方式 | 连续性 | 耗时 |
|------|---------|---------|--------|------|
| **Plan C 并行** (对话漫剧现状) | 宫格切帧 | 全部并行 | 硬切 | 最快 |
| **Plan C 串行** | 宫格切帧 | 顺序执行 | 硬切 | 中等 |
| **Plan A 串行** | 上一段尾帧 | 顺序执行 | 帧级连续 | 最慢，有累积误差 |
| **混合方案** | 宫格切帧为主，但参考上一段尾帧做 subject_reference | 顺序执行 | 较好连续性 | 中等 |

---

## 10-Stage Pipeline 规划

确认以上问题后，最终的 pipeline 如下：

```
┌─ 1. storyboard        — LLM 分镜（旁白叙事 + 角色档案）
│     输入: 小说文本 (≤15000字)
│     输出: storyboard.json (units + narration_segments + character_profiles)
│
├─ 2. char_refs          — 角色白底三视图 (Jimeng 1472×832)
│     与对话漫剧相同
│
├─ 3. scene_refs         — 场景参考图 (Gemini + 角色参考)
│     与对话漫剧相同
│
├─ 4. storyboard_grids   — 4×4 宫格分镜图 (Gemini 4K)
│     关键差异: 9:16 竖屏宫格 (3072×5504)
│     每格: 768×1376 → 智能检测分隔线 → LANCZOS resize 统一尺寸
│
├─ 5. video_prompts      — 智能切图 + LLM 15段视频指令
│     关键差异: 无 is_dialogue/dialogue 字段
│     每段: scene_description + camera + emotion + estimated_duration
│
├─ 6. narration_tts      — 单声优 MiniMax TTS
│     关键差异: 一个 voice_id 用于所有段
│     时长校准: final_dur = max(estimated, ceil(tts), 3)
│     无角色音色库、无回忆混响
│
├─ 7. video_gen          — Kling V3 首帧 only, 串行, 9:16
│     关键差异: aspect_ratio="9:16", 串行执行
│     sound 策略: 取决于 Q8
│     无 lip-sync
│
├─ 8. subtitle_burn      — drawtext 旁白文字
│     关键差异: 只有白色旁白文字，无角色名
│     字体: _resolve_cjk_font() 跨平台
│     转义: _ffmpeg_safe_text()
│
├─ 9. assembly           — 统一帧率 + 拼接 + ElevenLabs BGM
│     统一: 720×1280 @30fps (竖屏)
│     BGM: 纯器乐, dB 精确对标 -23dB + 防 clipping
│     如果 Q8 选方案 C: 视频原音降到 -35dB, 旁白 -15dB
│
└─ 10. quality_gate      — 质量检测
      检查: 时长 ≥ 50% 目标 / BGM 可听 / 全部段已生成
```

---

## 复用与新增代码估算

| 部分 | 复用来源 | 改动量 |
|------|---------|--------|
| Stage 1 storyboard | 新 prompt（旁白风格） | **新写** LLM prompt |
| Stage 2 char_refs | dialogue_manga 100% 复用 | 无 |
| Stage 3 scene_refs | dialogue_manga 100% 复用 | 无 |
| Stage 4 storyboard_grids | dialogue_manga 90% | 改 prompt 为 9:16 |
| Stage 5 video_prompts | dialogue_manga 80% | 去 dialogue 字段，改切图参数 |
| Stage 6 narration_tts | 简化版 dialogue_tts | **新写**（更简单） |
| Stage 7 video_gen | dialogue_manga 70% | 去 lip-sync，改 9:16，改串行 |
| Stage 8 subtitle_burn | dialogue_manga 80% | 去角色名，只留旁白 |
| Stage 9 assembly | dialogue_manga 90% | 可能加视频原音降混 |
| Stage 10 quality_gate | narration_manga 旧版 80% | 搬过来 + 适配新结构 |
| Review/Reroll ops | dialogue_manga 80% | 适配新结构 |
| `_detect_grid_panels` | 100% 复用 | 无 |
| `_resolve_cjk_font` | 100% 复用 | 无 |
| `_ffmpeg_safe_text` | 100% 复用 | 无 |
