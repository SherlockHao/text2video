# 对话漫剧工作流架构文档

> `dialogue_manga` — 人物有自己的对话语言（替代旁白）的漫剧推广视频生成模版

## 1. 定位与区别

| 维度 | 旁白漫剧 V2 (`narration_manga_v2`) | 对话漫剧 (`dialogue_manga`) |
|------|----------------------------|---------------------------|
| 叙事方式 | 单一旁白配音 | 多角色对话 + 动作描写 |
| 音频 | 全局 TTS → 按段切分 | 按段独立 TTS，角色音色各异 |
| 角色图 | 上半身肖像 (832×1472) | 白底三视图 (1472×832) |
| 场景图 | Jimeng T2I | Gemini (带角色参考输入) |
| 分镜图 | 无宫格 | 4×4 宫格 (Gemini 4K → PIL 切 16 帧) |
| 视频生成 | Kling V3 首帧+尾帧 | Kling V3 首帧 only (Plan C) |
| 口型同步 | 无 | Kling lip-sync (audio2video) |
| 字幕 | 旁白字幕 | 角色名(金色) + 台词(白色) |

## 2. 技术栈

```
LLM:        Qwen 3.5-plus (分镜/配音匹配/视频指令)
图像生成:    Jimeng T2I (角色三视图) + Gemini 3.1 Flash (场景/宫格)
视频生成:    Kling V3 image2video + lip-sync
语音合成:    Qwen3-TTS-Instruct-Flash (50+ 中文音色 + 自然语言 instruct)
音乐生成:    ElevenLabs Music API
后处理:      FFmpeg (字幕/混音/帧率统一/拼接) + PIL (宫格裁切)
```

## 3. 10-Stage Pipeline

```
┌─────────────────────────────────────────────────────┐
│ Stage 1: storyboard                                 │
│   LLM → units[] + character_profiles[]              │
│   输入: 小说文本 (≤15000字)                           │
│   输出: storyboard.json                             │
├─────────────────────────────────────────────────────┤
│ Stage 2: char_refs                                  │
│   Jimeng T2I → 白底三视图 (1472×832)                  │
│   输出: characters/charref_{cid}_v{n}.png           │
├─────────────────────────────────────────────────────┤
│ Stage 3: char_voices                                │
│   LLM 匹配 voice_trait → Qwen voice_id              │
│   LLM 生成 per-character tts_instructions            │
│   Qwen TTS → 主音色样本 (同步调用)                     │
│   FFmpeg aecho → 回忆混响版                           │
│   输出: voice_map.json + voice_library.json          │
├─────────────────────────────────────────────────────┤
│ Stage 4: scene_refs                                 │
│   Gemini + 角色参考图 → 场景参考图                     │
│   输出: scenes/scene_u{n}_s{n}_v{n}.png             │
├─────────────────────────────────────────────────────┤
│ Stage 5: storyboard_grids                           │
│   LLM → 16 shot prompts                            │
│   Gemini 4K (5504×3072) → 4×4 宫格图                │
│   输出: grids/grid_u{n}_shots.json + grid_u{n}.png  │
├─────────────────────────────────────────────────────┤
│ Stage 6: video_prompts                              │
│   PIL 切 4×4 → 16 帧 (1376×768)                     │
│   LLM → 16 段视频分镜指令                             │
│   输出: frames/u{n}/frame_{nn}.png                  │
│         grids/video_segments_u{n}.json              │
├─────────────────────────────────────────────────────┤
│ Stage 7: dialogue_tts                               │
│   Qwen TTS (同步) → 对话语音                          │
│   时长校准: final_dur = max(estimated, ceil(tts), 3) │
│   回忆场景: FFmpeg aecho 加混响                       │
│   输出: audio/u{n}_seg{nn}_dialogue.wav             │
├─────────────────────────────────────────────────────┤
│ Stage 8: video_gen                                  │
│   Kling V3 image2video (首帧 only, Plan C)          │
│   lip-sync 决策:                                    │
│     对话 + 非回忆 + 非背对 → lip-sync                │
│     其他 → 直接下载                                   │
│   输出: videos/u{n}_seg{nn}_final.mp4               │
├─────────────────────────────────────────────────────┤
│ Stage 9: subtitle_burn                              │
│   FFmpeg drawtext: 角色名(#FFD700) + 台词(white)     │
│   自动折行: 每行30字, 标点优先断行                      │
│   角色名动态上移避免多行台词重叠 (LINE_HEIGHT=36)       │
│   字体: PingFang SC                                 │
│   输出: videos/u{n}_seg{nn}_subtitled.mp4           │
├─────────────────────────────────────────────────────┤
│ Stage 10: assembly                                  │
│   统一 1280×720 @30fps                              │
│   ElevenLabs BGM (instrumental only, -28dB)         │
│   三层混合: video(-20dB) + BGM(-28dB)                │
│     + dialogue_patch(-15dB, 非lip-sync段)            │
│   BGM 预处理: compand + dynaudnorm (3s, 25dB)       │
│   无淡入 + 淡出1s · dB精确对标 · 防 clipping          │
│   输出: videos/u{n}_output.mp4                      │
└─────────────────────────────────────────────────────┘
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
      "key_scenes": [{"location": "...", "description": "...", "environment_prompt": "English T2I prompt for empty environment"}],
      "ending_hook": "钩子",
      "characters": ["角色A", "角色B"],
      "script": [
        {"type": "dialogue", "character": "角色A", "content": "台词"},
        {"type": "action", "character": null, "content": "环境描写"}
      ]
    }
  ],
  "character_profiles": [
    {
      "name": "角色名",
      "char_id": "char_001",
      "gender": "男",
      "age": "青年",
      "appearance_prompt": "structured: body type, hair, clothing, props, marks",
      "voice_trait": "低沉沙哑"
    }
  ]
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
      "is_dialogue": true,
      "is_memory": false,
      "dialogue": {
        "character": "角色A",
        "char_id": "char_001",
        "content": "台词内容",
        "facing": "面向镜头"
      },
      "estimated_duration": 5,
      "final_duration": 5,
      "tts_path": "/abs/path/to/audio.wav",
      "tts_duration": 4.2,
      "video_prompt": "视频生成提示词"
    }
  ]
}
```

