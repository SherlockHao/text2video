"""
Qwen3.5-Plus API 客户端
通过 OpenAI 兼容接口调用阿里云百炼平台的 Qwen3.5-Plus 模型
"""

import json
from openai import OpenAI

from .config import API_KEY, BASE_URL, MODEL


def create_client() -> OpenAI:
    """创建 Qwen API 客户端"""
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)


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
    )
    return response.choices[0].message.content


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


def chat_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict:
    """调用 Qwen 并解析返回的 JSON（自动处理 markdown 代码块包裹）"""
    raw = chat_with_system(system_prompt, user_prompt, temperature, max_tokens)

    json_str = raw
    if "```json" in raw:
        json_str = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        json_str = raw.split("```")[1].split("```")[0]

    return json.loads(json_str)
