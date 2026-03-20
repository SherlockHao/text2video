"""
Jimeng-specific utility functions.

Helpers for dimension calculation and result decoding
used by JimengProvider.
"""

import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Predefined aspect-ratio -> (width, height) mapping.
# Values are chosen to be compatible with Jimeng T2I v4.0 (multiples of 64,
# reasonable total pixel count).
# Verified working dimensions for Jimeng T2I v4.0
# Must be multiples of 16, within [512, 1536] range
_ASPECT_RATIO_MAP: dict[str, tuple[int, int]] = {
    "16:9": (1472, 832),
    "9:16": (832, 1472),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "1:1": (1024, 1024),
    "3:2": (1024, 672),
    "2:3": (672, 1024),
}


def calculate_dimensions(aspect_ratio: str) -> tuple[int, int]:
    """Convert an aspect ratio string to Jimeng-compatible pixel dimensions.

    Args:
        aspect_ratio: e.g. "16:9", "9:16", "1:1".

    Returns:
        (width, height) tuple. Falls back to (1024, 1024) for unknown ratios.
    """
    result = _ASPECT_RATIO_MAP.get(aspect_ratio, (1024, 1024))
    if aspect_ratio not in _ASPECT_RATIO_MAP:
        logger.warning(
            "Unknown aspect ratio '%s', defaulting to 1024x1024", aspect_ratio
        )
    return result


def decode_image_result(data: dict) -> Optional[bytes]:
    """Extract image bytes from a Jimeng API response dict.

    Checks ``binary_data_base64`` first (preferred — no extra download).
    Falls back to the first entry in ``image_urls`` if base64 is absent.

    Args:
        data: The ``data`` dict returned by ``get_t2i_result``.

    Returns:
        Raw image bytes, or *None* if no image data could be extracted.
    """
    # Try base64 first
    for b64 in data.get("binary_data_base64", []):
        if b64:
            try:
                return base64.b64decode(b64)
            except Exception:
                logger.warning("Failed to decode base64 image data")
                continue

    # Fallback: download from URL
    for url in data.get("image_urls", []):
        if url:
            try:
                import requests

                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                return resp.content
            except Exception:
                logger.warning("Failed to download image from %s", url)
                continue

    return None
