# 宫格图 Gemini Prompt 改动对比

> 以旁白漫剧 V2《落魄千金》Unit 1 为例

---

## 改动前（无 STORY CONTEXT）

```
You are generating a single 4x4 grid artwork (4 rows × 4 columns = 16 panels). The overall image MUST be in 9:16 PORTRAIT aspect ratio (taller than wide). Each panel MUST also be 9:16 portrait. Panels MUST be clearly separated by visible borders.

【REFERENCE IMAGES】
- Image 1: Character "苏念念" (art style + appearance reference)
- Image 2: Character "陆景琛" (art style + appearance reference)
- Image 3: Character "王经理" (art style + appearance reference)
- Image 4: Scene reference: 陆氏集团大厅
- Image 5: Scene reference: 总裁办公室门口
- Image 6: Scene reference: 总裁办公桌前

【PANELS — draw each panel exactly as described】
Panel 1: worn black high heels clicking on marble floor, blurred office background, anxious atmosphere, anime style, no timecode, no subtitles
Panel 2: pale fingers gripping brown leather folder tightly, knuckles white, trembling hands, dramatic shadows, manga style, no timecode, no subtitles
Panel 3: Su Niannian walking fast through grand hall, head bowed, messy black hair, worn shirt, mocking whispers visualized, anime style, no timecode, no subtitles
Panel 4: Su Niannian stopping before cold metal door, taking deep breath, eyes red with suppressed tears, tense mood, manga style, no timecode, no subtitles
Panel 5: door opening to reveal dark office silhouette, Lu Jingchen sitting in shadow, sudden shock, high contrast lighting, anime style, no timecode, no subtitles
Panel 6: Lu Jingchen looking up slowly from documents, cold piercing eyes, sharp jawline, grey suit, intense gaze, manga style, no timecode, no subtitles
Panel 7: Lu Jingchen standing up and walking around desk, tall imposing figure, silent approach, looming threat, dramatic perspective, anime style, no timecode, no subtitles
Panel 8: Su Niannian biting lip hard, holding back tears, facing towering man, expression of humiliation and fear, emotional close-up, manga style, no timecode, no subtitles
Panel 9: Lu Jingchen smirking cruelly, corner of mouth raised, cold laughter, platinum cufflinks visible, sinister vibe, anime style, no timecode, no subtitles
Panel 10: Lu Jingchen sitting back lazily in chair, pointing finger commandingly, declaring twenty-four hour availability, dominant posture, manga style, no timecode, no subtitles
Panel 11: Manager Wang entering with files, eyes shifting nervously between two characters, sweating, gold-rimmed glasses, awkward tension, anime style, no timecode, no subtitles
Panel 12: Su Niannian turning away reluctantly, walking towards heavy side door, shoulders slumped, feeling trapped, gloomy corridor, manga style, no timecode, no subtitles
Panel 13: Lu Jingchen leaning back with closed eyes, fingers touching silver cufflinks, whispering softly, dangerous calm, shadowy face, anime style, no timecode, no subtitles
Panel 14: Su Niannian's hand shaking on door handle, hesitation, tear falling on cheek, extreme emotional distress, detailed anime art, no timecode, no subtitles
Panel 15: Flashback, ECU, rainy night silhouette of girl leaving, blurred water droplets, memory fragment, sorrowful blue tone, manga style, no timecode, no subtitles
Panel 16: Lu Jingchen opening eyes suddenly, dark possessive glare, vowing never to let her escape again, cliffhanger ending, intense anime style, no timecode, no subtitles

【RULES】
- Keep character appearance absolutely consistent across all 16 panels (match reference images).
- Sequential storytelling: panels flow left-to-right, top-to-bottom.
- anime style, manga aesthetic, dramatic lighting, emotional tension, 9:16 vertical
- ZERO TEXT on the image: no labels, no letters, no numbers, no captions, no speech bubbles, no annotations of any kind. Pure artwork only.

Generate the 4×4 grid image now. 16 clearly separated panels. MUST be 9:16 PORTRAIT (taller than wide). No text anywhere.
```

**统计: 565 词, 35 行**

---

## 改动后（有 STORY CONTEXT + scene_group）

