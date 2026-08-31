from app.core.config import Settings
from app.llm.base import GenerationUsage, LLMConfigError
from app.llm.http_provider import (
    _INITIAL_BACKOFF,
    _JITTER_RATIO,
    _MAX_BACKOFF,
    _MAX_RETRY_AFTER,
    RETRYABLE_STATUS_CODES as _RETRYABLE_STATUS_CODES,
    HTTPChatProvider,
    body_error_code as _body_error_code,
    compute_backoff as _compute_backoff,
)

# The retry ladder moved to http_provider so every HTTP provider shares one
# implementation; these aliases keep the original import paths working.
__all__ = [
    "OpenRouterProvider",
    "_INITIAL_BACKOFF",
    "_JITTER_RATIO",
    "_MAX_BACKOFF",
    "_MAX_RETRY_AFTER",
    "_RETRYABLE_STATUS_CODES",
    "_body_error_code",
    "_compute_backoff",
]


class OpenRouterProvider(HTTPChatProvider):
    """Provider adapter for OpenRouter's OpenAI-compatible chat completions API.

    Retries on transient upstream errors (429, 502, 503, 504) with exponential
    backoff before giving up - including the ones OpenRouter reports as HTTP 200
    with the real status nested in the body, because it fronts other providers.
    """

    provider_id = "openrouter"
    label = "OpenRouter"

    def __init__(self, settings: Settings):
        if not settings.openrouter_api_key:
            raise LLMConfigError("OPENROUTER_API_KEY is not configured")
        super().__init__(settings)

    def _endpoint(self) -> str:
        return f"{self._settings.openrouter_base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/what-if",
            "X-Title": "WHAT IF",
        }

    def _payload(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> dict:
        return {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": temperature,
        }

    def _extract_text(self, body: dict) -> str:
        return body["choices"][0]["message"]["content"]

    def _extract_usage(self, body: dict) -> GenerationUsage:
        raw = body.get("usage") or {}
        return GenerationUsage(
            input_tokens=raw.get("prompt_tokens"),
            output_tokens=raw.get("completion_tokens"),
            total_tokens=raw.get("total_tokens"),
        )
