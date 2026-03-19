"""
Qwen3.5-Plus API 客户端
通过 OpenAI 兼容接口调用阿里云百炼平台的 Qwen3.5-Plus 模型
"""

import json
from openai import OpenAI

from .config import API_KEY, BASE_URL, MODEL


def create_client() -> OpenAI:
    """创建 Qwen API 客户端"""
    return OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=120.0)


def chat(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    model: str | None = None,
) -> str:
    """调用 Qwen3.5-Plus 聊天接口，返回文本内容"""
    client = create_client()
    response = client.chat.completions.create(
        model=model or MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body={"enable_thinking": False},
    )
    msg = response.choices[0].message
    content = msg.content or ""

    # Qwen 3.5-Plus thinking mode: content may be empty, actual output in reasoning_content
    if not content.strip() and hasattr(msg, "reasoning_content") and msg.reasoning_content:
        content = msg.reasoning_content

    return content


def chat_with_system(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """便捷方法：使用 system + user 消息调用"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return chat(messages, temperature=temperature, max_tokens=max_tokens)


def _extract_json(raw: str) -> str:
    """从 LLM 响应中提取 JSON 字符串，处理各种包裹格式"""
    import re

    text = raw

    # 1. Strip <think>...</think> tags (Qwen thinking mode)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # 2. Extract from ```json ... ``` code block
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        parts = text.split("```")
        # Find the part that looks like JSON
        for part in parts:
            stripped = part.strip()
            if stripped.startswith(("{", "[")):
                text = stripped
                break

    # 3. Find the outermost JSON object by matching braces
    text = text.strip()
    start_idx = text.find("{")
    if start_idx == -1:
        start_idx = text.find("[")
    if start_idx == -1:
        return text

    # Find matching closing brace/bracket
    open_char = text[start_idx]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    end_idx = start_idx

    for i in range(start_idx, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                end_idx = i
                break

    return text[start_idx:end_idx + 1]


def chat_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict:
    """调用 Qwen 并解析返回的 JSON（自动处理 thinking 标签、markdown 代码块等包裹）"""
    raw = chat_with_system(system_prompt, user_prompt, temperature, max_tokens)
    json_str = _extract_json(raw)
    return json.loads(json_str)
