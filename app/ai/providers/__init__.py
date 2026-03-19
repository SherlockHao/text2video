from typing import Dict, Type

from app.ai.base import AIProvider
from app.ai.providers.subtitle import SubtitleProvider
from app.ai.providers.text_to_video import TextToVideoProvider
from app.ai.providers.tts import TTSProvider

PROVIDER_REGISTRY: Dict[str, Type[AIProvider]] = {
    "text_to_video": TextToVideoProvider,
    "tts": TTSProvider,
    "subtitle": SubtitleProvider,
}


def get_provider(name: str) -> AIProvider:
    """Instantiate and return an AI provider by name.

    Raises:
        KeyError: If the provider name is not in the registry.
    """
    if name not in PROVIDER_REGISTRY:
        raise KeyError(
            f"Unknown provider '{name}'. Available: {list(PROVIDER_REGISTRY)}"
        )
    return PROVIDER_REGISTRY[name]()
