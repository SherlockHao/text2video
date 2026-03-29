# 导演规划 (director_plan) 改动前后对比

> 以旁白漫剧 V2《落魄千金》为例，展示新增 director_plan stage 前后，下游 stage 收到的信息差异。

---

## 改动概述

在 Stage 1 (storyboard) 和 Stage 2 (char_refs) 之间新增 **Stage 1.5: director_plan**。

它做两件事：
1. **全局 Visual Bible**（英文）— 跨所有 unit 统一的视觉规范
2. **单元导演规划**（中文）— 每个 unit 的导演构思

---

## Stage 1 输出对比

### Before（仅 storyboard）

Stage 1 输出 `storyboard.json`，包含故事信息但**无视觉规划**：

```json
{
  "units": [{
    "unit_number": 1,
    "title": "落魄千金闯入狼穴",
    "core_conflict": "破产千金为母治病忍辱入职...",
    "emotion_tone": "悬疑紧张",
    "key_scenes": [...],
    "script": [
      {"type": "action", "content": "苏念念低着头快步穿过大厅..."},
      {"type": "narration", "content": "昔日苏家大小姐如今沦为抵债秘书..."},
      ...
    ]
  }],
  "character_profiles": [
    {"char_id": "char_001", "name": "苏念念", "appearance_prompt": "24岁女性，身形纤细..."},
    {"char_id": "char_002", "name": "陆景琛", "appearance_prompt": "27岁男性，身材高大..."},
    ...
  ]
}
```

**缺失的信息：** 无色调规划、无构图策略、无角色拍摄方式、无情感节奏曲线、无视觉符号系统

### After（storyboard + director_plan）

Stage 1.5 新增输出 `director_plan.json`，包含两层信息：

#### Layer 1: 全局 Visual Bible（英文，供 T2I 直接使用）

```json
{
  "color_palette": {
    "primary": "cold steel grey with deep charcoal undertones to reflect the corporate oppression and suspense",
    "accent": "muted crimson red used sparingly for emotional pain or moments of intense threat",
    "memory_flashback": "sepia-toned with heavy vignette and soft focus to denote lost warmth and past trauma",
    "climax": "high-contrast chiaroscuro with sharp blue rim lighting against deep black shadows to heighten tension"
  },
  "art_direction": "Modern dramatic anime style with cel-shaded textures, heavy use of chiaroscuro lighting, cinematic widescreen framing, sharp angular character designs, and a moody atmosphere emphasizing psychological suspense and power imbalance.",
  "recurring_motifs": [
    {
      "symbol": "Worn high heels",
      "meaning": "Su Niannian's fallen status and physical exhaustion",
      "visual_treatment": "Close-up shots focusing on scuffed leather and cracked heels against pristine marble floors"
    },
    {
      "symbol": "Platinum cufflinks",
      "meaning": "Lu Jingchen's cold wealth and unyielding control",
      "visual_treatment": "Specular highlights catching cold light, often framed in extreme close-ups during threats"
    },
    {
      "symbol": "Glass partitions",
      "meaning": "The barrier between the powerful and the vulnerable, transparency without access",
      "visual_treatment": "Rendered with slight distortion and reflections that trap characters visually within the frame"
    }
  ],
  "character_cinematography": [
    {
      "char_id": "char_001",
      "name": "Su Niannian",
      "signature_framing": "High-angle shots to emphasize vulnerability and smallness, often partially obscured by shadows or foreground objects",
      "color_association": "pale beige and desaturated black"
    },
    {
      "char_id": "char_002",
      "name": "Lu Jingchen",
      "signature_framing": "Low-angle shots to dominate the frame, silhouetted against bright windows or lit from below to sharpen facial angles",
      "color_association": "deep charcoal grey and icy blue"
    },
    {
      "char_id": "char_003",
      "name": "Manager Wang",
      "signature_framing": "Mid-shots with slightly tilted Dutch angles to convey unease and subservience, often placed in the background",
      "color_association": "dull navy and muted white"
    }
  ],
  "transition_style": "Hard cuts with quick zooms for tension spikes, slow dissolves into darkness for emotional weight, and match cuts on eye lines to connect predator and prey",
  "lighting_base": "Cool, directional overhead fluorescent lighting casting harsh downward shadows, supplemented by narrow beams of natural light creating high-contrast pockets of isolation"
}
```

