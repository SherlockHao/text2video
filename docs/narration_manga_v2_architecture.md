# 旁白漫剧 V2 工作流架构文档

> `narration_manga_v2` — 单旁白音轨 + 9:16 竖屏 + 三层音频混合的漫剧推广视频生成模版

## 1. 定位与区别

| 维度 | 旁白漫剧 V2 (`narration_manga_v2`) | 对话漫剧 (`dialogue_manga`) |
|------|-------------------------------------|---------------------------|
| 画面比例 | 9:16 竖屏 (720x1280) | 16:9 横屏 (1280x720) |
| 叙事方式 | 单一旁白配音（无角色对话） | 多角色对话 + 动作描写 |
| 音频合成 | Qwen3-TTS-Instruct-Flash (单旁白) | MiniMax TTS (21 中文音色, 多角色) |
| 音色选择 | LLM 自动选择旁白音色 + 生成 story-aware instruct | LLM 匹配 voice_trait → MiniMax voice_id |
| 角色图 | 白底三视图 (1472x832) | 白底三视图 (1472x832) |
| 场景图 | Gemini (带角色参考, 9:16) | Gemini (带角色参考) |
| 宫格图 | 4x4 宫格 (Gemini 4K, 9:16 portrait) | 4x4 宫格 (Gemini 4K, 16:9) |
| 视频生成 | Kling V3 首帧 only, serial, sound=on, 9:16 | Kling V3 首帧 only (Plan C), parallel |
| 口型同步 | 无 (无 lip-sync) | Kling lip-sync (audio2video) |
| 字幕 | 旁白字幕 (白色) + 自动折行 + 长文本分段 | 角色名(金色) + 台词(白色) |
| 音频混合 | 三层混合: 视频 -35dB / 旁白 -15dB / BGM -28dB | 二层混合: 原始音频 + BGM (volume=0.15) |
| BGM 预处理 | compand + dynaudnorm (3s 窗口, maxgain=25dB) | 无预处理 |
| 角色音色库 | 无 (无 voice_library / voice_map) | MiniMax 21 音色 + 回忆混响版 |
| 回忆混响 | 无 | FFmpeg aecho 混响 |
| 质量检测 | Stage 10: quality_gate | 无 |
| 视频执行 | 串行 (serial) | 可并行 |

## 2. 技术栈

```
LLM:        Qwen 3.5-plus (分镜/旁白音色匹配/视频指令)
图像生成:    Jimeng T2I (角色三视图) + Gemini 3.1 Flash (场景/宫格)
视频生成:    Kling V3 image2video (sound=on, 9:16, serial)
语音合成:    Qwen3-TTS-Instruct-Flash (单旁白, LLM 驱动 instruct)
音乐生成:    ElevenLabs Music API
后处理:      FFmpeg (字幕/三层混音/帧率统一/拼接) + PIL (宫格裁切)
```

## 3. 10-Stage Pipeline

