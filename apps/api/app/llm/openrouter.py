import asyncio
import logging
import random
import time

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.llm.base import GenerationResult, GenerationUsage, LLMConfigError, LLMValidationError
from app.llm.json_utils import extract_json_object

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_INITIAL_BACKOFF = 2.0
# Cap on backoff *we* choose. A server-supplied Retry-After overrides it: when a
# provider says "wait 60s", retrying at 30s just burns another 429.
_MAX_BACKOFF = 30.0
# Absolute ceiling on a single wait, including Retry-After. Past this the request
# is failed rather than parked - a caller waiting five minutes on one stage is
# worse than a clear error.
_MAX_RETRY_AFTER = 120.0
# Fraction of the delay added as random jitter. Consequence generation fans out
# one call per branch, so without jitter every branch retries in lockstep and
# rate-limits itself again on the same tick.
_JITTER_RATIO = 0.25


def _compute_backoff(attempt: int, retry_after: str | None) -> tuple[float, str]:
    """Delay before the next attempt, and why it was chosen.

    Exponential (2s, 4s, 8s, ...) capped at _MAX_BACKOFF, unless the server sent
    a Retry-After, which wins outright up to _MAX_RETRY_AFTER. Jitter is added to
    de-synchronise concurrent branch calls.
    """
    delay = min(_INITIAL_BACKOFF * (2**attempt), _MAX_BACKOFF)
    source = "exponential"
    ceiling = _MAX_BACKOFF

    if retry_after:
        try:
            requested = float(retry_after)
        except ValueError:
            # Retry-After may also be an HTTP-date; we do not parse those and
            # fall back to our own schedule rather than guessing.
            pass
        else:
            # Only credit the header when it actually wins - otherwise the log
            # would claim the server set a delay our own schedule chose.
            if requested > delay:
                delay = min(requested, _MAX_RETRY_AFTER)
                source = "retry-after"
                ceiling = _MAX_RETRY_AFTER

    # Jitter is applied inside the ceiling, so the documented cap is the real
    # worst case rather than the cap plus a jitter overshoot.
    jittered = min(delay + random.uniform(0, delay * _JITTER_RATIO), ceiling)
    return jittered, source


class OpenRouterProvider:
    """Provider adapter for OpenRouter's OpenAI-compatible chat completions API.

    Retries on transient upstream errors (429, 502, 503, 504) with
    exponential backoff before giving up.
    """

    def __init__(self, settings: Settings):
        if not settings.openrouter_api_key:
            raise LLMConfigError("OPENROUTER_API_KEY is not configured")
        self._settings = settings
        self.model = settings.llm_model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/what-if",
            "X-Title": "WHAT IF",
        }

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
        stage: str,
        temperature: float = 0.4,
    ) -> GenerationResult:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        feedback = ""
        last_raw: str | None = None
        retries = 0
        usage: GenerationUsage | None = None
        max_attempts = self._settings.llm_max_retries + 1

        for attempt in range(max_attempts):
            payload_messages = list(messages)
            if feedback:
                payload_messages.append(
                    {"role": "user", "content": feedback}
                )

            started = time.perf_counter()
            try:
                async with httpx.AsyncClient(
                    timeout=self._settings.llm_request_timeout_seconds
                ) as client:
                    response = await client.post(
                        f"{self._settings.openrouter_base_url}/chat/completions",
                        headers=self._headers(),
                        json={
                            "model": self.model,
                            "messages": payload_messages,
                            "temperature": temperature,
                        },
                    )
            except httpx.HTTPError as exc:
                if attempt < max_attempts - 1:
                    retries += 1
                    backoff, _ = _compute_backoff(attempt, None)
                    logger.warning(
                        "stage=%s attempt=%d/%d network error: %s - retrying in %.1fs",
                        stage, attempt + 1, max_attempts, exc, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise LLMValidationError(
                    f"OpenRouter request failed after {max_attempts} attempts: {exc}"
                ) from exc

            latency_ms = int((time.perf_counter() - started) * 1000)

            # Error responses are not always JSON - gateways return HTML and
            # plain text - so the body is decoded defensively, never assumed.
            try:
                body = response.json()
            except ValueError:
                body = {"error": response.text[:300]}

            # Retry on transient upstream errors (429, 502, 503, 504)
            if response.status_code in _RETRYABLE_STATUS_CODES:
                if attempt < max_attempts - 1:
                    retries += 1
                    backoff, source = _compute_backoff(
                        attempt, response.headers.get("retry-after")
                    )
                    logger.warning(
                        "stage=%s attempt=%d/%d HTTP %d - retrying in %.1fs (%s)",
                        stage, attempt + 1, max_attempts, response.status_code, backoff, source,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise LLMValidationError(
                    f"OpenRouter returned HTTP {response.status_code} after "
                    f"{max_attempts} attempts: {body.get('error', body)}"
                )

            # Non-retryable HTTP error
            if response.status_code >= 400:
                raise LLMValidationError(
                    f"OpenRouter returned HTTP {response.status_code}: "
                    f"{response.text[:300]}"
                )

            try:
                choice = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMValidationError(
                    f"unexpected OpenRouter response shape: {body}"
                ) from exc

            last_raw = choice
            raw_usage = body.get("usage") or {}
            usage = GenerationUsage(
                input_tokens=raw_usage.get("prompt_tokens"),
                output_tokens=raw_usage.get("completion_tokens"),
                total_tokens=raw_usage.get("total_tokens"),
            )

            try:
                parsed = extract_json_object(last_raw)
                data = schema.model_validate(parsed)
                if retries > 0:
                    logger.info(
                        "stage=%s succeeded on attempt %d/%d",
                        stage, attempt + 1, max_attempts,
                    )
                return GenerationResult(
                    data=data,
                    model=self.model,
                    stage=stage,
                    latency_ms=latency_ms,
                    retries=retries,
                    usage=usage,
                )
            except (ValueError, ValidationError) as exc:
                if attempt < max_attempts - 1:
                    retries += 1
                    feedback = (
                        "Your previous response could not be parsed into the required JSON "
                        f"schema. Error: {exc}\nRespond again with ONLY a valid JSON object "
                        "matching the requested shape. Do not add commentary."
                    )
                    logger.warning(
                        "stage=%s attempt=%d/%d schema validation failed: %s",
                        stage, attempt + 1, max_attempts, exc,
                    )
                    continue
                raise LLMValidationError(
                    f"stage '{stage}' failed schema validation after "
                    f"{max_attempts} attempts: {exc}",
                    last_raw_output=last_raw,
                ) from exc

        # Should not reach here, but safety net
        raise LLMValidationError(
            f"stage '{stage}' exhausted all {max_attempts} attempts"
        )
