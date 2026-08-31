from app.core.config import Settings
from app.llm.base import GenerationUsage, LLMConfigError
from app.llm.http_provider import HTTPChatProvider


class AnthropicProvider(HTTPChatProvider):
    """Provider adapter for the Anthropic Messages API.

    Shares the retry ladder, schema repair and in-body error detection with
    every other HTTP provider. The Messages API differs from the OpenAI-shaped
    ones in four ways, all handled here:

    - the system prompt is a top-level field, not a message with role "system"
    - `max_tokens` is required, not optional
    - auth is `x-api-key` plus a pinned `anthropic-version`, not a bearer token
    - content comes back as a list of typed blocks, not a single string
    """

    provider_id = "anthropic"
    label = "Anthropic"

    def __init__(self, settings: Settings):
        if not settings.anthropic_api_key:
            raise LLMConfigError("ANTHROPIC_API_KEY is not configured")
        super().__init__(settings)

    def _endpoint(self) -> str:
        return f"{self._settings.anthropic_base_url}/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._settings.anthropic_api_key or "",
            "anthropic-version": self._settings.anthropic_version,
            "Content-Type": "application/json",
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
            # Required by the Messages API. Too low truncates a graph mid-JSON,
            # which the schema-repair loop would then burn attempts on.
            "max_tokens": self._settings.anthropic_max_tokens,
            "system": system_prompt,
            "messages": messages,
            "temperature": temperature,
        }

    def _extract_text(self, body: dict) -> str:
        """Concatenate the text blocks of a Messages API response.

        Content is a list of typed blocks; a thinking-enabled model puts a
        `thinking` block before the answer, so filtering by type - rather than
        taking content[0] - is what keeps this correct on those models.
        """
        blocks = body["content"]
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not text:
            # Not a KeyError case: the response was well-formed but carried no
            # text, so report the shape rather than raising a confusing KeyError.
            raise TypeError(f"no text block in Anthropic response: {blocks}")
        return text

    def _extract_usage(self, body: dict) -> GenerationUsage:
        raw = body.get("usage") or {}
        input_tokens = raw.get("input_tokens")
        output_tokens = raw.get("output_tokens")
        # The Messages API reports the two halves but no total, so it is derived
        # rather than left null - the pipeline records totals per execution.
        total = (
            input_tokens + output_tokens
            if isinstance(input_tokens, int) and isinstance(output_tokens, int)
            else None
        )
        return GenerationUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
        )