```
+-----------------------------------------------------+
| Stage 1: storyboard                                  |
|   LLM -> units[] + character_profiles[]              |
|   输入: 小说文本 (<=15000字)                           |
|   script 类型: narration (旁白) + action (动作)       |
|   输出: storyboard.json                              |
+-----------------------------------------------------+
| Stage 2: char_refs                                   |
|   Jimeng T2I -> 白底三视图 (1472x832)                 |
|   输出: characters/charref_{cid}_v{n}.png            |
+-----------------------------------------------------+
| Stage 3: scene_refs                                  |
|   Gemini + 角色参考图 -> 场景参考图 (9:16)             |
|   输出: scenes/scene_u{n}_s{n}_v{n}.png              |
+-----------------------------------------------------+
| Stage 4: storyboard_grids                            |
|   LLM -> 16 shot prompts (9:16 portrait)             |
|   Gemini 4K -> 4x4 宫格图 (portrait)                 |
|   输出: grids/grid_u{n}_shots.json + grid_u{n}.png   |
+-----------------------------------------------------+
| Stage 5: video_prompts                               |
|   PIL 切 4x4 -> 16 帧 (portrait)                     |
|   LLM -> 15 段视频分镜指令 (旁白版, 无对话字段)        |
|   输出: frames/u{n}/frame_{nn}.png                   |
|         grids/video_segments_u{n}.json               |
+-----------------------------------------------------+
| Stage 6: narration_tts                               |
|   Step 1: LLM 选旁白音色 + 生成 instruct 指令         |
|   Step 2: Qwen TTS 逐段生成旁白音频 (.wav)            |
|   时长校准: final_dur = max(estimated, ceil(tts), 3)  |
|   输出: narration_voice.json                         |
|         audio/u{n}_seg{nn}_narration.wav             |
+-----------------------------------------------------+
| Stage 7: video_gen                                   |
|   Kling V3 image2video (首帧 only, Plan C)           |
|   9:16, sound=on, serial 串行执行                     |
|   无 lip-sync (旁白在 assembly 叠加)                  |
|   输出: videos/u{n}_seg{nn}_final.mp4                |
+-----------------------------------------------------+
| Stage 8: subtitle_burn                               |
|   FFmpeg drawtext: 旁白字幕 (白色, 28px, 黑色描边)     |
|   自动折行 (20字/行) + 长文本按时长拆段                 |
|   输出: videos/u{n}_seg{nn}_subtitled.mp4            |
+-----------------------------------------------------+
| Stage 9: assembly                                    |
|   统一 720x1280 @30fps                               |
|   旁白时间轴音轨 (adelay 逐段对齐)                     |
|   三层音频混合 + ElevenLabs BGM                       |
|   输出: videos/u{n}_output.mp4                       |
+-----------------------------------------------------+
| Stage 10: quality_gate                               |
|   时长检查: dur >= target * 0.5                       |
|   BGM 可听性检查: volume diff >= 1.0dB               |
|   视频完整性: 全部段已生成                              |
|   旁白覆盖率: 旁白段均有 TTS                           |
+-----------------------------------------------------+
```

## 4. 数据模型

### storyboard.json

```json
{
  "units": [
    {
      "unit_number": 1,
      "title": "标题",
      "core_conflict": "核心冲突",
      "emotion_tone": "悬疑紧张",
      "key_scenes": [{"location": "...", "description": "..."}],
      "ending_hook": "钩子",
      "characters": ["角色A", "角色B"],
      "script": [
        {"type": "narration", "character": null, "content": "旁白文字，讲述剧情推进..."},
        {"type": "action", "character": "角色A", "content": "角色动作描写..."}
      ]
    }
  ],
  "character_profiles": [
    {
      "name": "角色名",
      "char_id": "char_001",
      "gender": "男",
      "age": "青年",
      "appearance_prompt": "外貌文生图提示词"
    }
  ]
}
```

### narration_voice.json

```json
{
  "voice_id": "Serena",
  "reason": "选择理由",
  "tts_instructions": "TTS旁白风格指令（50-80字中文，结合故事内容）"
}
```

### video_segments_u{n}.json

```json
{
  "video_segments": [
    {
      "segment_number": 1,
      "start_frame": 1,
      "end_frame": 2,
      "same_scene_as_prev": false,
      "is_memory": false,
      "scene_description": "中文场景描述",
      "camera_type": "中景",
      "camera_movement": "push_in",
      "emotion": "紧张",
      "narration_text": "对应的旁白文字（20-30字中文），或空字符串",
      "characters_in_frame": ["char_001"],
      "scene_ref_id": "u1_s1",
      "estimated_duration": 5,
      "final_duration": 5,
      "tts_path": "/abs/path/to/audio.wav",
      "tts_duration": 4.2,
      "video_prompt": "视频生成提示词（禁止说话/口型描写）"
    }
  ]
}
```

**注意**：与 dialogue_manga 不同，video_segments 中没有 `is_dialogue`、`dialogue`、`facing` 字段。取而代之的是 `narration_text` 字段。

## 5. 目录结构

