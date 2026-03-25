"""
小说分集拆解器 (Novel Splitter)

将一篇长篇小说（≤5万字）拆解为多个短剧集，每集约600字原文，
对应1分钟左右的短视频。

Pipeline:
  1. split_into_chunks   — 按段落边界物理粗切（≤5000字/chunk）
  2. process_novel       — 滑动窗口调用 LLM 生成剧集蓝图
  3. extract_episodes    — 基于锚点从原文精准截取每集文本
"""

from __future__ import annotations

import json
import logging

from vendor.qwen.client import chat_json

logger = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────

CHARS_PER_EPISODE = 600        # 每集约 600 原文字 ≈ 1 分钟视频
CHUNK_MAX_LENGTH = 5000        # 每个 chunk 上限
LLM_TEMPERATURE = 0.5         # 规划师偏稳定
LLM_MAX_TOKENS = 4096         # 足够输出 10+ 集 JSON

# ── Step 1: 物理粗切 ──────────────────────────────────────────────


def split_into_chunks(text: str, max_length: int = 5000) -> list[str]:
    """按段落边界将长文本切分为不超过 max_length 字的多个 chunk。

    切分逻辑：
    - 以 '\\n' 为段落分隔符拆出所有段落（保留空行语义）
    - 逐段累加，若加入当前段落后总长度超过 max_length，
      则把已累积内容作为一个 chunk，当前段落归入下一个 chunk
    - 单段落超过 max_length 的极端情况：该段落独立成一个 chunk（不硬切）

    Args:
        text: 完整小说文本
        max_length: 每个 chunk 的最大字符数，默认 5000

    Returns:
        chunk 文本列表，每个元素为一段连续原文
    """
    paragraphs = text.split("\n")

    chunks: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for para in paragraphs:
        para_len = len(para)

        # 加上换行符的长度（拼接时用 \n 连接）
        added_length = para_len + (1 if current_parts else 0)

        if current_parts and current_length + added_length > max_length:
            # 当前 chunk 已满，先保存
            chunks.append("\n".join(current_parts))
            current_parts = []
            current_length = 0

        current_parts.append(para)
        current_length += para_len + (1 if len(current_parts) > 1 else 0)

    # 收尾：最后一个 chunk
    if current_parts:
        chunks.append("\n".join(current_parts))

    # 过滤掉纯空白 chunk
    chunks = [c for c in chunks if c.strip()]

    return chunks


# ── Step 2: 滑动窗口 LLM 调用 ────────────────────────────────────

SHOWRUNNER_SYSTEM_PROMPT = """# Role: 顶级短剧总编剧兼全剧架构师 (Showrunner)

# Task:
阅读提供的【小说文本块】，将其大刀阔斧地"脱水提纯"，拆解为 {target_episodes} 集左右的高节奏、强冲突短剧/漫剧章节，并输出一份用于工程切割的《剧集拆解蓝图》(JSON格式)。

# Core Rules:
1. 剧情脱水：毫不留情地砍掉冗长景物描写和无关支线。每集只保留核心冲突。
2. 悬念钩子：每集的结尾必须卡在情绪最高潮或冲突即将爆发的瞬间（如打脸一半、生死危机）。强制切断，吸引观众看下一集。
3. 状态记忆：为每一集生成精准的 `context_state`（包含当前核心角色、位置、受伤/异常状态、刚发生的事），用于防止后续分镜失忆。
4. 物理切割锚点：为了让脚本精准切割原文，必须从原文中提取原封不动的句子作为 `start_anchor` (开头句) 和 `end_anchor` (结尾句)。锚点长度 10-20 字，必须与原文【一字不差】且具唯一性。

# Output Format:
严格遵守且仅输出JSON格式，不要任何 Markdown 代码块以外的废话。
{{
  "chunk_global_summary": "本文本块的一句话核心剧情",
  "episodes":[
    {{
      "episode_title": "本集标题",
      "context_state": "【前情状态】...",
      "compression_instruction": "【提纯指令】指导下一个模型：忽略哪些环境描写，重点放大什么动作...",
      "hook_type": "生死悬念/惊人反转等",
      "start_anchor": "原文中作为本集开头的原句...",
      "end_anchor": "原文中作为本集结尾（卡点）的原句..."
    }}
  ]
}}"""

