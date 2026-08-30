from pydantic import BaseModel, ValidationError

from app.llm.base import GenerationResult, LLMValidationError


class MockProvider:
    """Deterministic provider returning canned responses keyed by stage.

    Used for tests and keyless demos. Responses are validated against the
    requested schema exactly like a live provider, so fixtures stay honest.
    """

    provider_id = "mock"

    def __init__(self, responses: dict[str, dict]):
        self.responses = responses
        self.calls: list[str] = []

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
        stage: str,
        temperature: float = 0.4,
    ) -> GenerationResult:
        self.calls.append(stage)
        if stage not in self.responses:
            raise LLMValidationError(f"MockProvider has no canned response for stage '{stage}'")
        try:
            data = schema.model_validate(self.responses[stage])
        except ValidationError as exc:
            raise LLMValidationError(
                f"MockProvider canned response for '{stage}' is invalid: {exc}"
            ) from exc
        return GenerationResult(
            data=data,
            model="mock",
            stage=stage,
            latency_ms=1,
            retries=0,
            usage=None,
        )
