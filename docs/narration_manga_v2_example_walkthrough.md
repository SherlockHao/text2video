# 旁白漫剧 V2 — 完整流程示例

> 以都市言情小说《落魄千金》为例，展示从小说文本输入到最终视频输出的全过程。

---

## 输入

**小说文本** (`data/test_novel_v2.txt`, 2581 字)：

```
苏念念低着头，快步穿过陆氏集团那挑高十米的宏伟大厅。脚下那双有些磨损的高跟鞋在
光洁如镜的大理石地面上敲击出急促而清脆的声响……

她不敢抬头，甚至不敢让视线有任何多余的游移，生怕对上那些从四面八方投来的、带着
审视与嘲弄的目光……

"听说了吗？苏家破产了，她现在就是个灰姑娘。"

……

陆景琛——全城最年轻的商业帝国掌门人。三年前那个雨夜，她不告而别的男人。

"苏小姐，好久不见。"

"陆总，我是新来的助理。"

……

"苏念念，这一次，我不会再让你跑了。"
```

**执行命令**：

```bash
python scripts/e2e_v11b.py run \
  --workflow narration_manga_v2 \
  --input data/test_novel_v2.txt \
  --output e2e_output/narration_v2_test
```

---

## Stage 1: storyboard (LLM 分镜)

**调用**: Qwen 3.5-plus

**LLM 输入**: 小说全文 + NARRATION_STORYBOARD_SYSTEM_PROMPT

**LLM 输出**: `storyboard.json`

```json
{
  "units": [
    {
      "unit_number": 1,
      "title": "落魄千金闯入狼穴",
      "core_conflict": "破产千金为母治病忍辱入职，却直面曾被自己抛弃的复仇总裁。",
      "emotion_tone": "悬疑紧张",
      "key_scenes": [
        {
          "location": "陆氏集团大厅",
          "description": "苏念念低头穿过宏伟大厅，耳边充斥着员工对她家道中落的嘲讽议论。",
          "environment_prompt": "挑高十米的宽敞企业大厅，光洁如镜的大理石地面反射冷白日光，四周玻璃幕墙，现代极简风格，冷灰色调，氛围压抑肃杀"
        },
        {
          "location": "总裁办公室门口",
          "description": "苏念念推开门瞬间看到阳光下坐在真皮椅上的陆景琛，整个人僵住。",
          "environment_prompt": "豪华总裁办公室入口视角，巨大落地窗透入午后暖阳将室内切割成明暗两半，深色胡桃木办公桌，黑色真皮高背转椅"
        },
        {
          "location": "总裁办公桌前",
          "description": "陆景琛步步紧逼，将苏念念笼罩在阴影中，眼神如猎人锁定猎物。",
          "environment_prompt": "总裁办公桌特写区域，红木桌面纹理清晰，桌上散落文件和钢笔，背景是巨大落地窗和城市天际线，光影对比强烈"
        }
      ],
      "ending_hook": "陆景琛低声吐出'这次折断翅膀也要留住你'。",
      "characters": ["苏念念", "陆景琛", "王经理"],
      "script": [
        {"type": "action", "character": "苏念念", "content": "苏念念低着头快步穿过大厅，磨损的高跟鞋敲击地面，手指死死攥紧文件夹。"},
        {"type": "narration", "character": null, "content": "昔日苏家大小姐如今沦为抵债秘书，耳边的嘲弄如针扎心，她只为母亲医药费强忍屈辱。"},
        {"type": "action", "character": "苏念念", "content": "她在冰冷的金属门前停顿一秒，推开门，却在看到椅上男人的瞬间血液凝固。"},
        {"type": "narration", "character": null, "content": "那是三年前被她狠心抛下的恋人陆景琛，如今已是掌控她生杀大权的商业帝国掌门人。"},
        {"type": "action", "character": "陆景琛", "content": "陆景琛缓缓抬头，目光穿透文件落在她身上，随即起身绕过办公桌，一步步无声地逼近。"},
        {"type": "narration", "character": null, "content": "他居高临下质问谁曾誓言永不离开，苏念念咬唇忍住眼泪，只求公事公办却遭无情拒绝。"},
        {"type": "action", "character": "陆景琛", "content": "陆景琛嘴角勾起凉薄笑意，转身坐回椅子，慵懒宣布她是专属助理，二十四小时随叫随到。"},
        {"type": "narration", "character": null, "content": "在这陆氏他的意志就是规定，猎人已锁定猎物，直言绝不会再让她有机会逃跑。"},
        {"type": "action", "character": "王经理", "content": "王经理推门送入资料，目光在两人间惊疑游移，领命安排苏念念搬入办公室外套间。"},
        {"type": "narration", "character": null, "content": "这哪里是招聘分明是变相囚禁，苏念念被迫接受命令，转身走向那扇沉重的大门。"},
        {"type": "action", "character": "陆景琛", "content": "陆景琛靠在椅背上闭目，指尖摩挲袖扣，低声吐出'欢迎回来'与'折断翅膀'的狠话。"},
        {"type": "narration", "character": null, "content": "苏念念颤抖着没有回头径直离去，而门内男人脑海中全是雨夜她决绝背影，誓要将其禁锢身边。"}
      ]
    }
  ],
  "character_profiles": [
    {
      "name": "苏念念",
      "char_id": "char_001",
      "gender": "女",
      "age": "24 岁",
      "appearance_prompt": "24 岁女性，身形纤细瘦弱，皮肤苍白，黑色长直发略显凌乱垂在肩头，穿着米白色有些磨损的衬衫搭配黑色职业短裙，脚踩一双鞋跟磨损的黑色高跟鞋，怀抱棕色皮质文件夹"
    },
    {
      "name": "陆景琛",
      "char_id": "char_002",
      "gender": "男",
      "age": "27 岁",
      "appearance_prompt": "27 岁男性，身材高大魁梧，黑色短发梳理整齐，穿着深灰色定制三件套西装，内搭白色衬衫系深蓝领带，袖口佩戴铂金袖扣，面容冷峻棱角分明"
    },
    {
      "name": "王经理",
      "char_id": "char_003",
      "gender": "男",
      "age": "45 岁",
      "appearance_prompt": "45 岁男性，体型微胖，头发稀疏向后梳，戴着金丝边框眼镜，穿着深蓝色普通西装套装，手持一叠白色文件资料"
    }
  ]
}
```

