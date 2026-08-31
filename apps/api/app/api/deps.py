import logging

from fastapi import HTTPException, Request

from app.core.config import get_settings
from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMConfigError
from app.llm.demo_responses import DEMO_RESPONSES
from app.llm.mock import MockProvider
from app.llm.openai import OpenAIProvider
from app.llm.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)

# Every live provider speaks the same LLMProvider protocol, so adding one is a
# registry entry rather than a branch in the pipeline.
LIVE_PROVIDERS = {
    "openrouter": OpenRouterProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}
KNOWN_PROVIDERS = {*LIVE_PROVIDERS, "mock"}


def get_llm_provider(request: Request):
    settings = get_settings()
    provider_cls = LIVE_PROVIDERS.get(settings.llm_provider)
    if provider_cls is not None:
        try:
            return provider_cls(settings)
        except LLMConfigError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    if settings.llm_provider not in KNOWN_PROVIDERS:
        # Falling through to the demo would answer every scenario with the
        # canned Bengaluru career response at HTTP 200 - a silent wrong answer.
        supported = ", ".join(sorted(KNOWN_PROVIDERS))
        logger.error(
            "LLM_PROVIDER=%r is not recognised; refusing to serve canned demo answers. "
            "Set LLM_PROVIDER to one of: %s (a live provider also needs its API key).",
            settings.llm_provider,
            supported,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                f"unknown LLM provider '{settings.llm_provider}'; "
                f"set LLM_PROVIDER to one of: {supported}"
            ),
        )

    return MockProvider(dict(DEMO_RESPONSES))


def provider_is_mock(provider) -> bool:
    """True when the response came from canned fixtures, not a live model."""
    return getattr(provider, "provider_id", None) == "mock"
