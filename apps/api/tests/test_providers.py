"""Unit tests for the OpenAI and Anthropic provider adapters.

The retry ladder itself is covered exhaustively in test_openrouter.py; since
every HTTP provider now shares one implementation, the tests here focus on what
is genuinely per-provider - the wire format each one speaks - plus enough of the
failover path to prove the shared machinery is actually wired in.
"""

import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMConfigError, LLMValidationError
from app.llm.openai import OpenAIProvider


class Payload(BaseModel):
    answer: str


def settings(**overrides) -> Settings:
    base = {
        "openai_api_key": "test-openai-key",
        "anthropic_api_key": "test-anthropic-key",
        "llm_max_retries": 2,
        "llm_model": "test-model",
        "llm_request_timeout_seconds": 5.0,
    }
    base.update(overrides)
    return Settings(**base)


def openai_completion(content: str, usage: dict | None = None) -> dict:
    body = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return body


def anthropic_message(content: str, usage: dict | None = None) -> dict:
    body = {"content": [{"type": "text", "text": content}]}
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

        def body(self, index: int = 0) -> dict:
            return json.loads(self.requests[index].content)

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
    def test_openai_missing_key_is_refused_at_construction(self):
        with pytest.raises(LLMConfigError, match="OPENAI_API_KEY"):
            OpenAIProvider(settings(openai_api_key=None))

    def test_anthropic_missing_key_is_refused_at_construction(self):
        with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
            AnthropicProvider(settings(anthropic_api_key=None))

    def test_openai_uses_bearer_auth(self):
        headers = OpenAIProvider(settings())._headers()
        assert headers["Authorization"] == "Bearer test-openai-key"

    def test_anthropic_uses_api_key_header_and_pinned_version(self):
        headers = AnthropicProvider(settings())._headers()
        # The Messages API authenticates with x-api-key, not a bearer token, and
        # requires an explicit version.
        assert headers["x-api-key"] == "test-anthropic-key"
        assert headers["anthropic-version"] == "2023-06-01"
        assert "Authorization" not in headers

    def test_optional_openai_scoping_headers_are_omitted_when_unset(self):
        headers = OpenAIProvider(settings())._headers()
        assert "OpenAI-Organization" not in headers
        assert "OpenAI-Project" not in headers

    def test_openai_scoping_headers_are_sent_when_set(self):
        headers = OpenAIProvider(
            settings(openai_organization="org-1", openai_project="proj-1")
        )._headers()
        assert headers["OpenAI-Organization"] == "org-1"
        assert headers["OpenAI-Project"] == "proj-1"

    def test_endpoints(self):
        assert OpenAIProvider(settings())._endpoint().endswith("/v1/chat/completions")
        assert AnthropicProvider(settings())._endpoint().endswith("/v1/messages")


class TestOpenAIWireFormat:
    async def test_parses_and_reports_usage(self, transport):
        transport.push(
            httpx.Response(
                200,
                json=openai_completion(
                    json.dumps({"answer": "ok"}),
                    usage={"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
                ),
            )
        )
        result = await generate(OpenAIProvider(settings()))
        assert result.data.answer == "ok"
        assert result.usage.input_tokens == 11
        assert result.usage.output_tokens == 5
        assert result.usage.total_tokens == 16

    async def test_system_prompt_is_sent_as_a_message(self, transport):
        transport.push(httpx.Response(200, json=openai_completion(json.dumps({"answer": "ok"}))))
        await generate(OpenAIProvider(settings()))
        messages = transport.body()["messages"]
        assert messages[0] == {"role": "system", "content": "system"}
        assert messages[1]["role"] == "user"

    async def test_json_response_format_is_requested(self, transport):
        transport.push(httpx.Response(200, json=openai_completion(json.dumps({"answer": "ok"}))))
        await generate(OpenAIProvider(settings()))
        assert transport.body()["response_format"] == {"type": "json_object"}

    async def test_temperature_is_sent_for_standard_models(self, transport):
        transport.push(httpx.Response(200, json=openai_completion(json.dumps({"answer": "ok"}))))
        await generate(OpenAIProvider(settings(llm_model="gpt-4o")))
        assert "temperature" in transport.body()

    @pytest.mark.parametrize("model", ["o1-mini", "o3", "o4-mini", "gpt-5"])
    async def test_temperature_is_omitted_for_reasoning_models(self, transport, model):
        # These models reject an explicit temperature with a 400, which no amount
        # of retrying would fix.
        transport.push(httpx.Response(200, json=openai_completion(json.dumps({"answer": "ok"}))))
        await generate(OpenAIProvider(settings(llm_model=model)))
        assert "temperature" not in transport.body()


class TestAnthropicWireFormat:
    async def test_parses_and_reports_usage(self, transport):
        transport.push(
            httpx.Response(
                200,
                json=anthropic_message(
                    json.dumps({"answer": "ok"}),
                    usage={"input_tokens": 30, "output_tokens": 12},
                ),
            )
        )
        result = await generate(AnthropicProvider(settings()))
        assert result.data.answer == "ok"
        assert result.usage.input_tokens == 30
        assert result.usage.output_tokens == 12
        # The Messages API reports no total, so it is derived.
        assert result.usage.total_tokens == 42

    async def test_missing_usage_is_tolerated(self, transport):
        transport.push(httpx.Response(200, json=anthropic_message(json.dumps({"answer": "ok"}))))
        result = await generate(AnthropicProvider(settings()))
        assert result.usage.total_tokens is None

    async def test_system_prompt_is_top_level_not_a_message(self, transport):
        transport.push(httpx.Response(200, json=anthropic_message(json.dumps({"answer": "ok"}))))
        await generate(AnthropicProvider(settings()))
        body = transport.body()
        assert body["system"] == "system"
        # A "system" role inside messages is rejected by the Messages API.
        assert all(m["role"] != "system" for m in body["messages"])

    async def test_max_tokens_is_always_sent(self, transport):
        # Required by the Messages API - omitting it is a 400 on every request.
        transport.push(httpx.Response(200, json=anthropic_message(json.dumps({"answer": "ok"}))))
        await generate(AnthropicProvider(settings(anthropic_max_tokens=4096)))
        assert transport.body()["max_tokens"] == 4096

    async def test_text_blocks_are_concatenated_past_a_thinking_block(self, transport):
        # A thinking-enabled model puts a non-text block first; taking content[0]
        # would read the reasoning instead of the answer.
        transport.push(
            httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "thinking", "thinking": "considering..."},
                        {"type": "text", "text": json.dumps({"answer": "ok"})},
                    ]
                },
            )
        )
        result = await generate(AnthropicProvider(settings()))
        assert result.data.answer == "ok"

    async def test_response_without_a_text_block_is_reported(self, transport):
        transport.push(
            httpx.Response(200, json={"content": [{"type": "thinking", "thinking": "..."}]})
        )
        with pytest.raises(LLMValidationError, match="unexpected Anthropic response shape"):
            await generate(AnthropicProvider(settings()))