**耗时**: ~37s

---

## Stage 2: char_refs (角色三视图)

**调用**: Jimeng T2I (1472x832)

每个角色生成一张白底三视图参考图，prompt 示例（苏念念）：

```
杰作, 最高质量, 高度精细, 4K, 动漫风格, 漫画风格, 赛璐璐上色, 鲜艳色彩,
角色设定图, 白色背景, 三视图, 正面视图+侧面视图+背面视图,
女性角色, 24 岁女性，身形纤细瘦弱，皮肤苍白，黑色长直发略显凌乱垂在肩头，
穿着米白色有些磨损的衬衫搭配黑色职业短裙，脚踩一双鞋跟磨损的黑色高跟鞋，
怀抱棕色皮质文件夹,
全身立绘, 表情自然, 姿态端正, 纯净白色背景, 摄影棚灯光, 无文字, 无水印, 高清锐利, 单人
```

**输出**: 3 张角色三视图 PNG

```
characters/charref_char_001_v1_0.png  ← 苏念念
characters/charref_char_002_v1_0.png  ← 陆景琛
characters/charref_char_003_v1_0.png  ← 王经理
```

[苏念念三视图] [陆景琛三视图] [王经理三视图]

**耗时**: ~72s

---

## Stage 3: scene_refs (场景参考图)

**调用**: Gemini 3.1 Flash (带角色参考图作为风格参考)

每个 key_scene 用 `environment_prompt`（英文纯环境描述）生成空镜图，prompt 示例（场景1）：

