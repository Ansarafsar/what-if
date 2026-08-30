from typing import Protocol, TypeVar, runtime_checkable
from uuid import UUID

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMConfigError(LLMError):
    pass


class LLMValidationError(LLMError):
    def __init__(self, message: str, last_raw_output: str | None = None):
        super().__init__(message)
        self.last_raw_output = last_raw_output


class GenerationUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class GenerationResult(BaseModel):
    data: BaseModel
    model: str
    stage: str
    latency_ms: int
    retries: int
    usage: GenerationUsage | None = None


@runtime_checkable
class LLMProvider(Protocol):
    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
        stage: str,
        temperature: float = 0.4,
    ) -> GenerationResult:
        ...


def provider_name(provider: LLMProvider) -> str:
    return type(provider).__name__
