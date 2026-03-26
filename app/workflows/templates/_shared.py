"""
Shared utilities for workflow templates.
"""

import os
import re as _re_module


def _resolve_cjk_font() -> str:
    """跨平台 CJK 字体查找，返回可用字体路径。"""
    candidates = [
        # macOS
        "/System/Library/AssetsV2/com_apple_MobileAsset_Font7/3419f2a427639ad8c8e139149a287865a90fa17e.asset/AssetData/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        # Linux (apt install fonts-noto-cjk)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
        # Fallback
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""


def _ffmpeg_safe_text(text: str) -> str:
    """转义文本用于 FFmpeg drawtext filter，防止命令注入。"""
    text = text.replace("\\", "\\\\\\\\")
    text = text.replace("'", "'\\\\\\\\''")
    text = text.replace(":", "\\\\:")
    text = text.replace("%", "%%")
    text = text.replace(";", "\\\\;")
    text = text.replace("[", "\\\\[")
    text = text.replace("]", "\\\\]")
    return text


def _strip_shot_labels(text: str) -> str:
    """去掉 prompt 开头的景别缩写（EWS, CU, MS 等）避免 Gemini 渲染为文字"""
    return _re_module.sub(
        r'^(Extreme Wide Shot|EWS|Wide Shot|WS|Long Shot|LS|'
        r'Medium Shot|MS|Medium Close[- ]?Up|MCU|Close[- ]?Up|CU|'
        r'Extreme Close[- ]?Up|ECU|POV|Full Shot|FS|'
        r'Low [Aa]ngle|High [Aa]ngle|Silhouette [Ss]hot|Final [Cc]lose[- ]?[Uu]p)'
        r'[,\s]+', '', text).strip()


def _detect_grid_panels(grid_img):
    """检测 4x4 宫格图的分隔线，返回 crop boxes + resize target。

    Returns:
        (list[list[tuple]], tuple): (crop_boxes[row][col], (target_w, target_h))
    """
    import numpy as np
    arr = np.array(grid_img)
    col_bright = arr.mean(axis=(0, 2))
    row_bright = arr.mean(axis=(1, 2))
    bright_thresh = 200

    def _find_seps(brightness, n=3):
        bright_idx = np.where(brightness > bright_thresh)[0]
        if len(bright_idx) == 0:
            return []
        regions = []
        start = bright_idx[0]
        for i in range(1, len(bright_idx)):
            if bright_idx[i] - bright_idx[i-1] > 5:
                regions.append((int(start), int(bright_idx[i-1])))
                start = bright_idx[i]
        regions.append((int(start), int(bright_idx[-1])))
        total = len(brightness)
        inner = [(s, e) for s, e in regions if s > total * 0.05 and e < total * 0.95]
        return inner[:n]

    v_seps = _find_seps(col_bright, 3)
    h_seps = _find_seps(row_bright, 3)

    if len(v_seps) == 3 and len(h_seps) == 3:
        col_l = [0] + [s[1] + 1 for s in v_seps]
        col_r = [s[0] for s in v_seps] + [grid_img.width]
        row_t = [0] + [s[1] + 1 for s in h_seps]
        row_b = [s[0] for s in h_seps] + [grid_img.height]
        # 去掉外边框
        left_border = np.where(col_bright[:50] > bright_thresh)[0]
        if len(left_border) > 0:
            col_l[0] = int(left_border[-1]) + 1
        right_border = np.where(col_bright[-50:] > bright_thresh)[0]
        if len(right_border) > 0:
            col_r[3] = grid_img.width - 50 + int(right_border[0])
        boxes = [[( col_l[c], row_t[r], col_r[c], row_b[r] )
                  for c in range(4)] for r in range(4)]
    else:
        cw, ch = grid_img.width // 4, grid_img.height // 4
        boxes = [[(c*cw, r*ch, (c+1)*cw, (r+1)*ch)
                  for c in range(4)] for r in range(4)]

    # resize target: 统一 16:9 或 9:16
    all_w = [b[2]-b[0] for row in boxes for b in row]
    all_h = [b[3]-b[1] for row in boxes for b in row]
    max_w = max(all_w)
    max_h = max(all_h)
    # 判断方向：宽 > 高 → 横屏，高 > 宽 → 竖屏
    if max_w >= max_h:
        # 横屏 16:9
        target_w = max_w if max_w % 2 == 0 else max_w + 1
        target_h = round(target_w * 9 / 16)
    else:
        # 竖屏 9:16
        target_h = max_h if max_h % 2 == 0 else max_h + 1
        target_w = round(target_h * 9 / 16)
    if target_h % 2 == 1:
        target_h += 1
    if target_w % 2 == 1:
        target_w += 1

    return boxes, (target_w, target_h)


# LLM 输出校验
LLM_MAX_RETRIES = 3

def _validated_chat_json(system_prompt, user_prompt, required_keys,
                         temperature=0.5, max_tokens=8192, list_key=None,
                         list_length=None):
    """调用 LLM 并校验返回 JSON 的必需字段，失败重试。"""
    from vendor.qwen.client import chat_json
    for attempt in range(LLM_MAX_RETRIES):
        try:
            result = chat_json(system_prompt, user_prompt,
                               temperature=temperature, max_tokens=max_tokens)
            missing = [k for k in required_keys if k not in result]
            if missing:
                print(f"  LLM 校验失败 (attempt {attempt+1}): 缺少字段 {missing}")
                continue
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


NARRATION_VOICE_MATCH_SYSTEM_PROMPT = """你是一个顶级语音导演。你需要根据剧本的完整信息，为旁白配音选择最合适的音色并设计说话风格。

【选择音色的依据】
1. 故事题材和风格（都市言情/悬疑/古风/热血 等）
2. 情感基调（紧张/温馨/悲伤/燃 等）
3. 目标观众（年轻女性/男性/通用 等）
4. 旁白的叙事定位（第三人称客观叙述/带感情的讲述者/神秘感旁白 等）

【设计 TTS instruct 的要求】
1. 必须结合故事内容，不能只是泛泛的"低沉""稳重"
2. 描述具体的声音质感（如：略带沙哑的磁性嗓音 / 清亮如泉水的少女音）
3. 描述节奏变化（如：叙事段落语速平缓，冲突段落加快节奏，悬念处刻意停顿）
4. 描述情感层次（如：表面冷静但暗藏焦虑，随着情节推进逐渐沉重）
5. 50-80字中文

严格输出JSON格式：
{{
  "voice_id": "选中的音色ID",
  "reason": "选择理由（一句话）",
  "tts_instructions": "TTS旁白风格指令（50-80字中文，结合故事内容）"
}}"""


# ── BGM 预处理 ─────────────────────────────────────────────────

def _preprocess_bgm(bgm_raw_path: str, target_duration: float,
                    output_path: str, **kwargs) -> str | None:
    """BGM 预处理：dynaudnorm 滑窗音量均衡 → 截取到目标时长。

    用 FFmpeg dynaudnorm 将局部过弱的部分（如首尾渐入渐出）拉到接近全曲
    平均水平，避免开头结尾音量过小。处理后再由调用方做整体 dB 校准和 fade。

    Args:
        bgm_raw_path: 原始 BGM 文件路径
        target_duration: 目标时长（秒），通常等于视频时长
        output_path: 输出文件路径

    Returns:
        处理后的 BGM 文件路径，失败返回 None
    """
    import subprocess

    if not os.path.exists(bgm_raw_path):
        return None

    # 两步处理:
    # Step 1: compand 向上压缩 — 将低于 -30dB 的部分提升（最大 +15dB），
    #         高于 -20dB 的不动，-30 到 -20 之间平滑过渡
    # Step 2: dynaudnorm 滑窗均衡 — 3s 窗口进一步平滑局部音量差异
    af_filter = (
        "compand=attacks=0.1:decays=0.5:"
        "points=-90/-90|-45/-20|-30/-16|-20/-16|0/0:gain=0,"
        "dynaudnorm=framelen=3000:gausssize=31:"
        "peak=0.95:maxgain=25:correctdc=1"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", bgm_raw_path,
        "-t", str(target_duration),
        "-af", af_filter,
        "-c:a", "libmp3lame", "-b:a", "192k",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=60)

    if result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 100:
        before_mean, _ = _measure_mean_volume(bgm_raw_path, duration=5)
        after_mean, _ = _measure_mean_volume(output_path, duration=5)
        print(f"    BGM 预处理: compand + dynaudnorm (3s窗口, maxgain=15dB)")
        print(f"    BGM 预处理: 前5s mean {before_mean:.1f}dB → {after_mean:.1f}dB")
        return output_path

    print(f"    BGM 预处理: ✗ 处理失败")
    return None


def _measure_mean_volume(path: str, duration: float = None):
    """测量音频文件的 mean 和 max volume (dB)。"""
    import subprocess
    cmd = ["ffmpeg", "-i", path]
    if duration:
        cmd += ["-t", str(duration)]
    cmd += ["-af", "volumedetect", "-f", "null", "-"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    mean_db, max_db = -20.0, 0.0
    for line in result.stderr.split("\n"):
        if "mean_volume" in line:
            try:
                mean_db = float(line.split("mean_volume:")[1].strip().replace(" dB", ""))
            except (ValueError, IndexError):
                pass
        elif "max_volume" in line:
            try:
                max_db = float(line.split("max_volume:")[1].strip().replace(" dB", ""))
            except (ValueError, IndexError):
                pass
    return mean_db, max_db
