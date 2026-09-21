from typing import Dict, Literal, Optional

from app.core.config import Settings
from app.core.router import create_named_provider, ProviderConfigurationError
from app.providers.base import AIProvider

ModelProfile = Literal["fast", "quality", "reasoning", "vision"]


class ModelRouter:
    """Maps stable capability profiles to configured provider implementations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._provider_names: Dict[ModelProfile, str] = {
            "fast": settings.model_fast_provider or settings.ai_provider,
            "quality": settings.model_quality_provider or settings.ai_provider,
            "reasoning": settings.model_reasoning_provider or settings.ai_provider,
            "vision": settings.model_vision_provider or settings.ai_provider,
        }
        self._model_names = {profile: getattr(settings, f"model_{profile}_name") for profile in self._provider_names}
        self._providers: Dict[str, AIProvider] = {}

    def provider_for(self, profile: ModelProfile = "quality") -> AIProvider:
        provider_name = self._provider_names[profile]
        if profile == "vision" and not self.vision_configured():
            raise ProviderConfigurationError("VISION is not configured. Set a vision-capable provider and AKASHI_MODEL_VISION_NAME on the backend.")
        key = f"{provider_name}:{self._model_names[profile]}"
        if key not in self._providers:
            self._providers[key] = create_named_provider(
                self.settings, provider_name, self._model_names[profile]
            )
        return self._providers[key]

    def vision_configured(self) -> bool:
        return bool(self._model_names["vision"] and self._provider_names["vision"] in {"ollama", "gemini"})

    def profile_for_provider(self, provider: AIProvider) -> Optional[ModelProfile]:
        for profile, name in self._provider_names.items():
            if name == provider.name:
                return profile
        return None

    def describe(self) -> Dict[str, str]:
        return dict(self._provider_names)

    def capabilities(self) -> dict:
        # Configuration is not proof of successful live inference.
        return {
            profile: {
                "available": (self.vision_configured() if profile == "vision" else True)
                and provider in {"mock", "ollama", "gemini"}
                and (provider != "gemini" or bool(self.settings.gemini_api_key)),
                "accepts_images": profile == "vision" and self.vision_configured(),
                "kind": "mock" if provider == "mock" else "model",
            }
            for profile, provider in self._provider_names.items()
        }