#### Layer 2: 单元导演规划（中文，供后续 LLM stage 参考）

```json
{
  "unit_number": 1,
  "emotional_curve": "压抑卑微（入场）→震惊凝固（重逢）→恐惧递进（逼近）→短暂喘息（公事公办被拒）→绝望囚禁（接受安排）→寒意彻骨（结尾低语）",
  "camera_strategy": "开场使用手持跟拍与高角度俯拍强调苏念念的渺小与不安；重逢瞬间切换至静态特写捕捉微表情；陆景琛逼近时采用低角度仰拍配合缓慢推镜头（Dolly In）制造压迫感；结尾利用玻璃反射与极近特写强化心理惊悚。",
  "key_compositions": [
    {
      "panels": "1-2",
      "technique": "局部特写递进：从磨损的高跟鞋特写切入，上移至泛白指节，最后拉至中远景展示人物在空旷大厅中的孤立无援，建立'落魄'基调。"
    },
    {
      "panels": "3-4",
      "technique": "视线匹配剪辑（Match Cut on Eye Line）：苏念念推门的主观视角直接切至陆景琛抬头的特写，中间无过渡，制造'血液凝固'的视觉冲击。"
    },
    {
      "panels": "5-6",
      "technique": "权力反差构图：陆景琛起身逼近时，镜头置于地面低角度，使其身形占据画面2/3，苏念念被挤压至画面边缘，体现绝对掌控。"
    },
    {
      "panels": "11-12",
      "technique": "玻璃隔断隐喻：透过带有轻微畸变的玻璃拍摄苏念念转身的背影，陆景琛的身影倒映在玻璃上如同幽灵般笼罩着她。"
    }
  ],
  "color_shifts": "冷钢灰开场（压抑）→ 瞬间去色处理（震惊时刻）→ 深炭灰与阴影主导（对峙期）→ 袖扣处点缀 muted crimson（威胁信号）→ 结尾回归高对比度冷蓝轮廓光（悬疑收尾）",
  "pacing_notes": "帧1-3节奏缓慢沉重，强调脚步声与环境音；帧4-5突然静止，心跳声放大；帧6-8节奏加速，配合脚步逼近的鼓点；帧9-10王经理介入时节奏稍乱；帧11-12极度放慢，仅保留低语声与环境底噪，制造窒息感。",
  "special_treatments": [
    {
      "panels": "4",
      "treatment": "时间停滞效果：背景虚化至全黑，仅保留两人面部高光，色彩瞬间抽离为黑白，模拟'血液凝固'的心理感受。"
    },
    {
      "panels": "12",
      "treatment": "闪回叠加：画面边缘叠化出'雨夜决绝背影'的Sepia色调模糊影像，与现实冷蓝光形成冷暖冲突。"
    }
  ]
}
```

---

## 下游 Stage 收到的信息变化

### Stage 2: char_refs（角色三视图）

**Before:**
```
prompt = "杰作, 4K, 动漫风格, 角色设定图, 白色背景, 三视图,
女性角色, 24岁女性，身形纤细瘦弱，皮肤苍白，黑色长直发...
全身立绘, 表情自然, 姿态端正, 无文字, 无水印, 单人"
```

**After（新增角色色调关联）:**
```
prompt = "杰作, 4K, 动漫风格, 角色设定图, 白色背景, 三视图,
女性角色, 24岁女性，身形纤细瘦弱，皮肤苍白，黑色长直发...
全身立绘, 表情自然, 姿态端正, 无文字, 无水印, 单人,
pale beige and desaturated black 色调倾向"     ← 来自 Visual Bible
```

### Stage 3: scene_refs（场景空镜图）

**Before:**
```
Generate an anime background scene image — EMPTY ENVIRONMENT ONLY.
Location: 陆氏集团大厅.
Environment description: 挑高十米的宽敞企业大厅...
No text, no watermark, no characters.
```

**After（新增全局美术方向 + 色调）:**
```
Generate an anime background scene image — EMPTY ENVIRONMENT ONLY.
Location: 陆氏集团大厅.
Environment description: 挑高十米的宽敞企业大厅...
No text, no watermark, no characters.
Visual style: Modern dramatic anime style with cel-shaded textures,
heavy use of chiaroscuro lighting, cinematic widescreen framing...     ← 来自 Visual Bible
Color palette: cold steel grey with deep charcoal undertones...        ← 来自 Visual Bible
```

