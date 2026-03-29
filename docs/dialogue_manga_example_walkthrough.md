# 对话漫剧 — 完整流程示例

> 以古风武侠小说《孤星铁匠铺》为例，展示从小说文本输入到最终视频输出的全过程。

---

## 输入

**小说文本** (`data/test_novel.txt`, 630 字)：

```
黄昏，陈记铁匠铺内炉火正旺，火星四溅。陈锈赤着上身，肌肉紧绷，
机械地挥舞铁锤……

（隔着街道，声音清亮穿透喧闹）"据说，那孤星剑客遇到了一种比死
更可怕的东西……让人忘记自己是谁。"

陈锈高举的铁锤在半空猛地一顿……

（低声呢喃，声音颤抖）"忘记……自己是谁……"

……阿九没有看别人，只看着他，像是在看一个久别的故人。
```

**执行命令**：

```bash
python scripts/e2e_v11b.py run \
  --workflow dialogue_manga \
  --input data/test_novel.txt \
  --output e2e_output/dialogue_test
```

---

## Stage 1: storyboard (LLM 分镜)

**调用**: Qwen 3.5-plus

**LLM 输出**: `storyboard.json`

LLM 识别出 5 个冲突单元、4 个角色。以 Unit 1 为例：

```json
{
  "units": [
    {
      "unit_number": 1,
      "title": "铁匠失手，说书人唤醒沉睡剑魂",
      "core_conflict": "神秘说书人阿九用故事刺激失忆铁匠陈锈，导致其本能觉醒却引发剧烈头痛与记忆碎片。",
      "emotion_tone": "悬疑紧张",
      "key_scenes": [
        {
          "location": "陈记铁匠铺",
          "description": "黄昏炉火旁，陈锈听到关于'孤星剑客'的故事，手中铁锤莫名停顿。",
          "environment_prompt": "ancient Chinese blacksmith forge at dusk, roaring charcoal furnace, orange firelight, iron tools on walls, rusty anvil, sparks flying, smoke and haze, wooden beams, warm golden tones"
        },
        {
          "location": "茶馆二楼窗口",
          "description": "阿九压低声音讲述传说，目光穿过街道锁定铁匠铺内的陈锈。",
          "environment_prompt": "second floor window of ancient Chinese teahouse, wooden lattice window frame, overlooking busy street below, warm lantern light inside, tea set on table, dusk sky"
        },
        {
          "location": "铁匠铺内",
          "description": "陈锈挥锤失误，废铁落地激起白雾，抬头正对上阿九清冷的视线。",
          "environment_prompt": "interior of blacksmith forge, red-hot iron on anvil, white steam rising from water bucket, scattered tools, dim firelight, heavy atmosphere"
        }
      ],
      "ending_hook": "深夜阿九潜入铁匠铺摇响铜铃，陈锈瞬间陷入冷蓝色风雪幻象。",
      "characters": ["陈锈", "阿九"],
      "script": [
        {"type": "action", "character": null, "content": "黄昏，陈记铁匠铺内炉火正旺，火星四溅。陈锈赤着上身，机械地挥舞铁锤。"},
        {"type": "dialogue", "character": "阿九", "content": "据说，那孤星剑客遇到了一种比死更可怕的东西……让人忘记自己是谁。"},
        {"type": "action", "character": "陈锈", "content": "高举的铁锤在半空猛地一顿，眼神瞬间变得空洞而痛苦。"},
        {"type": "dialogue", "character": "陈锈", "content": "忘记……自己是谁……"},
        {"type": "action", "character": "陈锈", "content": "猛地挥下铁锤，却砸偏了方位。废铁落地激起白色水汽。"},
        {"type": "action", "character": null, "content": "陈锈透过水汽抬头，正对上茶馆二楼窗口阿九那一双清冷的眼睛。"}
      ]
    }
  ],
  "character_profiles": [
    {
      "name": "陈锈 (孤星)",
      "char_id": "char_001",
      "gender": "男",
      "age": "25 岁",
      "appearance_prompt": "25岁男性，古铜色皮肤，身材高大魁梧，黑色短发，赤膊穿粗布短打，双手厚茧，背负一根生锈铁棍",
      "voice_trait": "低沉沙哑，像被锻打过的铁器"
    },
    {
      "name": "阿九",
      "char_id": "char_002",
      "gender": "女",
      "age": "20 多岁",
      "appearance_prompt": "20多岁女性，身穿粗布青衣，面容清秀，黑色长发，腰间挂一串铜铃，手持短刀",
      "voice_trait": "清亮如泉水，带着故事感"
    },
    {
      "name": "孟婆",
      "char_id": "char_003",
      "gender": "女",
      "age": "50 岁",
      "appearance_prompt": "50岁女性，灰白色长袍，脸戴无五官的空白瓷面具，身姿如玉雕般静止",
      "voice_trait": "温柔催眠感，像风穿过空谷"
    },
    {
      "name": "赵客",
      "char_id": "char_004",
      "gender": "男",
      "age": "40 多岁",
      "appearance_prompt": "40多岁中年男性，浑身是血，胸口有深可见骨的黑色毒伤，面容憔悴",
      "voice_trait": "虚弱急促，临终前的嘶哑"
    }
  ]
}
```