SHOWRUNNER_USER_PROMPT = """【前情提要】：{previous_context}
(注：如果前情提要为"无"，说明这是小说的开头。)

【目标集数】：请尽量将以下文本块拆解为 {target_episodes} 集。

【小说文本块】：
{chunk_text}"""


def process_novel(
    full_text: str,
    max_chunk_length: int = CHUNK_MAX_LENGTH,
    chars_per_episode: int = CHARS_PER_EPISODE,
) -> list[dict]:
    """滑动窗口遍历 chunks，调用 LLM 规划师生成剧集蓝图。

    Args:
        full_text: 完整小说文本
        max_chunk_length: chunk 最大字符数
        chars_per_episode: 每集对应的原文字数

    Returns:
        所有 chunk 的蓝图列表，每个元素结构为:
        {
            "chunk_index": int,
            "chunk_text": str,
            "blueprint": { "chunk_global_summary": ..., "episodes": [...] }
        }
    """
    # 1. 物理粗切
    chunks = split_into_chunks(full_text, max_length=max_chunk_length)
    logger.info(f"小说共 {len(full_text)} 字，切分为 {len(chunks)} 个 chunk")

    # 2. 滑动窗口循环
    previous_context = "无"
    all_blueprints: list[dict] = []

    for i, chunk_text in enumerate(chunks):
        # 动态估算本 chunk 的目标集数
        target_episodes = max(1, len(chunk_text) // chars_per_episode)
        logger.info(
            f"[Chunk {i+1}/{len(chunks)}] "
            f"{len(chunk_text)} 字, 目标 {target_episodes} 集"
        )

        # 构造 prompt
        system_prompt = SHOWRUNNER_SYSTEM_PROMPT.format(
            target_episodes=target_episodes
        )
        user_prompt = SHOWRUNNER_USER_PROMPT.format(
            previous_context=previous_context,
            target_episodes=target_episodes,
            chunk_text=chunk_text,
        )

        # 调用 LLM
        blueprint = chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )

        episodes = blueprint.get("episodes", [])
        logger.info(
            f"  → LLM 返回 {len(episodes)} 集, "
            f"摘要: {blueprint.get('chunk_global_summary', '(无)')}"
        )

        # 记录结果
        all_blueprints.append({
            "chunk_index": i,
            "chunk_text": chunk_text,
            "blueprint": blueprint,
        })

        # 滑动窗口：将最后一集的 context_state 传给下一个 chunk
        if episodes:
            previous_context = episodes[-1].get("context_state", "无")

    logger.info(
        f"规划完成: 共 {sum(len(b['blueprint'].get('episodes', [])) for b in all_blueprints)} 集"
    )
    return all_blueprints


# ── Step 3: 基于锚点的精准切割 ───────────────────────────────────