class TestSharedFailoverIsWiredIn:
    """The ladder is tested in depth elsewhere; this proves each adapter uses it."""

    @pytest.mark.parametrize("status", [429, 502, 503, 504])
    async def test_openai_retries_transient_statuses(self, transport, status):
        transport.push(
            httpx.Response(status, json={"error": "slow down"}),
            httpx.Response(200, json=openai_completion(json.dumps({"answer": "ok"}))),
        )
        result = await generate(OpenAIProvider(settings()))
        assert result.data.answer == "ok"
        assert result.retries == 1

    @pytest.mark.parametrize("status", [429, 502, 503, 504])
    async def test_anthropic_retries_transient_statuses(self, transport, status):
        transport.push(
            httpx.Response(status, json={"error": "overloaded"}),
            httpx.Response(200, json=anthropic_message(json.dumps({"answer": "ok"}))),
        )
        result = await generate(AnthropicProvider(settings()))
        assert result.data.answer == "ok"
        assert result.retries == 1

    async def test_openai_repairs_a_schema_violation_without_sleeping(
        self, transport, no_sleep
    ):
        transport.push(
            httpx.Response(200, json=openai_completion("not json at all")),
            httpx.Response(200, json=openai_completion(json.dumps({"answer": "ok"}))),
        )
        result = await generate(OpenAIProvider(settings()))
        assert result.data.answer == "ok"
        # A schema error is the model's fault, not the server's - no backoff.
        assert no_sleep == []

    async def test_anthropic_repairs_a_schema_violation(self, transport):
        transport.push(
            httpx.Response(200, json=anthropic_message("not json at all")),
            httpx.Response(200, json=anthropic_message(json.dumps({"answer": "ok"}))),
        )
        result = await generate(AnthropicProvider(settings()))
        assert result.data.answer == "ok"
        assert result.retries == 1

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    async def test_client_errors_fail_immediately(self, transport, status):
        transport.push(httpx.Response(status, json={"error": {"message": "nope"}}))
        with pytest.raises(LLMValidationError, match=str(status)):
            await generate(OpenAIProvider(settings()))
        assert len(transport.requests) == 1

    async def test_network_error_is_retried(self, transport):
        transport.push(
            httpx.ConnectError("connection reset"),
            httpx.Response(200, json=anthropic_message(json.dumps({"answer": "ok"}))),
        )
        result = await generate(AnthropicProvider(settings()))
        assert result.retries == 1

    async def test_in_body_error_code_is_retried(self, transport):
        # A gateway in front of either provider can report a failure as HTTP 200
        # with the real status nested in the body.
        transport.push(
            httpx.Response(200, json={"error": {"message": "rate limited", "code": 429}}),
            httpx.Response(200, json=openai_completion(json.dumps({"answer": "ok"}))),
        )
        result = await generate(OpenAIProvider(settings()))
        assert result.data.answer == "ok"
        assert result.retries == 1

    async def test_error_messages_name_the_provider(self, transport):
        transport.push(httpx.Response(400, json={"error": "bad"}))
        with pytest.raises(LLMValidationError, match="Anthropic"):
            await generate(AnthropicProvider(settings()))
