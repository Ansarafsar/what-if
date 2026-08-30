import logging

from fastapi import HTTPException, Request

from app.core.config import get_settings
from app.llm.base import LLMConfigError
from app.llm.demo_responses import DEMO_RESPONSES
from app.llm.mock import MockProvider
from app.llm.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)

KNOWN_PROVIDERS = {"openrouter", "mock"}


def get_llm_provider(request: Request):
    settings = get_settings()
    if settings.llm_provider == "openrouter":
        try:
            return OpenRouterProvider(settings)
        except LLMConfigError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    if settings.llm_provider not in KNOWN_PROVIDERS:
        # Falling through to the demo would answer every scenario with the
        # canned Bengaluru career response at HTTP 200 - a silent wrong answer.
        logger.error(
            "LLM_PROVIDER=%r is not recognised; refusing to serve canned demo answers. "
            "Set LLM_PROVIDER=openrouter (with OPENROUTER_API_KEY) or LLM_PROVIDER=mock.",
            settings.llm_provider,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                f"unknown LLM provider '{settings.llm_provider}'; "
                "set LLM_PROVIDER to 'openrouter' or 'mock'"
            ),
        )

    return MockProvider(dict(DEMO_RESPONSES))


def provider_is_mock(provider) -> bool:
    """True when the response came from canned fixtures, not a live model."""
    return getattr(provider, "provider_id", None) == "mock"
