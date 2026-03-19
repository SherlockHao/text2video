"""
Provider registry and routing.

Maps (task_type, quality_tier) to concrete ExternalAIProvider instances.
"""

import logging
from typing import Optional

from app.ai.base import ExternalAIProvider

logger = logging.getLogger(__name__)

# Provider class registry - populated by provider modules
_PROVIDER_CLASSES: dict[str, type[ExternalAIProvider]] = {}


def register_provider(name: str, cls: type[ExternalAIProvider]) -> None:
    """Register a provider class."""
    _PROVIDER_CLASSES[name] = cls
    logger.info("Registered provider: %s", name)


# Routing table: (task_type, quality_tier) -> provider_name
# quality_tier=None means "any quality tier"
_ROUTING_TABLE: dict[tuple[str, Optional[str]], str] = {
    ("script_breakdown", None): "qwen",
    ("image_generation", None): "jimeng",
    ("video_generation", "normal"): "kling",
    ("video_generation", "high"): "seedance2",
    ("video_generation", None): "kling",  # default
    ("tts_generation", None): "elevenlabs",
}


def get_provider(task_type: str, quality_tier: str | None = None) -> ExternalAIProvider:
    """
    Get a provider instance for the given task type and quality tier.

    Routing priority:
    1. Exact match (task_type, quality_tier)
    2. Fallback match (task_type, None)

    Raises:
        ValueError: If no provider is registered for the given combination.
    """
    # Try exact match first
    provider_name = _ROUTING_TABLE.get((task_type, quality_tier))

    # Fallback to any-quality match
    if provider_name is None:
        provider_name = _ROUTING_TABLE.get((task_type, None))

    if provider_name is None:
        raise ValueError(
            f"No provider route for task_type={task_type}, quality_tier={quality_tier}"
        )

    cls = _PROVIDER_CLASSES.get(provider_name)
    if cls is None:
        raise ValueError(
            f"Provider '{provider_name}' is routed but not registered. "
            f"Available: {list(_PROVIDER_CLASSES.keys())}"
        )

    return cls()


def update_route(task_type: str, quality_tier: str | None, provider_name: str) -> None:
    """Update a routing entry (useful for testing or runtime config changes)."""
    _ROUTING_TABLE[(task_type, quality_tier)] = provider_name
