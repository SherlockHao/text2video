"""
TTS-driven duration planner — 基于真实 TTS 时长规划子镜头时长

Logic:
  target = tts_duration + buffer (default 1.0s)
  Case 1: target >= original total → keep as-is
  Case 2: target < total, proportional shrink (all >= min) → shrink
  Case 3: proportional shrink hits min floor → pin at min, shrink rest
  Case 4: all at min still > target → collapse to single shot
"""

import math
import logging

logger = logging.getLogger(__name__)

KLING_MIN_DURATION = 3
KLING_MAX_DURATION = 15
DEFAULT_SUB_SHOT_DURATION = 5
TTS_BUFFER = 1.0  # 前后各 0.5s


def plan_sub_shot_durations(
    sub_shots: list[dict],
    tts_duration: float,
    default_duration: int = DEFAULT_SUB_SHOT_DURATION,
    min_duration: int = KLING_MIN_DURATION,
    max_duration: int = KLING_MAX_DURATION,
    buffer: float = TTS_BUFFER,
) -> tuple[list[dict] | None, list[int] | None]:
    """
    根据真实 TTS 时长规划子镜头时长。

    Returns:
        (sub_shots, durations) — 调整后的子镜头列表和时长数组
        如果触发 Case 4，返回 (None, None)
    """
    n = len(sub_shots)
    if n == 0:
        return None, None

    target = tts_duration + buffer
    original_durations = [default_duration] * n
    total_original = sum(original_durations)

    # Case 1: target >= total → 不调整
    if target >= total_original:
        return sub_shots, original_durations

    # Case 2/3: target < total → 等比例缩短
    ratio = target / total_original
    raw_durations = [d * ratio for d in original_durations]

    any_below_min = any(d < min_duration for d in raw_durations)

    if not any_below_min:
        # Case 2: 全部 >= min
        durations = _round_durations(raw_durations, target, min_duration, max_duration)
        return sub_shots, durations

    # Case 3: 有子镜头 < min，钉死后缩短其他
    durations = _shrink_with_floor(original_durations, target, min_duration, max_duration)

    if durations is None:
        # Case 4: 全部 min 仍超出
        return None, None

    return sub_shots, durations


def get_single_shot_duration(
    tts_duration: float,
    min_duration: int = KLING_MIN_DURATION,
    max_duration: int = KLING_MAX_DURATION,
    buffer: float = TTS_BUFFER,
) -> int:
    """Case 4 兜底：计算单镜头时长。"""
    return max(min_duration, min(max_duration, round(tts_duration + buffer)))


def _round_durations(
    raw_durations: list[float],
    target: float,
    min_dur: int,
    max_dur: int,
) -> list[int]:
    """将浮点时长取整为整数秒，总和尽量接近 target。"""
    n = len(raw_durations)
    target_int = max(n * min_dur, round(target))

    durations = [max(min_dur, math.floor(d)) for d in raw_durations]
    durations[-1] = max(min_dur, target_int - sum(durations[:-1]))
    durations = [max(min_dur, min(max_dur, d)) for d in durations]
    return durations


def _shrink_with_floor(
    original_durations: list[int],
    target: float,
    min_dur: int,
    max_dur: int,
) -> list[int] | None:
    """缩短子镜头，低于 min 的钉死，其余按比例缩短。"""
    n = len(original_durations)
    if n * min_dur > target:
        return None  # Case 4

    durations = list(original_durations)
    remaining_target = target
    pinned = set()

    for _ in range(n):
        flexible = [i for i in range(n) if i not in pinned]
        flex_total = sum(durations[i] for i in flexible)
        if flex_total <= 0:
            break

        ratio = remaining_target / flex_total
        new_durs = list(durations)
        newly_pinned = False

        for i in flexible:
            new_val = durations[i] * ratio
            if new_val < min_dur:
                new_durs[i] = min_dur
                pinned.add(i)
                remaining_target -= min_dur
                newly_pinned = True
            else:
                new_durs[i] = new_val

        durations = new_durs
        if not newly_pinned:
            break
        remaining_target = target - sum(durations[i] for i in pinned)

    return _round_durations(durations, target, min_dur, max_dur)