```
{output_dir}/
+-- storyboard.json              # Stage 1 输出
+-- narration_voice.json         # Stage 6 LLM 选择旁白音色
+-- candidates.json              # CandidateManager 持久化
+-- characters/
|   +-- charref_char_001_v1.png  # 三视图
+-- scenes/
|   +-- scene_u1_s1_v1.png       # 场景参考图 (9:16)
+-- grids/
|   +-- grid_u1_shots.json       # LLM 16 shot prompts
|   +-- grid_u1_v1.png           # Gemini 4K 宫格图 (9:16 portrait)
|   +-- video_segments_u1.json   # LLM 15 段视频指令 (旁白版)
+-- frames/
|   +-- u1/
|       +-- frame_01.png         # 切出的 16 帧
|       +-- ...
+-- audio/
|   +-- u1_seg01_narration.wav   # 旁白 TTS (Qwen)
|   +-- u1_narration_track.mp3   # 完整旁白时间轴音轨
|   +-- u1_bgm.mp3              # BGM (ElevenLabs)
|   +-- u1_bgm_processed.mp3    # BGM 预处理后
+-- videos/
    +-- u1_seg01_final.mp4       # 原始视频 (sound=on)
    +-- u1_seg01_subtitled.mp4   # 带旁白字幕
    +-- u1_unified_00.mp4        # 统一帧率
    +-- u1_concat.mp4            # 拼接后
    +-- u1_output.mp4            # 最终输出 (三层混合)
```

## 6. 抽卡 / Reroll 体系

| 抽卡目标 | 方法 | 策略 |
|---------|------|------|
| 宫格帧 | `op_reroll_frame` | FIFO 切换备选 -> 超限则重生成整张宫格 -> 切 16 帧 (max 3 版) |
| 视频段 | `op_reroll_video_segment` | 重新 Kling V3 image2video (9:16, sound=on) |
| 旁白 TTS | `op_reroll_narration_tts` | 重新 TTS 生成，支持 voice_id 覆写 |
| 角色参考图 | `op_reroll_char_ref` (继承 mixin) | Jimeng T2I 重新生成 |
| 场景背景 | `op_reroll_scene_bg` (继承 mixin) | Gemini 重新生成 |

**注意**：`op_reroll_tts` 和 `op_reroll_video` 被覆写为错误提示，需使用 V2 专用方法 `op_reroll_narration_tts` 和 `op_reroll_video_segment`。

## 7. Review 操作

| 方法 | 返回内容 |
|------|---------|
| `op_review_storyboard` | 所有 units 摘要 (title/conflict/emotion/characters/narration_count) + character_profiles |
| `op_review_status` | 10 个 stage 的完成状态 + 资产统计 |
| `op_review_characters` | 角色三视图路径（无音色信息） |
| `op_review_unit(n)` | 指定 unit 的 15 段分镜详情 (帧/视频/TTS路径) |
| `op_review_tts` | 按 unit/segment 结构返回旁白 TTS 信息 |
| `op_review_assets(type)` | 指定类型的全部资产列表 |

## 8. 关键决策

### Plan C: 首帧 only, 无尾帧, 串行执行

> 全部视频段使用首帧驱动，无尾帧，硬切过渡。与 dialogue_manga 的并行策略不同，narration_manga_v2 采用**串行执行**，每段生成后等待 5s 再继续下一段，避免 Kling API 并行限制。

### sound=on: Kling V3 音效

> 所有视频段均开启 `sound=on`，让 Kling V3 生成与画面匹配的环境音效。该音效在最终 assembly 时作为三层混合的底层 (Layer 1, -35dB)。

### 无 Lip-sync

> 旁白漫剧无角色对话，不需要口型同步。旁白音频在 assembly 阶段通过时间轴对齐叠加到视频上，而非在视频生成阶段嵌入。

### LLM 驱动旁白音色选择

> 与 dialogue_manga 的固定 voice_map 不同，narration_manga_v2 使用 LLM 根据剧本题材、情感基调、角色信息自动选择最合适的旁白音色，并生成 story-aware 的 TTS instruct 指令（50-80字，描述声音质感、节奏变化、情感层次）。

### 三层音频混合

```
Layer 1: Video original audio (sound=on)  -> volume=-35dB
Layer 2: Narration TTS track              -> mean=-15dB (动态校准)
Layer 3: BGM (instrumental)               -> mean=-28dB (动态校准) + fade out 1s
```

- 每层独立测量均值 (loudnorm meanvol)
- 动态计算调整量: `adjust_dB = target_dB - measured_mean`
- 防 clipping: 确保调整后 max_peak < -1.0dB
- amix 混合，duration=first，dropout_transition=2