## 5. 目录结构

```
{output_dir}/
├── storyboard.json              # Stage 1 输出
├── voice_map.json               # Stage 3 LLM 匹配结果
├── candidates.json              # CandidateManager 持久化
├── characters/
│   ├── charref_char_001_v1.png  # 三视图
│   ├── voice_char_001_v1.wav    # 主音色样本
│   ├── voice_char_001_memory_v1.wav  # 回忆混响版
│   └── voice_library.json       # 音色元数据
├── scenes/
│   └── scene_u1_s1_v1.png       # 场景参考图
├── grids/
│   ├── grid_u1_shots.json       # LLM 16 shot prompts
│   ├── grid_u1_v1.png           # Gemini 4K 宫格图
│   └── video_segments_u1.json   # LLM 16 段视频指令
├── frames/
│   └── u1/
│       ├── frame_01.png         # 切出的 16 帧
│       └── ...
├── audio/
│   ├── u1_seg01_dialogue.wav    # 对话 TTS
│   └── u1_bgm.mp3              # BGM
└── videos/
    ├── u1_seg01_final.mp4       # 原始视频
    ├── u1_seg01_subtitled.mp4   # 带字幕
    ├── u1_unified_00.mp4        # 统一帧率
    └── u1_output.mp4            # 最终输出
```

## 6. 抽卡 / Reroll 体系

| 抽卡目标 | 方法 | 策略 |
|---------|------|------|
| 宫格帧 | `op_reroll_frame` | FIFO 切换备选 → 超限则重生成整张宫格 → 切 16 帧 (max 3 版) |
| 视频段 | `op_reroll_video_segment` | 重新 Kling V3 + lip-sync |
| 对话 TTS | `op_reroll_dialogue_tts` | 重新 Qwen TTS，支持 voice_id 覆写 |
| 角色参考图 | `op_reroll_char_ref` (继承 mixin) | Jimeng T2I 重新生成 |
| 场景背景 | `op_reroll_scene_bg` (继承 mixin) | Gemini 重新生成 |

## 7. Review 操作

| 方法 | 返回内容 |
|------|---------|
| `op_review_storyboard` | 所有 units 摘要 + character_profiles |
| `op_review_status` | 10 个 stage 的完成状态 + 资产统计 |
| `op_review_characters` | 角色三视图路径 + 音色信息 |
| `op_review_unit(n)` | 指定 unit 的 16 段分镜详情 (帧/视频/TTS路径) |
| `op_review_assets(type)` | 指定类型的全部资产列表 |

## 8. 关键决策

### Plan C: 首帧 only, 无尾帧

> "差一点不同比完全不同更不自然" — 通过 AIGC 专家讨论确定。
> 全部视频段使用首帧驱动，无尾帧，硬切过渡。全部段可并行生成，无累积误差。

### Lip-sync 决策逻辑

```python
need_lipsync = is_dialogue and not is_memory and "背" not in facing
```

- 正常对话 + 面向/侧面镜头 → lip-sync
- 回忆场景 → 跳过 (使用混响音频叠加)
- 背对镜头 → 跳过

### 时长校准

```python
final_duration = max(estimated_duration, math.ceil(tts_duration), 3)
```

无额外 buffer，精确对齐。

### 帧率统一

所有 clip 在拼接前统一为 `1280×720 @30fps`：
- Kling image2video 输出 24fps
- Kling lip-sync 输出 30fps
- 混合拼接会导致冻帧，必须预处理

## 9. API 端点

```
GET  /workflows/dialogue_manga/review/storyboard?output_dir=...
GET  /workflows/dialogue_manga/review/status?output_dir=...
GET  /workflows/dialogue_manga/review/characters?output_dir=...
GET  /workflows/dialogue_manga/review/unit/{n}?output_dir=...
GET  /workflows/dialogue_manga/review/assets?asset_type=...&output_dir=...
POST /workflows/dialogue_manga/reroll/frame
POST /workflows/dialogue_manga/reroll/video-segment
POST /workflows/dialogue_manga/reroll/dialogue-tts
POST /workflows/dialogue_manga/reroll/char-ref
POST /workflows/dialogue_manga/reroll/scene-bg
```

## 10. CLI 命令

```bash
# 执行完整流程
python scripts/e2e_v11b.py run --workflow dialogue_manga --input data/novel.txt --output e2e_output/test

# 审查
python scripts/e2e_v11b.py review storyboard --workflow dialogue_manga --output dir
python scripts/e2e_v11b.py review characters --workflow dialogue_manga --output dir
python scripts/e2e_v11b.py review unit --workflow dialogue_manga --output dir --unit 1
python scripts/e2e_v11b.py review assets --workflow dialogue_manga --output dir --asset-type grids

# 抽卡
python scripts/e2e_v11b.py reroll frame --workflow dialogue_manga --output dir --unit 1 --frame 3
python scripts/e2e_v11b.py reroll video_segment --workflow dialogue_manga --output dir --unit 1 --seg 1
python scripts/e2e_v11b.py reroll dialogue_tts --workflow dialogue_manga --output dir --unit 1 --seg 1
```
