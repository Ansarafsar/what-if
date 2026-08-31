"""Unit tests for the OpenRouter retry ladder and schema-repair loop.

This is the most failure-prone code in the repo - it is the only place that
touches a network, and every failure mode it handles is one a user hits on a
bad day. Backoff sleeps are patched out so the ladder is asserted, not waited on.
"""

import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.llm.base import LLMConfigError, LLMValidationError
from app.llm.openrouter import (
    _JITTER_RATIO,
    _MAX_BACKOFF,
    _MAX_RETRY_AFTER,
    OpenRouterProvider,
    _compute_backoff,
)


def assert_backoff(actual: float, base: float) -> None:
    """Backoff is `base` plus up to _JITTER_RATIO of jitter."""
    assert base <= actual <= base * (1 + _JITTER_RATIO), f"{actual} not in jitter range of {base}"


class Payload(BaseModel):
    answer: str


def settings(**overrides) -> Settings:
    base = {
        "openrouter_api_key": "test-key",
        "llm_max_retries": 2,
        "llm_model": "test/model",
        "llm_request_timeout_seconds": 5.0,
    }
    base.update(overrides)
    return Settings(**base)


def completion(content: str, usage: dict | None = None) -> dict:
    body = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return body


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Assert the backoff schedule without waiting for it."""
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("app.llm.http_provider.asyncio.sleep", fake_sleep)
    return slept


@pytest.fixture()
def transport(monkeypatch):
    """Queue of responses (or exceptions) the provider will receive in order."""

    class Queue:
        def __init__(self):
            self.responses = []
            self.requests: list[httpx.Request] = []

        def push(self, *items):
            self.responses.extend(items)

    queue = Queue()

    def handler(request: httpx.Request) -> httpx.Response:
        queue.requests.append(request)
        item = queue.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.llm.http_provider.httpx.AsyncClient", patched)
    return queue


async def generate(provider, stage="test_stage"):
    return await provider.generate_structured(
        system_prompt="system",
        user_prompt="user",
        schema=Payload,
        stage=stage,
    )


class TestConfiguration:
    def test_missing_api_key_is_refused_at_construction(self):
        with pytest.raises(LLMConfigError):
            OpenRouterProvider(settings(openrouter_api_key=None))

    def test_headers_carry_the_key(self):
        provider = OpenRouterProvider(settings())
        assert provider._headers()["Authorization"] == "Bearer test-key"


class TestHappyPath:
    async def test_parses_and_reports_usage(self, transport):
        transport.push(
            httpx.Response(
                200,
                json=completion(
                    json.dumps({"answer": "ok"}),
                    usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                ),
            )
        )
        result = await generate(OpenRouterProvider(settings()))

        assert result.data.answer == "ok"
        assert result.retries == 0
        assert result.usage.input_tokens == 11
        assert result.usage.output_tokens == 7
        assert result.model == "test/model"

    async def test_json_wrapped_in_prose_is_recovered(self, transport):
        transport.push(
            httpx.Response(
                200,
                json=completion('Here you go:\n```json\n{"answer": "ok"}\n```\nHope that helps!'),
            )
        )
        result = await generate(OpenRouterProvider(settings()))
        assert result.data.answer == "ok"

    async def test_missing_usage_block_is_tolerated(self, transport):
        transport.push(httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))))
        result = await generate(OpenRouterProvider(settings()))
        assert result.usage.input_tokens is None


class TestRetryLadder:
    async def test_429_is_retried_then_succeeds(self, transport, no_sleep):
        transport.push(
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        result = await generate(OpenRouterProvider(settings()))

        assert result.data.answer == "ok"
        assert result.retries == 1
        assert len(no_sleep) == 1
        assert_backoff(no_sleep[0], 2.0)

    @pytest.mark.parametrize("status", [429, 502, 503, 504])
    async def test_all_transient_statuses_are_retried(self, transport, status):
        transport.push(
            httpx.Response(status, json={"error": "transient"}),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        result = await generate(OpenRouterProvider(settings()))
        assert result.retries == 1

    async def test_backoff_is_exponential_and_capped(self, transport, no_sleep):
        transport.push(*[httpx.Response(503, json={"error": "down"}) for _ in range(5)])
        with pytest.raises(LLMValidationError):
            await generate(OpenRouterProvider(settings(llm_max_retries=4)))

        assert len(no_sleep) == 4
        for actual, base in zip(no_sleep, [2.0, 4.0, 8.0, 16.0]):
            assert_backoff(actual, base)

    async def test_retry_after_header_overrides_backoff(self, transport, no_sleep):
        transport.push(
            httpx.Response(429, json={"error": "slow down"}, headers={"retry-after": "12"}),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        await generate(OpenRouterProvider(settings()))
        assert_backoff(no_sleep[0], 12.0)

    async def test_garbage_retry_after_falls_back_to_backoff(self, transport, no_sleep):
        transport.push(
            httpx.Response(429, json={"error": "x"}, headers={"retry-after": "soon"}),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        await generate(OpenRouterProvider(settings()))
        assert_backoff(no_sleep[0], 2.0)

    async def test_http_date_retry_after_falls_back_to_backoff(self, transport, no_sleep):
        """HTTP-date form is legal but unparsed; our own schedule takes over."""
        transport.push(
            httpx.Response(
                429, json={"error": "x"}, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}
            ),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        await generate(OpenRouterProvider(settings()))
        assert_backoff(no_sleep[0], 2.0)

    async def test_shorter_retry_after_never_shortens_backoff(self, transport, no_sleep):
        transport.push(
            httpx.Response(429, json={"error": "x"}, headers={"retry-after": "0.5"}),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        await generate(OpenRouterProvider(settings()))
        assert_backoff(no_sleep[0], 2.0)

    async def test_long_retry_after_is_capped(self, transport, no_sleep):
        """A provider asking for an hour must not park the request for an hour."""
        transport.push(
            httpx.Response(429, json={"error": "x"}, headers={"retry-after": "3600"}),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        await generate(OpenRouterProvider(settings()))
        assert no_sleep[0] <= _MAX_RETRY_AFTER * (1 + _JITTER_RATIO)
        assert no_sleep[0] >= _MAX_RETRY_AFTER

    def test_jitter_never_pushes_the_delay_past_the_cap(self):
        """Jitter applied after the cap would make the documented 30s a lie."""
        for attempt in range(8):
            delays = [_compute_backoff(attempt, None)[0] for _ in range(200)]
            assert max(delays) <= _MAX_BACKOFF

    def test_retry_after_ceiling_includes_jitter(self):
        delays = [_compute_backoff(0, "3600")[0] for _ in range(200)]
        assert max(delays) <= _MAX_RETRY_AFTER

    def test_source_names_whichever_value_actually_won(self):
        """A Retry-After shorter than our own backoff does not set the delay,
        so the log must not claim the server chose it."""
        _, source = _compute_backoff(2, "1")
        assert source == "exponential"
        _, source = _compute_backoff(0, "60")
        assert source == "retry-after"

    async def test_jitter_desynchronises_concurrent_retries(self):
        """Consequence generation fans out per branch; identical delays would
        make every branch retry on the same tick and rate-limit again."""
        delays = {_compute_backoff(2, None)[0] for _ in range(20)}
        assert len(delays) > 1, "backoff is not jittered"
        assert all(_MAX_BACKOFF >= d >= 8.0 for d in delays)

    async def test_exhausted_retries_raise_with_status(self, transport):
        transport.push(*[httpx.Response(503, json={"error": "down"}) for _ in range(3)])
        with pytest.raises(LLMValidationError) as exc:
            await generate(OpenRouterProvider(settings()))
        assert "503" in str(exc.value)

    async def test_network_error_is_retried(self, transport, no_sleep):
        transport.push(
            httpx.ConnectError("connection reset"),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        result = await generate(OpenRouterProvider(settings()))
        assert result.retries == 1
        assert_backoff(no_sleep[0], 2.0)

    async def test_timeout_exhausts_and_raises(self, transport):
        transport.push(*[httpx.ReadTimeout("timed out") for _ in range(3)])
        with pytest.raises(LLMValidationError) as exc:
            await generate(OpenRouterProvider(settings()))
        assert "attempts" in str(exc.value)


class TestUpstreamErrorInBody:
    """OpenRouter proxies other providers. When one fails, the failure arrives
    as HTTP 200 with the real status nested in the body, so reading only
    response.status_code spends none of the retry budget on a rate limit.
    """

    # The exact body a live run returned.
    LIVE_BODY = {"error": {"message": "Provider returned error", "code": 429}}

    async def test_in_body_429_is_retried(self, transport, no_sleep):
        transport.push(
            httpx.Response(200, json=self.LIVE_BODY),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        result = await generate(OpenRouterProvider(settings()))

        assert result.data.answer == "ok"
        assert result.retries == 1
        assert_backoff(no_sleep[0], 2.0)

    async def test_in_body_429_is_not_reported_as_a_malformed_payload(self, transport):
        transport.push(*[httpx.Response(200, json=self.LIVE_BODY) for _ in range(3)])
        with pytest.raises(LLMValidationError) as exc:
            await generate(OpenRouterProvider(settings()))

        message = str(exc.value)
        assert "429" in message
        assert "unexpected OpenRouter response shape" not in message

    @pytest.mark.parametrize("code", [429, 502, 503, 504])
    async def test_every_transient_code_in_body_is_retried(self, transport, code):
        transport.push(
            httpx.Response(200, json={"error": {"message": "upstream", "code": code}}),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        assert (await generate(OpenRouterProvider(settings()))).retries == 1

    async def test_string_code_is_understood(self, transport):
        transport.push(
            httpx.Response(200, json={"error": {"message": "upstream", "code": "429"}}),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        assert (await generate(OpenRouterProvider(settings()))).retries == 1

    async def test_non_transient_code_in_body_fails_without_retrying(self, transport, no_sleep):
        transport.push(httpx.Response(200, json={"error": {"message": "bad key", "code": 401}}))
        with pytest.raises(LLMValidationError) as exc:
            await generate(OpenRouterProvider(settings()))

        assert "401" in str(exc.value)
        assert no_sleep == []
        assert len(transport.requests) == 1

    async def test_a_normal_completion_is_untouched(self, transport):
        """A successful body has no error key and must not be misread."""
        transport.push(httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))))
        assert (await generate(OpenRouterProvider(settings()))).data.answer == "ok"

    async def test_a_plain_string_error_is_not_mistaken_for_a_code(self, transport, no_sleep):
        """Our own non-JSON fallback stores `{"error": "<text>"}`, whose value is
        a string with no code. It must fall through to the shape check rather
        than being read as a retryable upstream status."""
        transport.push(httpx.Response(200, text="not json at all"))
        with pytest.raises(LLMValidationError) as exc:
            await generate(OpenRouterProvider(settings()))

        assert "unexpected OpenRouter response shape" in str(exc.value)
        assert no_sleep == []  # not treated as a rate limit


class TestNonRetryable:
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    async def test_client_errors_fail_immediately(self, transport, status, no_sleep):
        transport.push(httpx.Response(status, text="nope"))
        with pytest.raises(LLMValidationError) as exc:
            await generate(OpenRouterProvider(settings()))

        assert str(status) in str(exc.value)
        assert no_sleep == []
        assert len(transport.requests) == 1

    async def test_non_json_error_body_does_not_crash(self, transport):
        """Gateways return HTML, not JSON. Decoding the body eagerly used to
        raise JSONDecodeError straight out of the provider."""
        transport.push(
            httpx.Response(502, html="<html><body>Bad Gateway</body></html>"),
            httpx.Response(502, html="<html><body>Bad Gateway</body></html>"),
            httpx.Response(502, html="<html><body>Bad Gateway</body></html>"),
        )
        with pytest.raises(LLMValidationError) as exc:
            await generate(OpenRouterProvider(settings()))
        assert "502" in str(exc.value)

    async def test_unexpected_response_shape_is_reported(self, transport):
        transport.push(httpx.Response(200, json={"unexpected": True}))
        with pytest.raises(LLMValidationError) as exc:
            await generate(OpenRouterProvider(settings()))
        assert "unexpected OpenRouter response shape" in str(exc.value)


class TestSchemaRepairLoop:
    async def test_invalid_json_triggers_a_repair_attempt(self, transport):
        transport.push(
            httpx.Response(200, json=completion("not json at all")),
            httpx.Response(200, json=completion(json.dumps({"answer": "repaired"}))),
        )
        result = await generate(OpenRouterProvider(settings()))

        assert result.data.answer == "repaired"
        assert result.retries == 1

    async def test_repair_feedback_is_appended_to_the_conversation(self, transport):
        transport.push(
            httpx.Response(200, json=completion(json.dumps({"wrong_key": 1}))),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        await generate(OpenRouterProvider(settings()))

        first, second = (json.loads(r.content)["messages"] for r in transport.requests)
        assert len(first) == 2
        assert len(second) == 3
        assert "could not be parsed" in second[-1]["content"]

    async def test_schema_mismatch_exhausts_and_keeps_last_raw_output(self, transport):
        transport.push(*[
            httpx.Response(200, json=completion(json.dumps({"wrong_key": i})))
            for i in range(3)
        ])
        with pytest.raises(LLMValidationError) as exc:
            await generate(OpenRouterProvider(settings()))

        assert "failed schema validation" in str(exc.value)
        assert exc.value.last_raw_output == json.dumps({"wrong_key": 2})

    async def test_repair_does_not_sleep(self, transport, no_sleep):
        """A schema error is the model's fault, not the server's - retry now."""
        transport.push(
            httpx.Response(200, json=completion("garbage")),
            httpx.Response(200, json=completion(json.dumps({"answer": "ok"}))),
        )
        await generate(OpenRouterProvider(settings()))
        assert no_sleep == []

    async def test_retries_zero_means_one_attempt(self, transport):
        transport.push(httpx.Response(200, json=completion("garbage")))
        with pytest.raises(LLMValidationError):
            await generate(OpenRouterProvider(settings(llm_max_retries=0)))
        assert len(transport.requests) == 1
