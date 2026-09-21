from app.core.config import Settings
from app.providers.base import AIProvider
from typing import Optional
from app.providers.gemini import GeminiProvider
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider


class ProviderConfigurationError(RuntimeError):
    """Raised when an AI provider cannot be configured."""


def create_named_provider(settings: Settings, provider_name: str, model_name: Optional[str] = None) -> AIProvider:
    """Build a named provider behind the stable provider interface."""
    provider_name = provider_name.strip().lower()

    if provider_name == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model_name=model_name or settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
        )

    if provider_name == "mock":
        return MockProvider()

    if provider_name == "gemini":
        if not settings.gemini_api_key:
            raise ProviderConfigurationError(
                "AI_PROVIDER is set to 'gemini', "
                "but GEMINI_API_KEY is missing."
            )

        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model_name=model_name or settings.gemini_model,
        )

    raise ProviderConfigurationError(
        f"Unsupported AI provider '{provider_name}'. "
        "Supported providers: ollama, mock, gemini."
    )


def create_provider(settings: Settings) -> AIProvider:
    """Build the legacy/default provider without changing existing callers."""
    return create_named_provider(settings, settings.ai_provider)
