"""
Qwen3-TTS-Instruct-Flash — 语音合成客户端

用法:
    from vendor.qwen.tts import qwen_tts

    # 返回音频字节 (WAV)
    audio_bytes = qwen_tts(
        text="要合成的文本",
        voice="Cherry",
        instructions="温柔的叙述风格，语速中等",
    )
"""

import requests
from .config import API_KEY

TTS_MODEL = "qwen3-tts-instruct-flash"
TTS_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

# 可用音色（已验证可用）
QWEN_VOICES = {
    # ── 女声 ──
    "Cherry":       "芊悦 — 开朗友好的年轻女性",
    "Serena":       "苏瑶 — 温柔细腻",
    "Chelsie":      "千雪 — 动漫风虚拟女友",
    "Maia":         "四月 — 知性温婉",
    "Bella":        "女性通用",
    "Momo":         "茉兔 — 俏皮活泼",
    "Vivian":       "十三 — 大胆可爱",
    # Jennifer / Katerina 不可用，已移除
    "Mia":          "女性 — 清新",
    "Stella":       "女性 — 明亮",
    "Nini":         "女性 — 甜美",
    # ── 男声 ──
    "Ethan":        "晨煦 — 温暖阳光",
    "Moon":         "月白 — 自信随性",
    "Kai":          "凯 — 舒缓ASMR",
    "Nofish":       "不吃鱼 — 设计师男声",
    "Ryan":         "男性通用",
    "Eldric Sage":  "智慧老者",
    "Vincent":      "男性 — 低沉磁性",
    "Neil":         "男性 — 温和",
    "Arthur":       "男性 — 沉稳",
    # ── 方言 ──
    "Jada":         "上海话女声",
    "Sunny":        "四川话女声",
    "Kiki":         "粤语女声",
    "Dylan":        "北京话男声",
    "Li":           "南京话男声",
    "Marcus":       "陕西话男声",
    "Eric":         "四川话男声",
    "Rocky":        "粤语男声",
}

# 情感指令模板（用于 LLM 匹配后生成 instructions）
EMOTION_INSTRUCTIONS = {
    "calm":      "平静冷淡的叙述，不带强烈感情色彩，声音沉稳",
    "happy":     "开朗愉悦的语气，声音明亮上扬，语速稍快",
    "sad":       "悲伤低沉的叙述，声音沙哑，语速缓慢，像在追忆",
    "angry":     "愤怒但克制的叙述，咬字有力，声音压低",
    "fearful":   "紧张恐惧的叙述，声音微微发颤，语速不稳",
    "tense":     "紧张压抑的叙述，声音低沉有力，节奏紧凑",
    "whisper":   "低声耳语般的叙述，神秘感",
    "excited":   "兴奋激动的叙述，声音高亢，语速快",
    "gentle":    "温柔轻缓的叙述，声音柔和，像在讲睡前故事",
    "narration": "沉稳专业的旁白叙述风格，声音有磁性，节奏适中",
}


def qwen_tts(text: str, voice: str = "Serena",
             instructions: str = None, emotion: str = None) -> bytes | None:
    """调用 Qwen3-TTS 生成语音，返回 WAV 音频字节。

    Args:
        text: 要合成的文本（≤600字）
        voice: 音色 ID
        instructions: 自然语言风格指令（与 emotion 二选一，优先 instructions）
        emotion: 预设情感标签（会转换为 instructions）

    Returns:
        WAV 音频字节，失败返回 None
    """
    if not text or not text.strip():
        return None

    # 构建 instructions
    inst = instructions
    if not inst and emotion:
        inst = EMOTION_INSTRUCTIONS.get(emotion, EMOTION_INSTRUCTIONS["calm"])
    if not inst:
        inst = EMOTION_INSTRUCTIONS["narration"]

    try:
        r = requests.post(
            TTS_ENDPOINT,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": TTS_MODEL,
                "input": {"text": text, "voice": voice},
                "parameters": {"instructions": inst},
            },
            timeout=30,
        )

        if r.status_code != 200:
            print(f"  Qwen TTS error: {r.status_code} {r.text[:100]}")
            return None

        result = r.json()
        audio_url = result.get("output", {}).get("audio", {}).get("url")
        if not audio_url:
            print(f"  Qwen TTS: 无音频 URL")
            return None

        # 下载 WAV
        wav_r = requests.get(audio_url, timeout=30)
        if wav_r.status_code == 200 and len(wav_r.content) > 100:
            return wav_r.content

        print(f"  Qwen TTS: 下载失败 {wav_r.status_code}")
        return None

    except Exception as e:
        print(f"  Qwen TTS exception: {e}")
        return None
