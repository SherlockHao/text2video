"""
Sora 2 (OpenAI) vendor module
提供文生视频能力，作为 Kling V3 的备选方案
注意: prompt 必须使用英文
"""

from .config import API_KEY
from .client import Sora2Client