---

## Stage 2: char_refs (角色三视图)

**调用**: Jimeng T2I (1472x832)

每个角色一张白底三视图（正面+侧面+背面），prompt 示例（陈锈）：

```
杰作, 最高质量, 4K, 动漫风格, 赛璐璐上色, 角色设定图, 白色背景, 三视图,
正面视图+侧面视图+背面视图, 男性角色,
25岁男性，古铜色皮肤，身材高大魁梧，黑色短发，赤膊穿粗布短打，双手厚茧，背负一根生锈铁棍,
全身立绘, 表情自然, 姿态端正, 纯净白色背景, 无文字, 无水印, 单人
```

**输出**: 4 张角色三视图

```
characters/charref_char_001_v1_0.png  ← 陈锈
characters/charref_char_002_v1_0.png  ← 阿九
characters/charref_char_003_v1_0.png  ← 孟婆
characters/charref_char_004_v1_0.png  ← 赵客
```

[陈锈三视图] [阿九三视图] [孟婆三视图] [赵客三视图]

---

## Stage 3: char_voices (角色音色库)

### Step 1: LLM 匹配音色

**调用**: Qwen 3.5-plus + VOICE_MATCH_SYSTEM_PROMPT

LLM 根据每个角色的 `voice_trait` 从 50+ Qwen 音色中选择最匹配的，并生成 TTS instruct：

```json
{
  "matches": [
    {
      "char_id": "char_001",
      "voice_id": "Ethan",
      "reason": "温暖但带粗犷感的男声适合铁匠角色",
      "intro_text": "我是陈锈，曾如孤星漂泊，如今只剩这副冷硬躯壳。",
      "tts_instructions": "低沉沙哑的嗓音，说话沉稳有力但带着迷茫，语速偏慢，像在努力回忆什么，每句话尾音略微下沉。"
    },
    {
      "char_id": "char_002",
      "voice_id": "Cherry",
      "reason": "开朗清亮的年轻女声适合说书人角色",
      "intro_text": "我叫阿九，若你敢对峙，便见识我的锐利与坚定。",
      "tts_instructions": "清亮灵动的女声，讲故事时抑扬顿挫有节奏感，悬念处刻意压低声音放慢语速，营造神秘氛围。"
    }
  ]
}
```

### Step 2: Qwen TTS 生成音色样本

**调用**: Qwen3-TTS-Instruct-Flash (同步)

每个角色生成自我介绍音频 + 回忆混响版（FFmpeg aecho）。

**输出**: `voice_map.json` + `voice_library.json` + 音频文件

```
characters/voice_char_001_v1.wav          ← 陈锈主音色
characters/voice_char_001_memory_v1.wav   ← 陈锈回忆混响版
characters/voice_char_002_v1.wav          ← 阿九主音色
characters/voice_char_002_memory_v1.wav   ← 阿九回忆混响版
...
```