```
Generate an anime background scene image in 9:16 portrait aspect ratio — EMPTY ENVIRONMENT ONLY.
Location: 陆氏集团大厅.
Environment description: 挑高十米的宽敞企业大厅，光洁如镜的大理石地面反射冷白日光，
四周玻璃幕墙，现代极简风格，冷灰色调，氛围压抑肃杀.
This is a pure environment/background art with NO characters, NO people,
NO human figures, NO silhouettes. Show only the location, architecture,
objects, lighting, and atmosphere.
...
```

参考图输入: 3 张角色三视图（仅做风格参考，label 标注 "DO NOT draw this character"）

**输出**: 3 张纯环境空镜 PNG

```
scenes/scene_u1_s1_v2.png  ← 陆氏集团大厅（空旷大理石大厅）
scenes/scene_u1_s2_v2.png  ← 总裁办公室门口（胡桃木桌+落地窗）
scenes/scene_u1_s3_v2.png  ← 总裁办公桌前（桌面特写+城市天际线）
```

[大厅空镜] [办公室空镜] [办公桌空镜]

**耗时**: ~87s

---

## Stage 4: storyboard_grids (4x4 宫格分镜图)

### Step A: LLM 生成 16 个分镜 prompt

**调用**: Qwen 3.5-plus + GRID_SHOTS_SYSTEM_PROMPT

**输出**: `grids/grid_u1_shots.json`

```json
{
  "style_tags": ["anime style", "manga aesthetic", "dramatic lighting", "emotional tension", "9:16 vertical"],
  "shots": [
    {"shot_number": 1, "prompt_text": "ECU, worn black high heels clicking on marble floor, blurred office background, anxious atmosphere, anime style, no timecode, no subtitles"},
    {"shot_number": 2, "prompt_text": "CU, pale fingers gripping brown leather folder tightly, knuckles white, trembling hands, dramatic shadows, manga style, no timecode, no subtitles"},
    {"shot_number": 3, "prompt_text": "MS, Su Niannian walking fast through grand hall, head bowed, messy black hair, worn shirt, anime style, no timecode, no subtitles"},
    {"shot_number": 4, "prompt_text": "MCU, Su Niannian stopping before cold metal door, taking deep breath, eyes red, tense mood, manga style, no timecode, no subtitles"},
    "...共 16 个"
  ]
}
```

### Step B: Gemini 生成宫格图

**调用**: Gemini 3.1 Flash (`image_size="4K"`)

参考图输入: 3 张角色三视图 + 3 张场景空镜（共 6 张）

Gemini prompt（精简版）：
```
You are generating a single 4x4 grid artwork (4 rows × 4 columns = 16 panels).
The overall image MUST be in 9:16 PORTRAIT aspect ratio (taller than wide).
Each panel MUST also be 9:16 portrait. Panels MUST be clearly separated.

【REFERENCE IMAGES】
- Image 1: Character "苏念念" (art style + appearance reference)
- Image 2: Character "陆景琛" (art style + appearance reference)
- ...

【PANELS — draw each panel exactly as described】
Panel 1: worn black high heels clicking on marble floor, blurred office background...
Panel 2: pale fingers gripping brown leather folder tightly, knuckles white...
...共 16 个 Panel...

【RULES】
- Keep character appearance absolutely consistent across all 16 panels.
- Sequential storytelling: panels flow left-to-right, top-to-bottom.
- anime style, manga aesthetic, dramatic lighting...
- ZERO TEXT on the image: no labels, no letters, no speech bubbles.

Generate the 4×4 grid image now. 16 clearly separated panels. MUST be 9:16 PORTRAIT.
```

**输出**: `grids/grid_u1_v1.png` (3072x5504, 9:16 竖屏 4K)

[4×4 宫格分镜图 — 16 个竖屏面板，无文字标签]

**耗时**: ~120s

---

## Stage 5: video_prompts (切图 + 分镜指令)

### Step A: PIL 智能切割