### Stage 4 Step A: GRID_SHOTS LLM（16 shot prompts）

**Before（LLM 输入）:**
```
【剧本单元 1】：落魄千金闯入狼穴
情感底色：悬疑紧张
核心冲突：破产千金为母治病忍辱入职...
【完整剧本】：[action/narration...]
【角色外貌参考】：[...]
请为每帧生成16段视频分镜指令。
```

**After（新增导演规划）:**
```
【剧本单元 1】：落魄千金闯入狼穴
情感底色：悬疑紧张
核心冲突：破产千金为母治病忍辱入职...
【完整剧本】：[action/narration...]
【角色外貌参考】：[...]

【导演规划】：                                                         ← 新增
{
  "emotional_curve": "压抑卑微→震惊凝固→恐惧递进→...",
  "camera_strategy": "开场使用手持跟拍与高角度俯拍...",
  "key_compositions": [
    {"panels": "1-2", "technique": "局部特写递进：从磨损的高跟鞋..."},
    {"panels": "3-4", "technique": "视线匹配剪辑..."},
    {"panels": "5-6", "technique": "权力反差构图..."},
    ...
  ],
  "color_shifts": "冷钢灰开场→瞬间去色→深炭灰与阴影...",
  "pacing_notes": "帧1-3节奏缓慢沉重..."
}

请为每帧生成16段视频分镜指令。
```

### Stage 4 Step B: GRID_IMAGE Gemini（宫格图）

**Before（STORY CONTEXT 部分）:**
```
【STORY CONTEXT】
Title: 落魄千金闯入狼穴
Emotion: 悬疑紧张
Conflict: 破产千金为母治病忍辱入职...
Scene grouping:
  - Panels 1, 2, 3: Corporate Lobby
  - Panels 5-13, 16: Executive Office
  - Panels 14, 15: Rainy Street [FLASHBACK] — USE DESATURATED/BLUE TONES
```

**After（新增美术方向 + 色调）:**
```
【STORY CONTEXT】
Title: 落魄千金闯入狼穴
Emotion: 悬疑紧张
Conflict: 破产千金为母治病忍辱入职...
Art direction: Modern dramatic anime style with cel-shaded textures,  ← 来自 Visual Bible
heavy use of chiaroscuro lighting, cinematic widescreen framing...
Color palette: cold steel grey with deep charcoal undertones...        ← 来自 Visual Bible
Scene grouping:
  - Panels 1, 2, 3: Corporate Lobby
  - Panels 5-13, 16: Executive Office
  - Panels 14, 15: Rainy Street [FLASHBACK] — USE DESATURATED/BLUE TONES
```

---

## 新增信息总结

| 新增信息 | 来源 | 消费方 | 作用 |
|---------|------|--------|------|
| color_palette (4种色调) | Visual Bible | scene_refs, storyboard_grids | 全局色调统一 |
| art_direction | Visual Bible | scene_refs, storyboard_grids | 全局美术风格 |
| recurring_motifs (3个) | Visual Bible | (人工参考) | 视觉符号系统 |
| character_cinematography | Visual Bible | char_refs | 角色色调关联 |
| lighting_base | Visual Bible | (人工参考) | 光影基准 |
| emotional_curve | Unit Plan | GRID_SHOTS LLM | 情感节奏指导 |
| camera_strategy | Unit Plan | GRID_SHOTS LLM | 镜头策略指导 |
| key_compositions (4组) | Unit Plan | GRID_SHOTS LLM | 具体构图技法 |
| color_shifts | Unit Plan | GRID_SHOTS LLM | 色调变化规划 |
| pacing_notes | Unit Plan | GRID_SHOTS LLM | 节奏备注 |
| special_treatments | Unit Plan | GRID_SHOTS LLM | 特殊效果（闪回等） |

---

## 耗时影响

| 步骤 | 耗时 |
|------|------|
| Visual Bible (1次LLM) | ~15s |
| Unit Plan (1次LLM × N units) | ~17s × N |
| **总新增** | **~33s** (1个unit) |
| 占全流程 (~42min) | **< 1.5%** |
