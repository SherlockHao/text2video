"""
Prompt template registry.

Maps (content_type, visual_style) pairs to prompt builder functions.
Each builder function accepts source text and configuration parameters
and returns {"system_prompt": str, "user_prompt": str}.
"""

from typing import Callable

_TEMPLATES: dict[tuple[str, str], Callable] = {}


def register_template(content_type: str, visual_style: str, fn: Callable) -> None:
    """Register a prompt template builder function."""
    _TEMPLATES[(content_type, visual_style)] = fn


def get_template(content_type: str, visual_style: str) -> Callable:
    """
    Retrieve a registered prompt template builder function.

    Raises:
        ValueError: If no template is registered for the given combination.
    """
    fn = _TEMPLATES.get((content_type, visual_style))
    if fn is None:
        raise ValueError(f"No prompt template for ({content_type}, {visual_style})")
    return fn