- 自动检测分隔线（亮度 > 200 的连续像素区域）
- 去掉白色边框 → crop 16 个面板 → LANCZOS resize 到统一 9:16 尺寸

**输出**: `frames/u1/frame_01.png` ~ `frame_16.png` (每帧 ~774x1376)

### Step B: LLM 生成 16 段视频指令

**调用**: Qwen 3.5-plus + VIDEO_SEGMENTS_SYSTEM_PROMPT

**LLM 输入**: 剧本 script + 角色列表 + 场景参考 + 16 个 shot 描述

**输出**: `grids/video_segments_u1.json`

```json
{
  "video_segments": [
    {
      "segment_number": 1,
      "start_frame": 1,
      "is_memory": false,
      "scene_description": "陆氏集团大厅，苏念念穿着磨损高跟鞋行走的特写。",
      "camera_type": "特写/极特写",
      "camera_movement": "tilt_up",
      "emotion": "紧张/压抑",
      "narration_text": "曾经高傲的苏家大小姐如今沦为笑柄，只为给母亲凑齐医药费，她不得不低头忍耐。",
      "characters_in_frame": ["char_001"],
      "scene_ref_id": "u1_s1",
      "estimated_duration": 5,
      "video_prompt": "镜头从大理石地面上敲击的磨损高跟鞋低角度特写开始，缓慢向上倾斜，聚焦到苏念念因用力而指节发白的双手。"
    },
    {
      "segment_number": 2,
      "start_frame": 2,
      "narration_text": "",
      "camera_type": "中景",
      "camera_movement": "pull_back",
      "video_prompt": "画面从手部特写缓缓向后拉远，展现她瘦弱的背影穿过公司走廊。",
      "estimated_duration": 4
    },
    "...共 16 段..."
  ]
}
```

**耗时**: ~64s

---

## Stage 6: narration_tts (旁白语音)

### Step 1: LLM 选择旁白音色

**调用**: Qwen 3.5-plus + NARRATION_VOICE_MATCH_SYSTEM_PROMPT

**输入**: 剧本标题、情感基调、冲突、旁白摘要、角色信息 + Qwen 可用音色列表

**输出**: `narration_voice.json`

```json
{
  "voice_id": "Serena",
  "reason": "温柔细腻的女声适合都市言情的旁白，表面柔和实则暗藏张力",
  "tts_instructions": "用温柔却克制的女声，仿佛在耳边低声讲述一个心碎的秘密。叙述苏念念的隐忍时声音轻柔沉重，提及陆景琛时语调微微收紧带着不安。冲突段落保持表面冷静但气息加速，悬念处用极轻的叹息感停顿，勾人心弦。"
}
```

### Step 2: Qwen TTS 逐段生成

**调用**: Qwen3-TTS-Instruct-Flash

对 16 段中有 `narration_text` 的段生成旁白音频，其余段无旁白。

| 段 | 旁白文字 | TTS 时长 | 最终时长 |
|----|---------|---------|---------|
| 段1 | "曾经高傲的苏家大小姐如今沦为笑柄..." | 7.0s | 8s |
| 段3 | "三年前的雨夜她狠心抛弃了他..." | 7.4s | 8s |
| 段6 | "他质问当初誓言，嘲讽她如今处境..." | 8.0s | 8s |
| 段9 | "这哪里是招聘分明是变相囚禁..." | 7.7s | 8s |
| 其他12段 | (无旁白) | — | 3-4s |

时长校准公式: `final_duration = max(estimated_duration, ceil(tts_duration), 3)`

**输出**: 4 个 WAV 文件

```
audio/u1_seg01_narration.wav  (7.0s)
audio/u1_seg03_narration.wav  (7.4s)
audio/u1_seg06_narration.wav  (8.0s)
audio/u1_seg09_narration.wav  (7.7s)
```

**耗时**: ~27s

---

## Stage 7: video_gen (视频生成)

**调用**: Kling V3 image2video (串行, sound=on, 9:16)

每段视频用对应帧作为首帧，`sound="on"` 获取环境音效，无 lip-sync。