---

## Stage 4: scene_refs (场景参考图)

**调用**: Gemini 3.1 Flash (带角色参考图作为风格参考)

使用 `environment_prompt`（英文纯环境描述）生成空镜图，prompt 示例（铁匠铺）：

```
Generate an anime background scene image — EMPTY ENVIRONMENT ONLY.
Location: 陈记铁匠铺.
Environment description: ancient Chinese blacksmith forge at dusk, roaring charcoal furnace,
orange firelight, iron tools on walls, rusty anvil, sparks flying, smoke and haze...
This is a pure environment/background art with NO characters, NO people...
```

**输出**: 每个 unit 3 张空镜场景图（共 5 units × 3 = 15 张）

```
scenes/scene_u1_s1_v1.png  ← 陈记铁匠铺（炉火、铁砧、暖光）
scenes/scene_u1_s2_v1.png  ← 茶馆二楼窗口（木窗、灯笼、街景）
scenes/scene_u1_s3_v1.png  ← 铁匠铺内（蒸汽、铁器、暗光）
```

[铁匠铺空镜] [茶馆空镜] [铺内空镜]

---

## Stage 5: storyboard_grids (4x4 宫格分镜图)

### Step A: LLM 生成 16 个分镜 prompt

```json
{
  "style_tags": ["anime style", "manga illustration", "dramatic lighting", "suspenseful atmosphere", "cel shaded"],
  "shots": [
    {"shot_number": 1, "prompt_text": "EWS, sunset glow over bustling street, Chen's forge glowing fiercely, sparks flying, cinematic, no timecode, no subtitles"},
    {"shot_number": 2, "prompt_text": "MCU, shirtless muscular blacksmith Chen Xiu swinging hammer, intense focus, sweat dripping, warm firelight, no timecode, no subtitles"},
    {"shot_number": 3, "prompt_text": "MS, storyteller Ah Jiu standing across street, green robe, clear eyes, holding short blade, anime style, no timecode, no subtitles"},
    {"shot_number": 4, "prompt_text": "CU, Ah Jiu speaking calmly, copper bells at waist, mysterious aura, soft wind, detailed features, no timecode, no subtitles"},
    "...共 16 个"
  ]
}
```

### Step B: Gemini 生成宫格图

**输出**: `grids/grid_u1_v1.png` (5504x3072, 16:9 横屏 4K)

[4×4 宫格分镜图 — 16 个横屏面板]

---

## Stage 6: video_prompts (切图 + 分镜指令)

### Step A: PIL 智能切割

自动检测分隔线 → 16 帧 → LANCZOS resize 统一 16:9

**输出**: `frames/u1/frame_01.png` ~ `frame_16.png`

### Step B: LLM 生成 16 段视频指令

```json
{
  "video_segments": [
    {
      "segment_number": 1,
      "start_frame": 1,
      "is_dialogue": false,
      "scene_description": "黄昏时分，陈记铁匠铺外景转内景，炉火旺盛。",
      "camera_type": "远景转中近景",
      "camera_movement": "push_in",
      "emotion": "紧张",
      "video_prompt": "镜头从繁忙街道的黄昏全景缓缓推进，穿过飞溅的火星，聚焦到铁匠铺内赤膊的陈锈。",
      "estimated_duration": 4
    },
    {
      "segment_number": 3,
      "start_frame": 3,
      "is_dialogue": true,
      "dialogue": {
        "character": "阿九",
        "char_id": "char_002",
        "content": "据说，那孤星剑客遇到了一种比死更可怕的东西……让人忘记自己是谁。",
        "facing": "侧面"
      },
      "video_prompt": "镜头缓慢推近阿九的面部，她嘴唇微动，腰间铜铃随风轻晃。",
      "estimated_duration": 8
    },
    "...共 16 段..."
  ]
}
```

---

## Stage 7: dialogue_tts (对话语音)

**调用**: Qwen3-TTS-Instruct-Flash (同步)

