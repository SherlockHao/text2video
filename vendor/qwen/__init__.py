"""
Qwen3.5-Plus vendor module
提供 LLM 调用能力，用于小说分镜拆解等文本生成任务
"""

from .client import chat, chat_json, chat_with_system, create_client
from .config import API_KEY, BASE_URL, MODEL
from .storyboard import novel_to_storyboard