### 旁白时间轴构建

```python
# 从静音基底开始，逐个 overlay TTS
anullsrc -> [tts1 adelay=offset1] -> [tts2 adelay=offset2] -> ... -> amix
```

每段 TTS 按对应视频段的起始时间偏移（adelay），生成一条完整的旁白时间轴音轨。

### BGM 预处理

两步 FFmpeg 处理管线：

1. **compand** 向上压缩: 低于 -30dB 的部分提升（最大 +15dB），高于 -20dB 不动
2. **dynaudnorm** 滑窗均衡: 3s 窗口 (framelen=3000)，peak=0.95，maxgain=25dB，correctdc=1

```
compand=attacks=0.1:decays=0.5:points=-90/-90|-45/-20|-30/-16|-20/-16|0/0:gain=0,
dynaudnorm=framelen=3000:gausssize=31:peak=0.95:maxgain=25:correctdc=1
```

### 字幕自动折行 + 长文本拆段

- 每行最大 20 个中文字 (720px 竖屏, fontsize=28, 留边距 40px)
- 折行优先在标点处断句（逗号、句号、叹号、问号、分号、顿号）
- 总行数 <= 2 行: 一次性显示全时长
- 总行数 > 2 行: 拆成 2 段，各显示一半时长
- FFmpeg drawtext `enable='between(t,start,end)'` 控制显示时间

### 时长校准

```python
final_duration = max(estimated_duration, math.ceil(tts_duration), 3)
```

无额外 buffer，精确对齐。非旁白段: `final = max(estimated, 3)`。

### 帧率统一

所有 clip 在拼接前统一为 `720x1280 @30fps`：
- 9:16 竖屏 (portrait)
- 无音频的 clip 添加静音轨 (anullsrc)
- libx264, preset=fast, crf=18

### Quality Gate 检测项

| 检测项 | 条件 | 判定 |
|--------|------|------|
| 时长 | `dur < target * 0.5` | FAIL |
| BGM 可听性 | `abs(concat_mean - output_mean) < 1.0dB` | FAIL |
| 视频完整性 | `generated < total_segments` | FAIL |
| 旁白覆盖率 | `tts_with_file < narration_segments` | FAIL |

## 9. API 端点

```
GET  /workflows/narration_manga_v2/review/storyboard?output_dir=...
GET  /workflows/narration_manga_v2/review/status?output_dir=...
GET  /workflows/narration_manga_v2/review/characters?output_dir=...
GET  /workflows/narration_manga_v2/review/unit/{n}?output_dir=...
GET  /workflows/narration_manga_v2/review/tts?output_dir=...
GET  /workflows/narration_manga_v2/review/assets?asset_type=...&output_dir=...
POST /workflows/narration_manga_v2/reroll/frame
POST /workflows/narration_manga_v2/reroll/video-segment
POST /workflows/narration_manga_v2/reroll/narration-tts
POST /workflows/narration_manga_v2/reroll/char-ref
POST /workflows/narration_manga_v2/reroll/scene-bg
```

## 10. CLI 命令

```bash
# 执行完整流程
python scripts/e2e_v11b.py run --workflow narration_manga_v2 --input data/novel.txt --output e2e_output/test

# 审查
python scripts/e2e_v11b.py review storyboard --workflow narration_manga_v2 --output dir
python scripts/e2e_v11b.py review characters --workflow narration_manga_v2 --output dir
python scripts/e2e_v11b.py review unit --workflow narration_manga_v2 --output dir --unit 1
python scripts/e2e_v11b.py review tts --workflow narration_manga_v2 --output dir
python scripts/e2e_v11b.py review assets --workflow narration_manga_v2 --output dir --asset-type grids

# 抽卡
python scripts/e2e_v11b.py reroll frame --workflow narration_manga_v2 --output dir --unit 1 --frame 3
python scripts/e2e_v11b.py reroll video_segment --workflow narration_manga_v2 --output dir --unit 1 --seg 1
python scripts/e2e_v11b.py reroll narration_tts --workflow narration_manga_v2 --output dir --unit 1 --seg 1
```
