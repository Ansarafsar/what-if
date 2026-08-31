"""Shared retry/parse machinery for HTTP chat-completion providers.

OpenRouter, OpenAI and Anthropic differ only in their endpoint, auth header,
request body and response shape. Everything that makes a provider *reliable* -
the backoff ladder, Retry-After handling, jitter, in-body error detection and
schema repair - is identical, and duplicating it per provider is how one copy
silently drifts and loses a fix the others have.

Subclasses supply the wire format; this base owns the failure behaviour.
"""

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.llm.base import GenerationResult, GenerationUsage, LLMValidationError
from app.llm.json_utils import extract_json_object

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
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


def body_error_code(body: object) -> int | None:
    """The HTTP-like status nested inside a 200 response, if there is one.

    OpenRouter fronts other providers; when one of them fails, the failure comes
    back as a normal 200 whose body is `{"error": {"code": 429, ...}}`.
    """
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    if isinstance(code, bool):
        return None
    if isinstance(code, int):
        return code
    if isinstance(code, str) and code.isdigit():
        return int(code)
    return None


def compute_backoff(attempt: int, retry_after: str | None) -> tuple[float, str]:
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


class HTTPChatProvider(ABC):
    """Base for providers speaking a JSON chat-completions HTTP API.

    Retries transient upstream errors (429, 502, 503, 504 - whether reported as
    the HTTP status or nested in a 200 body) with exponential backoff, and
    repairs schema violations by feeding the validation error back to the model.
    """

    #: Human-readable name used in error messages and logs.
    label: str = "LLM"

    def __init__(self, settings: Settings):
        self._settings = settings
        self.model = settings.llm_model

    # --- wire format, supplied by each provider -----------------------------

    @abstractmethod
    def _endpoint(self) -> str:
        """Absolute URL of the chat-completions endpoint."""

    @abstractmethod
    def _headers(self) -> dict[str, str]:
        """Auth and content headers for the request."""

    @abstractmethod
    def _payload(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> dict:
        """Request body. `messages` holds only the user/assistant turns."""

    @abstractmethod
    def _extract_text(self, body: dict) -> str:
        """The assistant's text content from a successful response body."""

    @abstractmethod
    def _extract_usage(self, body: dict) -> GenerationUsage:
        """Token accounting from a successful response body."""

    # --- shared behaviour ---------------------------------------------------

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
        stage: str,
        temperature: float = 0.4,
    ) -> GenerationResult:
        messages = [{"role": "user", "content": user_prompt}]
        feedback = ""
        last_raw: str | None = None
        retries = 0
        usage: GenerationUsage | None = None
        max_attempts = self._settings.llm_max_retries + 1

        for attempt in range(max_attempts):
            payload_messages = list(messages)
            if feedback:
                payload_messages.append({"role": "user", "content": feedback})

            started = time.perf_counter()
            try:
                async with httpx.AsyncClient(
                    timeout=self._settings.llm_request_timeout_seconds
                ) as client:
                    response = await client.post(
                        self._endpoint(),
                        headers=self._headers(),
                        json=self._payload(
                            system_prompt=system_prompt,
                            messages=payload_messages,
                            temperature=temperature,
                        ),
                    )
            except httpx.HTTPError as exc:
                if attempt < max_attempts - 1:
                    retries += 1
                    backoff, _ = compute_backoff(attempt, None)
                    logger.warning(
                        "stage=%s attempt=%d/%d network error: %s - retrying in %.1fs",
                        stage, attempt + 1, max_attempts, exc, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise LLMValidationError(
                    f"{self.label} request failed after {max_attempts} attempts: {exc}"
                ) from exc

            latency_ms = int((time.perf_counter() - started) * 1000)

            # Error responses are not always JSON - gateways return HTML and
            # plain text - so the body is decoded defensively, never assumed.
            try:
                body = response.json()
            except ValueError:
                body = {"error": response.text[:300]}

            # A proxy in front of the real provider can report a failure as
            # HTTP 200 with the real status nested in the body:
            #   {"error": {"message": "Provider returned error", "code": 429}}
            # Reading only response.status_code treats that as a malformed
            # payload and fails immediately, spending none of the retry budget
            # on what is really a rate limit.
            code_in_body = body_error_code(body)
            if code_in_body is not None and response.status_code < 400:
                if code_in_body in RETRYABLE_STATUS_CODES and attempt < max_attempts - 1:
                    retries += 1
                    backoff, source = compute_backoff(
                        attempt, response.headers.get("retry-after")
                    )
                    logger.warning(
                        "stage=%s attempt=%d/%d upstream error %d in body - retrying in %.1fs (%s)",
                        stage, attempt + 1, max_attempts, code_in_body, backoff, source,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise LLMValidationError(
                    f"{self.label} upstream returned {code_in_body} after "
                    f"{attempt + 1} attempt(s): {body.get('error')}"
                )

            # Retry on transient upstream errors (429, 502, 503, 504)
            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt < max_attempts - 1:
                    retries += 1
                    backoff, source = compute_backoff(
                        attempt, response.headers.get("retry-after")
                    )
                    logger.warning(
                        "stage=%s attempt=%d/%d HTTP %d - retrying in %.1fs (%s)",
                        stage, attempt + 1, max_attempts, response.status_code, backoff, source,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise LLMValidationError(
                    f"{self.label} returned HTTP {response.status_code} after "
                    f"{max_attempts} attempts: {body.get('error', body)}"
                )

            # Non-retryable HTTP error
            if response.status_code >= 400:
                raise LLMValidationError(
                    f"{self.label} returned HTTP {response.status_code}: "
                    f"{response.text[:300]}"
                )

            try:
                last_raw = self._extract_text(body)
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMValidationError(
                    f"unexpected {self.label} response shape: {body}"
                ) from exc

            usage = self._extract_usage(body)

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
                    # No backoff here: a schema violation is the model's fault,
                    # not the server's, so sleeping would waste the caller's time.
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