def extract_episodes_raw_text(
    chunk_text: str,
    blueprint: dict,
) -> list[dict]:
    """根据蓝图中的 start_anchor / end_anchor 从原文中截取每集文本。

    容错策略（按优先级）：
    1. 精确匹配：直接在 chunk_text 中 find start_anchor 和 end_anchor
    2. 子串模糊匹配：取锚点前8字做子串搜索（应对 LLM 多加/少加标点）
    3. 兜底：如果 start 找不到，用上一集 end 的位置；如果 end 找不到，
       用下一集 start 的位置或 chunk 末尾

    Args:
        chunk_text: 当前 chunk 的原文
        blueprint: LLM 返回的蓝图 JSON（含 episodes 列表）

    Returns:
        每集信息列表，在原 episode dict 基础上增加:
        - raw_text: 截取的原文
        - anchor_match: "exact" | "fuzzy" | "fallback" 标记匹配质量
    """
    episodes = blueprint.get("episodes", [])
    if not episodes:
        return []

    results: list[dict] = []
    last_end_pos = 0  # 上一集结束位置，用于兜底

    for i, ep in enumerate(episodes):
        start_anchor = ep.get("start_anchor", "")
        end_anchor = ep.get("end_anchor", "")

        # ── 查找 start 位置 ──
        start_pos, start_quality = _find_anchor(
            chunk_text, start_anchor, search_from=last_end_pos
        )
        if start_pos == -1:
            # 兜底：从上一集结束位置开始
            start_pos = last_end_pos
            start_quality = "fallback"

        # ── 查找 end 位置 ──
        end_pos, end_quality = _find_anchor(
            chunk_text, end_anchor, search_from=start_pos
        )
        if end_pos == -1:
            # 兜底：尝试用下一集的 start_anchor 定位
            if i + 1 < len(episodes):
                next_start = episodes[i + 1].get("start_anchor", "")
                next_pos, _ = _find_anchor(
                    chunk_text, next_start, search_from=start_pos
                )
                end_pos = next_pos if next_pos != -1 else len(chunk_text)
            else:
                end_pos = len(chunk_text)
            end_quality = "fallback"
        else:
            # end_pos 指向锚点开头，需要包含锚点本身
            end_pos += len(end_anchor)

        # 截取原文
        raw_text = chunk_text[start_pos:end_pos].strip()

        # 综合匹配质量
        if start_quality == "exact" and end_quality == "exact":
            anchor_match = "exact"
        elif "fallback" in (start_quality, end_quality):
            anchor_match = "fallback"
        else:
            anchor_match = "fuzzy"

        result = {**ep, "raw_text": raw_text, "anchor_match": anchor_match}
        results.append(result)

        last_end_pos = end_pos

        logger.debug(
            f"  Episode {i+1} '{ep.get('episode_title', '')}': "
            f"{len(raw_text)} 字, match={anchor_match}"
        )

    # 统计匹配质量
    exact_count = sum(1 for r in results if r["anchor_match"] == "exact")
    fuzzy_count = sum(1 for r in results if r["anchor_match"] == "fuzzy")
    fallback_count = sum(1 for r in results if r["anchor_match"] == "fallback")
    logger.info(
        f"锚点切割完成: {len(results)} 集, "
        f"精确={exact_count}, 模糊={fuzzy_count}, 兜底={fallback_count}"
    )

    return results


def _find_anchor(
    text: str,
    anchor: str,
    search_from: int = 0,
) -> tuple[int, str]:
    """在 text 中查找锚点位置。

    Returns:
        (position, quality): position=-1 表示未找到,
        quality 为 "exact" | "fuzzy"
    """
    if not anchor:
        return -1, "fallback"

    # 1. 精确匹配
    pos = text.find(anchor, search_from)
    if pos != -1:
        return pos, "exact"

    # 2. 模糊匹配：取锚点前 8 个字符做子串搜索
    #    应对 LLM 可能多加/少加标点、空格的情况
    short = anchor[:8].strip()
    if len(short) >= 4:
        pos = text.find(short, search_from)
        if pos != -1:
            return pos, "fuzzy"

    # 3. 进一步模糊：去除所有标点空格后匹配
    import re
    anchor_clean = re.sub(r"[\s\u3000，。！？、；：\u201c\u201d\u2018\u2019（）《》\u2014\u2026·-]", "", anchor)
    if len(anchor_clean) >= 6:
        # 在 text 中滑动匹配
        text_clean_map = []  # (clean_index, original_index)
        for idx, ch in enumerate(text[search_from:], start=search_from):
            if not re.match(r"[\s\u3000，。！？、；：\u201c\u201d\u2018\u2019（）《》\u2014\u2026·-]", ch):
                text_clean_map.append((len(text_clean_map), idx))

        text_clean = "".join(
            text[orig_idx] for _, orig_idx in text_clean_map
        )
        clean_pos = text_clean.find(anchor_clean[:10])
        if clean_pos != -1 and clean_pos < len(text_clean_map):
            return text_clean_map[clean_pos][1], "fuzzy"

    return -1, "fallback"