逐段生成对话语音，每段用对应角色的 voice_id + tts_instructions：

| 段 | 角色 | 对话 | voice_id | TTS | final |
|----|------|------|----------|-----|-------|
| 段3 | 阿九 | "据说，那孤星剑客遇到了..." | Cherry | 7.0s | 8s |
| 段5 | 陈锈 | "忘记……自己是谁……" | Ethan | 3.2s | 4s |

时长校准: `final_duration = max(estimated, ceil(tts_duration), 3)`

回忆场景自动加混响 (FFmpeg aecho)。

**输出**:

```
audio/u1_seg03_dialogue.wav  ← 阿九台词
audio/u1_seg05_dialogue.wav  ← 陈锈台词
```

---

## Stage 8: video_gen (视频生成 + lip-sync)

**调用**: Kling V3 image2video + lip-sync

每段用对应帧作为首帧。sound 策略：

| 段类型 | sound | lip-sync | 音频来源 |
|--------|-------|----------|---------|
| action 段（无对话） | **on** | 无 | Kling 自动生成环境音效 |
| dialogue 段（面向/侧面） | **off** | **有** | TTS → lip-sync 烧入视频 |
| dialogue 段（回忆/背对） | **off** | **跳过** | TTS 在 assembly 补充混入 |

speech 关键词检测：video_prompt 含"说话/开口/口型"等词 → 强制 sound=off

Lip-sync 流程（段3 阿九对话为例）：
```
1. Kling V3 image2video (frame_03.png + video_prompt, sound=off) → video_id
2. POST /v1/videos/lip-sync (video_id + 阿九 TTS base64) → lip-sync video
3. 下载 lip-sync 后的视频 → u1_seg03_final.mp4
```

**输出**: 16 个 MP4 文件

```
videos/u1_seg01_final.mp4  (4s, sound=on, 环境音效)
videos/u1_seg02_final.mp4  (3s, sound=on, 环境音效)
videos/u1_seg03_final.mp4  (8s, lip-sync, 阿九说话)
videos/u1_seg04_final.mp4  (3s, sound=on, 环境音效)
videos/u1_seg05_final.mp4  (4s, lip-sync, 陈锈说话)
...
```

---

## Stage 9: subtitle_burn (字幕压制)

**调用**: FFmpeg drawtext

仅对 `is_dialogue=true` 的段压制双行字幕：
- 角色名: #FFD700 金色, 22px（自动上移避免重叠）
- 台词: 白色, 28px, 每行 30 字自动折行

```
drawtext=fontfile='PingFang.ttc':fontsize=28:fontcolor=white:borderw=2:
  x=(w-text_w)/2:y=h-th-60:text='据说，那孤星剑客遇到了一种比死更可怕的东西……',
drawtext=fontfile='PingFang.ttc':fontsize=22:fontcolor=#FFD700:borderw=1.5:
  x=(w-text_w)/2:y=h-th-101:text='阿九'
```

**输出**: 带字幕的对话段视频

```
videos/u1_seg03_subtitled.mp4  ← 阿九台词 + 金色名字
videos/u1_seg05_subtitled.mp4  ← 陈锈台词 + 金色名字
```

---

## Stage 10: assembly (组装)

### Step A: 统一帧率
所有 16 段统一为 `1280x720 @30fps`（16:9 横屏），带字幕版优先。

### Step B: 拼接
FFmpeg concat demuxer 硬切拼接。

### Step C: 补充对话音轨
检测 lip-sync 被跳过的对话段（回忆/背对），用 adelay 将其 TTS 按时间轴插入补充音轨。

```
时间轴:  0s ------- 4s ------- 8s ------- 16s ...
补充音轨: [静音]     [静音]      [静音]      ...
```
（本例中所有对话都成功 lip-sync，无需补充）

### Step D: BGM
**调用**: ElevenLabs Music API

LLM 生成纯器乐 prompt，BGM 预处理 (compand + dynaudnorm)。

### Step E: 音频混合