| 段 | 首帧 | 时长 | sound | 内容 |
|----|------|------|-------|------|
| 段1 | frame_01.png | 8s | on | 高跟鞋特写 → 手部特写 |
| 段2 | frame_02.png | 4s | on | 走廊中景 |
| 段3 | frame_03.png | 8s | on | 办公室大门打开 |
| ... | ... | ... | ... | ... |
| 段16 | frame_16.png | 4s | on | 陆景琛睁眼特写 |

Kling API 参数示例（段1）：
```json
{
  "model_name": "kling-v3",
  "image": "base64(frame_01.png)",
  "prompt": "镜头从大理石地面上敲击的磨损高跟鞋低角度特写开始，缓慢向上倾斜...",
  "mode": "std",
  "duration": "8",
  "aspect_ratio": "9:16",
  "sound": "on",
  "subject_reference": [{"image": "base64(charref_char_001.png)"}]
}
```

**输出**: 16 个 MP4 文件

```
videos/u1_seg01_final.mp4  (8.0s, ~5MB)
videos/u1_seg02_final.mp4  (4.0s, ~3MB)
...
videos/u1_seg16_final.mp4  (4.0s, ~3MB)
```

**耗时**: ~35 min (串行, 每段 ~2 min)

---

## Stage 8: subtitle_burn (字幕压制)

**调用**: FFmpeg drawtext

仅对有 `narration_text` 的段压制字幕（白色旁白文字，无角色名）。

字幕处理逻辑：
- 每行最多 20 个中文字，在标点处优先断行
- 超过 2 行时拆成 2 段，各显示一半时长

FFmpeg filter 示例（段6，38 字 → 2 段）：
```
drawtext=fontfile='PingFang.ttc':fontsize=28:fontcolor=white:borderw=2:bordercolor=black:
  x=(w-text_w)/2:y=h-th-60:text='他质问当初誓言，嘲讽她如今处境，':enable='between(t,0.0,4.0)',
drawtext=fontfile='PingFang.ttc':fontsize=28:fontcolor=white:borderw=2:bordercolor=black:
  x=(w-text_w)/2:y=h-th-60:text='更霸道宣布她是专属助理，二十四小时随叫随到。':enable='between(t,4.0,8.0)'
```

**输出**: 4 个带字幕的 MP4

```
videos/u1_seg01_subtitled.mp4
videos/u1_seg03_subtitled.mp4
videos/u1_seg06_subtitled.mp4
videos/u1_seg09_subtitled.mp4
```

**耗时**: ~4s

---

## Stage 9: assembly (组装)

### Step A: 统一帧率

所有 16 段视频统一为 `720x1280 @30fps`（9:16 竖屏），带字幕的优先。

### Step B: 拼接

FFmpeg concat demuxer 硬切拼接 → `u1_concat.mp4` (76.6s)

### Step C: 旁白音轨

将 4 段 TTS 音频按时间轴偏移拼成一条完整旁白音轨：

```
时间轴: 0s -------- 8s ---- 12s ------- 20s ... 40s ------- 48s ...
旁白:   [段1 TTS]   [静音]  [段3 TTS]   ...   [段9 TTS]   [静音] ...
```

通过 `seg_to_unified` 映射确保时间偏移精确对齐。

### Step D: BGM 生成

**调用**: ElevenLabs Music API

LLM 生成纯器乐 prompt：
```
Dark, suspenseful instrumental loop featuring pulsating low strings,
dissonant piano stabs, and a ticking clock rhythm...
No vocals, choir, or humming.
```

BGM 预处理: `compand + dynaudnorm` (3s 窗口, maxgain=25dB) 拉平首尾弱音量

### Step E: 三层音频混合

```
Layer 1: 视频原音 (sound=on 环境音效) → -35dB (极低, 背景氛围)
Layer 2: 旁白 TTS                     → mean=-15dB (主导, dB 精确对标)
Layer 3: BGM (纯器乐)                  → mean=-28dB (衬底, 防 clipping)
                                           ↓
                              amix=inputs=3 → 最终音频
                                           ↓
                              + 视频画面 → u1_output.mp4
```