# ── 完整入口 ─────────────────────────────────────────────────────


def split_novel_to_episodes(
    full_text: str,
    output_dir: str | None = None,
    chars_per_episode: int = CHARS_PER_EPISODE,
    max_chunk_length: int = CHUNK_MAX_LENGTH,
) -> list[dict]:
    """完整流程：粗切 → LLM 蓝图 → 锚点切割 → 输出每集信息。

    Args:
        full_text: 完整小说文本
        output_dir: 可选，输出目录。若提供则保存 blueprint.json 和每集 txt
        chars_per_episode: 每集对应的原文字数
        max_chunk_length: chunk 最大字符数

    Returns:
        全局集列表，每个元素:
        {
            "episode_number": int (从1开始的全局编号),
            "episode_title": str,
            "context_state": str,
            "compression_instruction": str,
            "hook_type": str,
            "raw_text": str (截取的原文),
            "anchor_match": str ("exact"/"fuzzy"/"fallback"),
            "chunk_index": int (所属 chunk 编号),
        }
    """
    import os

    logger.info(f"开始小说分集: {len(full_text)} 字, "
                f"预估 {max(1, len(full_text) // chars_per_episode)} 集")

    # Step 1+2: 粗切 + LLM 蓝图
    all_blueprints = process_novel(
        full_text,
        max_chunk_length=max_chunk_length,
        chars_per_episode=chars_per_episode,
    )

    # Step 3: 锚点切割 + 全局编号
    all_episodes: list[dict] = []
    global_ep_num = 0

    for bp_item in all_blueprints:
        chunk_text = bp_item["chunk_text"]
        blueprint = bp_item["blueprint"]
        chunk_idx = bp_item["chunk_index"]

        episodes = extract_episodes_raw_text(chunk_text, blueprint)

        for ep in episodes:
            global_ep_num += 1
            ep["episode_number"] = global_ep_num
            ep["chunk_index"] = chunk_idx
            all_episodes.append(ep)

    logger.info(f"分集完成: 共 {len(all_episodes)} 集")

    # 保存到磁盘
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

        # 保存完整蓝图
        blueprint_path = os.path.join(output_dir, "novel_blueprint.json")
        with open(blueprint_path, "w", encoding="utf-8") as f:
            json.dump(all_blueprints, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"蓝图已保存: {blueprint_path}")

        # 保存每集摘要
        episodes_summary = []
        for ep in all_episodes:
            episodes_summary.append({
                "episode_number": ep["episode_number"],
                "episode_title": ep["episode_title"],
                "context_state": ep["context_state"],
                "compression_instruction": ep["compression_instruction"],
                "hook_type": ep["hook_type"],
                "anchor_match": ep["anchor_match"],
                "raw_text_length": len(ep["raw_text"]),
                "chunk_index": ep["chunk_index"],
            })
        summary_path = os.path.join(output_dir, "episodes_summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(episodes_summary, f, ensure_ascii=False, indent=2)
        logger.info(f"集摘要已保存: {summary_path}")

        # 保存每集原文 txt（供下游分镜 LLM 使用）
        episodes_dir = os.path.join(output_dir, "episodes")
        os.makedirs(episodes_dir, exist_ok=True)
        for ep in all_episodes:
            ep_path = os.path.join(episodes_dir, f"ep_{ep['episode_number']:03d}.txt")
            with open(ep_path, "w", encoding="utf-8") as f:
                f.write(ep["raw_text"])
            # 同时保存元数据
            meta_path = os.path.join(episodes_dir, f"ep_{ep['episode_number']:03d}_meta.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                meta = {k: v for k, v in ep.items() if k != "raw_text"}
                meta["raw_text_length"] = len(ep["raw_text"])
                json.dump(meta, f, ensure_ascii=False, indent=2)

        logger.info(f"每集文件已保存: {episodes_dir}/ (共 {len(all_episodes)} 集)")

    return all_episodes
