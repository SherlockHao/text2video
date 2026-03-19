"""
即梦AI (火山引擎) vendor module
提供图片生成、图生视频、图像风格化能力
"""

from .config import AK, SK
from .i2v import generate_video, submit_i2v_task, get_i2v_result, save_video
from .t2i import generate_image, submit_t2i_task, get_t2i_result, save_images
from .style import stylize_image, STYLES
