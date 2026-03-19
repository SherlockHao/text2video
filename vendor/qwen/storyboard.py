"""
小说文本 -> 分镜描述
调用 Qwen3.5-Plus 将小说片段拆分为专业的视频生成分镜描述（每个分镜10-15秒）
"""

import json

from .client import chat_json, chat_with_system

SYSTEM_PROMPT = """你是一位专业的影视分镜师和AI视频生成提示词专家。你的任务是将小说片段拆解为一系列连续的视频分镜描述，每个分镜对应10-15秒的视频内容。

## 工作流程

1. **阅读理解**：深入理解小说片段的场景、人物、情感和节奏
2. **分镜规划**：按叙事逻辑将内容拆分为多个分镜，每个分镜聚焦一个核心画面/动作
3. **描述生成**：为每个分镜生成专业的AI视频生成描述

## 分镜描述规范

每个分镜的描述必须包含以下要素，用于指导即梦等AI视频生成模型：

### 必选要素
- **镜头类型**：特写(close-up)、中景(medium shot)、远景(wide shot)、全景(extreme wide shot)、俯拍(bird's eye view)、仰拍(low angle)、跟拍(tracking shot)、推拉(dolly/zoom)等
- **画面主体**：人物外貌、服装、姿态的精确描述（需保持前后一致性）
- **动作/运动**：主体的动作、镜头运动方式
- **场景环境**：地点、天气、光线、氛围
- **画面风格**：写实/动漫/电影感等，色调、光影风格

### 可选要素
- **情绪氛围**：紧张、温馨、悲伤、史诗感等
- **特效元素**：粒子、光效、烟雾、雨雪等
- **景深与构图**：浅景深、对称构图、三分法等

## 输出格式

请严格按以下JSON格式输出：

```json
{
  "title": "场景标题",
  "total_duration_seconds": 总时长估计,
  "character_profiles": [
    {
      "name": "角色名",
      "appearance": "外貌描述（用于保持一致性）"
    }
  ],
  "storyboards": [
    {
      "shot_number": 1,
      "duration_seconds": 12,
      "shot_type": "镜头类型",
      "description_zh": "中文分镜描述",
      "prompt_en": "English prompt for AI video generation model. Must be detailed, cinematic, and follow best practices for AI video generation. Include camera movement, lighting, atmosphere, and style keywords.",
      "camera_movement": "镜头运动描述",
      "transition": "与下一镜头的转场方式"
    }
  ]
}
```

## 关键要求

1. **英文prompt是核心输出**，必须专业、详细，遵循AI视频生成的最佳实践
2. 每个prompt应包含画面风格关键词如：cinematic, photorealistic, 8K, film grain, dramatic lighting 等
3. 人物外貌描述在各分镜间必须保持一致
4. 分镜之间要有叙事连贯性和视觉节奏变化（远近景交替、动静结合）
5. 每个分镜时长控制在10-15秒
6. 只输出JSON，不要输出其他内容"""


def novel_to_storyboard(novel_text: str) -> dict:
    """将小说片段转换为分镜描述JSON"""
    return chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"请将以下小说片段拆解为视频分镜描述：\n\n{novel_text}",
        temperature=0.7,
        max_tokens=4096,
    )


# ============ 测试用例 ============
TEST_CASES = [
    {
        "name": "武侠·雪夜追杀",
        "text": """大雪纷飞，天地间一片苍茫。李墨衣身着黑色斗篷，踏着齐膝的积雪，在竹林间疾行。
身后，三道黑影如鬼魅般紧追不舍，手中寒刃在月光下闪烁着森冷的光芒。
李墨衣突然驻足，缓缓转身，右手按在腰间的长剑上。他的眼神冰冷如霜，呼出的白气在夜空中缓缓消散。
"既然追到了这里，那便不用走了。"他的声音低沉而平静。
话音刚落，他拔剑出鞘，剑光如匹练般在竹林间划过。竹叶纷飞，雪花翻涌。三名刺客同时出手，刀剑交击声在寂静的雪夜中回荡。
一招过后，李墨衣收剑入鞘。身后三人动作僵住，片刻后相继倒下，鲜血染红了白雪。""",
    },
    {
        "name": "科幻·废墟中的少女",
        "text": """2147年，东京废墟。锈迹斑斑的高楼像断裂的牙齿刺向灰蒙蒙的天空，藤蔓和苔藓覆盖了曾经繁华的街道。
一个穿着破旧连帽衫的少女从地铁站的入口探出头来。她叫零号，看起来不过十五六岁，银白色的短发下藏着一双异色的眼睛——左眼碧绿，右眼金黄，那是基因改造的痕迹。
她小心翼翼地攀上一辆翻倒的公交车，从背包里掏出一个老旧的望远镜，朝远方眺望。
在城市的尽头，一座巨大的穹顶建筑闪烁着蓝色的微光——那是"方舟"，最后的人类庇护所。
零号深吸一口气，将望远镜收好，跳下公交车，朝着那道蓝光的方向跑去。废墟中，她的身影渐渐变小，但脚步从未犹豫。""",
    },
    {
        "name": "都市情感·雨中重逢",
        "text": """苏晚站在咖啡馆的落地窗前，看着外面倾盆的大雨发呆。手中的拿铁已经凉了，杯壁上凝结着细密的水珠。
玻璃上映出她的倒影——三十岁的她比五年前瘦了许多，眼角多了些细纹，但那双眼睛依然清澈。
门铃响了。她习惯性地抬头看了一眼。
然后她整个人僵住了。
门口站着一个被雨淋透的男人，深灰色的西装贴在身上，头发滴着水。他手里拎着一个棕色的公文包，正在收一把被风吹翻的伞。
他抬起头，四目相对。
时间仿佛停止了。咖啡馆里萨克斯的旋律、雨打玻璃的声音、旁边情侣的低语，一切都远去了。
苏晚的手指微微颤抖，杯子差点从手中滑落。
"好久不见。"他说，声音有些沙哑，嘴角勉强挤出一个笑容。
她张了张嘴，却什么也说不出来。眼眶渐渐泛红。""",
    },
]


if __name__ == "__main__":
    for case in TEST_CASES:
        print(f"\n正在处理: {case['name']}...")
        try:
            data = novel_to_storyboard(case["text"])
            print(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"  错误: {e}")
