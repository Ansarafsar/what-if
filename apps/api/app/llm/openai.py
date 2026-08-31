from app.core.config import Settings
from app.llm.base import GenerationUsage, LLMConfigError
from app.llm.http_provider import HTTPChatProvider


class OpenAIProvider(HTTPChatProvider):
    """Provider adapter for OpenAI's chat completions API.

    Shares the retry ladder, schema repair and in-body error detection with
    every other HTTP provider; only the wire format differs.
    """

    provider_id = "openai"
    label = "OpenAI"

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise LLMConfigError("OPENAI_API_KEY is not configured")
        super().__init__(settings)

    def _endpoint(self) -> str:
        return f"{self._settings.openai_base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        # Organisation and project scoping are optional; sending an empty header
        # is an auth error rather than a no-op, so they are only set when present.
        if self._settings.openai_organization:
            headers["OpenAI-Organization"] = self._settings.openai_organization
        if self._settings.openai_project:
            headers["OpenAI-Project"] = self._settings.openai_project
        return headers

    def _payload(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            # Ask for JSON at the protocol level rather than trusting the prompt.
            # The stages all request a JSON object, and json_utils still runs, so
            # a model that ignores this is handled exactly as before.
            "response_format": {"type": "json_object"},
        }
        # Reasoning models (o-series, gpt-5) reject an explicit temperature, so
        # the parameter is omitted for them rather than sent and 400'd.
        if not self._omits_temperature():
            payload["temperature"] = temperature
        return payload

    def _omits_temperature(self) -> bool:
        model = self.model.lower()
        return model.startswith(("o1", "o3", "o4", "gpt-5"))

    def _extract_text(self, body: dict) -> str:
        return body["choices"][0]["message"]["content"]

    def _extract_usage(self, body: dict) -> GenerationUsage:
        raw = body.get("usage") or {}
        return GenerationUsage(
            input_tokens=raw.get("prompt_tokens"),
            output_tokens=raw.get("completion_tokens"),
            total_tokens=raw.get("total_tokens"),
        )