BGM 淡出: 最后 1 秒 (无淡入)

**输出**: `videos/u1_output.mp4`

**耗时**: ~14s

---

## Stage 10: quality_gate (质量检测)

检查项:

| 检查 | 结果 |
|------|------|
| BGM 可听性 (volume diff) | ✓ (diff=2.9dB) |
| 视频完整性 (16/16 段) | ✓ |
| TTS 覆盖率 (4/4 旁白段) | ✓ |

**结果**: PASSED

**耗时**: ~2s

---

## 最终输出

```
e2e_output/narration_v2_test/videos/u1_output.mp4
```

| 属性 | 值 |
|------|-----|
| 时长 | 76.6s |
| 大小 | 31.3MB |
| 分辨率 | 720x1280 |
| 帧率 | 30fps |
| 画面方向 | 9:16 竖屏 |
| 音频 | 环境音效 + Serena 女声旁白 + 纯器乐 BGM |
| 字幕 | 4 段旁白 (自动折行 + 分时显示) |

---

## 目录结构

```
e2e_output/narration_v2_test/
├── storyboard.json                 # Stage 1: LLM 分镜
├── narration_voice.json            # Stage 6: 旁白音色配置
├── candidates.json                 # 资产版本管理
├── characters/
│   ├── charref_char_001_v1_0.png   # Stage 2: 苏念念三视图
│   ├── charref_char_002_v1_0.png   # 陆景琛三视图
│   └── charref_char_003_v1_0.png   # 王经理三视图
├── scenes/
│   ├── scene_u1_s1_v2.png          # Stage 3: 大厅空镜
│   ├── scene_u1_s2_v2.png          # 办公室空镜
│   └── scene_u1_s3_v2.png          # 办公桌空镜
├── grids/
│   ├── grid_u1_shots.json          # Stage 4: 16 shot prompts
│   ├── grid_u1_v1.png              # Stage 4: 4K 宫格图 (3072x5504)
│   └── video_segments_u1.json      # Stage 5: 16 段视频指令
├── frames/
│   └── u1/
│       ├── frame_01.png            # Stage 5: 切出的 16 帧
│       └── ...frame_16.png
├── audio/
│   ├── u1_seg01_narration.wav      # Stage 6: 旁白 TTS
│   ├── u1_seg03_narration.wav
│   ├── u1_seg06_narration.wav
│   ├── u1_seg09_narration.wav
│   ├── u1_narration_track.mp3      # Stage 9: 旁白时间轴音轨
│   ├── u1_bgm.mp3                  # Stage 9: ElevenLabs BGM
│   └── u1_bgm_processed.mp3       # Stage 9: BGM 预处理后
└── videos/
    ├── u1_seg01_final.mp4          # Stage 7: Kling V3 视频
    ├── u1_seg01_subtitled.mp4      # Stage 8: 带字幕
    ├── ...
    ├── u1_seg16_final.mp4
    ├── u1_unified_00.mp4           # Stage 9: 统一帧率
    ├── ...
    ├── u1_concat.mp4               # Stage 9: 拼接
    └── u1_output.mp4               # 最终输出
```

---

## 耗时分布

| Stage | 耗时 | 占比 |
|-------|------|------|
| 1. storyboard | 37s | 1.5% |
| 2. char_refs | 72s | 3% |
| 3. scene_refs | 87s | 3.5% |
| 4. storyboard_grids | 120s | 5% |
| 5. video_prompts | 64s | 2.5% |
| 6. narration_tts | 27s | 1% |
| **7. video_gen** | **~2100s** | **84%** |
| 8. subtitle_burn | 4s | <1% |
| 9. assembly | 14s | <1% |
| 10. quality_gate | 2s | <1% |
| **总计** | **~42 min** | |

视频生成（Stage 7）占总耗时 84%，是串行执行 16 段 Kling V3 的瓶颈。
