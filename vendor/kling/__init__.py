"""
可灵 (Kling) AI vendor module
提供图生视频（I2V）、文生图（T2I）能力，支持角色参考图绑定
"""

from .config import ACCESS_KEY, SECRET_KEY, BASE_URL
from .client import KlingClient