```
Layer 1: 视频原音 (lip-sync 对话 + 环境音效) → -20dB
Layer 2: BGM (纯器乐)                        → -28dB (dB 精确对标)
Layer 3: 补充对话 (如有)                       → -15dB
                                               ↓
                     amix (normalize=0, weights=1 1...) → u1_output.mp4
```

BGM 淡出: 最后 1 秒 (无淡入)

**amix 参数**: `normalize=0` 防止自动缩小各层音量，`weights=1 1...` 保持各层权重一致。

**Assembly fallback chain**: 3-layer mix → 2-layer mix → raw video。任一层混合失败时自动降级。

**Kling V3 duration cap**: 最大 15 秒 (`KLING_MAX_DURATION=15`)，超过的段会被截断。

**输出**: `videos/u1_output.mp4`

---

## 与旁白漫剧 V2 的关键区别

| 维度 | 对话漫剧 | 旁白漫剧 V2 |
|------|---------|------------|
| 画面方向 | **16:9 横屏** | 9:16 竖屏 |
| 叙事方式 | 多角色对话 + 动作 | 单旁白叙述 |
| TTS | **多角色独立音色** + per-char instruct | 单声优 + 故事感 instruct |
| 音色库 | **Stage 3 char_voices** (音色样本 + 回忆混响) | 无 (Stage 6 直接选音色) |
| lip-sync | **有** (Kling lip-sync API) | 无 |
| sound 策略 | 对话段 off + action 段 on | **全部 on** |
| 视频执行 | 可并行 | 串行 |
| 字幕 | **角色名(金) + 台词(白)** 双行 | 旁白(白)单行 + 分时显示 |
| 视频原音衰减 | **-20dB** (保留 lip-sync 对话) | -35dB (极低，旁白主导) |
| 补充音轨 | **有** (非 lip-sync 对话段) | 无 |
| quality_gate | 无 | 有 |

---

## 目录结构

```
e2e_output/dialogue_test/
├── storyboard.json                 # Stage 1: LLM 分镜 (5 units)
├── voice_map.json                  # Stage 3: 音色匹配结果
├── candidates.json                 # 资产版本管理
├── characters/
│   ├── charref_char_001_v1_0.png   # Stage 2: 陈锈三视图
│   ├── charref_char_002_v1_0.png   # 阿九三视图
│   ├── charref_char_003_v1_0.png   # 孟婆三视图
│   ├── charref_char_004_v1_0.png   # 赵客三视图
│   ├── voice_char_001_v1.wav       # Stage 3: 陈锈音色样本
│   ├── voice_char_001_memory_v1.wav# 陈锈回忆混响版
│   ├── voice_char_002_v1.wav       # 阿九音色样本
│   └── voice_library.json          # 音色元数据
├── scenes/
│   ├── scene_u1_s1_v1.png          # Stage 4: 铁匠铺空镜
│   ├── scene_u1_s2_v1.png          # 茶馆空镜
│   └── scene_u1_s3_v1.png          # 铺内空镜
├── grids/
│   ├── grid_u1_shots.json          # Stage 5: 16 shot prompts
│   ├── grid_u1_v1.png              # Stage 5: 4K 宫格图 (5504x3072)
│   └── video_segments_u1.json      # Stage 6: 16 段视频指令
├── frames/
│   └── u1/
│       ├── frame_01.png            # Stage 6: 切出的 16 帧
│       └── ...frame_16.png
├── audio/
│   ├── u1_seg03_dialogue.wav       # Stage 7: 阿九对话 TTS
│   ├── u1_seg05_dialogue.wav       # 陈锈对话 TTS
│   ├── u1_bgm.mp3                  # Stage 10: BGM
│   └── u1_bgm_processed.mp3       # BGM 预处理后
└── videos/
    ├── u1_seg01_final.mp4          # Stage 8: Kling V3 视频
    ├── u1_seg03_final.mp4          # lip-sync 版本
    ├── u1_seg03_subtitled.mp4      # Stage 9: 带字幕
    ├── ...
    ├── u1_seg16_final.mp4
    └── u1_output.mp4               # 最终输出
```
