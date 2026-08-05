from app.core.config import Settings
from app.providers.base import AIProvider
from app.providers.gemini import GeminiProvider
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider


class ProviderConfigurationError(RuntimeError):
    """Raised when an AI provider cannot be configured."""


def create_provider(settings: Settings) -> AIProvider:
    """Build the configured provider behind a stable interface."""

    if settings.ai_provider == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model_name=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
        )

    if settings.ai_provider == "mock":
        return MockProvider()

    if settings.ai_provider == "gemini":
        if not settings.gemini_api_key:
            raise ProviderConfigurationError(
                "AI_PROVIDER is set to 'gemini', "
                "but GEMINI_API_KEY is missing."
            )

        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
        )

    raise ProviderConfigurationError(
        f"Unsupported AI_PROVIDER '{settings.ai_provider}'. "
        "Supported providers: ollama, mock, gemini."
    )