```
You are generating a single 4x4 grid artwork (4 rows × 4 columns = 16 panels). The overall image MUST be in 9:16 PORTRAIT aspect ratio (taller than wide). Each panel MUST also be 9:16 portrait. Panels MUST be clearly separated by visible borders.

【REFERENCE IMAGES】
- Image 1: Character "苏念念" (art style + appearance reference)
- Image 2: Character "陆景琛" (art style + appearance reference)
- Image 3: Character "王经理" (art style + appearance reference)
- Image 4: Scene reference: 陆氏集团大厅
- Image 5: Scene reference: 总裁办公室门口
- Image 6: Scene reference: 总裁办公桌前

【STORY CONTEXT】
Title: 落魄千金闯入狼穴
Emotion: 悬疑紧张
Conflict: 破产千金为母治病忍辱入职，却直面曾被自己抛弃的复仇总裁。
Scene grouping (panels sharing the same location should have consistent backgrounds):
  - Panels 1, 2, 3: Corporate Lobby
  - Panels 4: Executive Office Entrance
  - Panels 5, 6, 7, 8, 9, 10, 11, 12, 13, 16: Executive Office
  - Panels 14, 15: Rainy Street [FLASHBACK] — USE DESATURATED/BLUE TONES

【PANELS — draw each panel exactly as described】
Panel 1: worn black high heels striking cold marble floor, dust particles dancing in light, suspenseful atmosphere, anime style, no timecode, no subtitles
Panel 2: pale fingers gripping brown leather folder tightly, knuckles turning white, trembling hands, anxiety, manga style, no timecode, no subtitles
Panel 3: Su NianNian walking fast with head down, messy black hair, worn shirt, blurred mocking colleagues in background, sad atmosphere, anime style, no timecode, no subtitles
Panel 4: Su NianNian pausing before cold metal door, taking deep breath, red rimmed eyes, hesitation, dramatic shadow, manga style, no timecode, no subtitles
Panel 5: office door opening, Lu JingChen sitting in shadows behind desk, imposing silhouette, chilling air, suspense, anime style, no timecode, no subtitles
Panel 6: Lu JingChen looking up slowly, cold dark eyes piercing through documents, sharp jawline, grey suit, intense gaze, manga style, no timecode, no subtitles
Panel 7: Lu JingChen standing up and walking around desk, tall figure approaching, silent threat, Su NianNian shrinking back, tension, anime style, no timecode, no subtitles
Panel 8: Su NianNian biting lip hard, holding back tears, face pale with fear, refusing to cry, emotional pain, manga style, no timecode, no subtitles
Panel 9: Lu JingChen smirking cruelly, corner of mouth raised, cold expression, platinum cufflinks gleaming, dominance, anime style, no timecode, no subtitles
Panel 10: Manager Wang entering nervously, holding papers, eyes shifting between boss and secretary, awkward tension, office setting, manga style, no timecode, no subtitles
Panel 11: Su NianNian turning away quietly, shoulders slumped, walking towards heavy door, feeling trapped, despair, anime style, no timecode, no subtitles
Panel 12: Lu JingChen leaning back in chair, eyes closed, fingers rubbing silver cufflink, calculating mind, dark mood, manga style, no timecode, no subtitles
Panel 13: Su NianNian's hand touching door handle, shaking slightly, about to leave, sense of no escape, dramatic focus, anime style, no timecode, no subtitles
Panel 14: [FLASHBACK], rainy night street, young Su NianNian walking away decisively, back turned, heavy rain soaking clothes, sorrowful memory, manga style, no timecode, no subtitles
Panel 15: [FLASHBACK], young Lu JingChen watching her leave in rain, heartbroken expression, water dripping from hair, painful past, anime style, no timecode, no subtitles
Panel 16: Lu JingChen opening eyes suddenly, dark pupils filled with obsession and possessiveness, whispering welcome back, sinister vibe, manga style, no timecode, no subtitles

【RULES】
- Keep character appearance absolutely consistent across all 16 panels (match reference images).
- Sequential storytelling: panels flow left-to-right, top-to-bottom.
- anime style, manga aesthetic, dramatic lighting, emotional tension, 9:16 vertical
- ZERO TEXT on the image: no labels, no letters, no numbers, no captions, no speech bubbles, no annotations of any kind. Pure artwork only.

Generate the 4×4 grid image now. 16 clearly separated panels. MUST be 9:16 PORTRAIT (taller than wide). No text anywhere.
```

**统计: 623 词, 45 行 (+10%)**

---

## 差异对比

| 维度 | 改动前 | 改动后 |
|------|--------|--------|
| 总词数 | 565 | 623 (+10%) |
| 总行数 | 35 | 45 (+10 行) |
| STORY CONTEXT | 无 | Title + Emotion + Conflict |
| 场景分组 | 无 | 4 组 (Lobby / Entrance / Office / Flashback) |
| 回忆/闪回标记 | 仅 Panel 15 文本中提到 "Flashback" | Panel 14-15 显式标记 + "USE DESATURATED/BLUE TONES" |
| shots scene_group | 无此字段 | 每个 shot 标注所属场景 |
| 场景一致性指引 | 仅 "Sequential storytelling" | "panels sharing the same location should have consistent backgrounds" |

### Gemini 新增获得的信息

1. **故事类型**: "悬疑紧张" — Gemini 知道整体氛围基调
2. **核心冲突**: "破产千金 vs 复仇总裁" — Gemini 理解角色关系
3. **场景分组**:
   - Panel 1-3 → Corporate Lobby → 应画相似的大理石大厅
   - Panel 5-13, 16 → Executive Office → 应画一致的办公室
   - Panel 14-15 → Rainy Street [FLASHBACK] → 应用冷蓝色调
4. **显式闪回标记**: Panel 14-15 的 shot 文本也带 [FLASHBACK] 前缀
