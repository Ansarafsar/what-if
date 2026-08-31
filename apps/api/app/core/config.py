from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "whatif-api"
    app_version: str = "0.1.0"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://whatif:whatif@localhost:5432/whatif"

    cors_origins: list[str] = ["http://localhost:3000"]

    # LLM configuration
    # provider: openrouter | openai | anthropic (live) | mock (tests/demo)
    llm_provider: str = "mock"
    llm_model: str = "deepseek/deepseek-chat-v3-0324:free"
    llm_temperature_extraction: float = 0.2
    llm_temperature_generation: float = 0.7
    # Attempts = llm_max_retries + 1, covering both transient HTTP failures
    # (429/502/503/504, with exponential backoff + jitter) and schema-repair
    # rounds. Raising this helps on rate-limited free tiers, but the wait is
    # paid per branch, so worst-case generation latency rises with it.
    llm_max_retries: int = 2
    llm_request_timeout_seconds: float = 90.0

    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    # Optional scoping headers; only sent when set.
    openai_organization: str | None = None
    openai_project: str | None = None

    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    # Pinned rather than floating: an API version bump can change response
    # shapes, and this adapter parses them.
    anthropic_version: str = "2023-06-01"
    # Required by the Messages API. Generous enough for a full possibility
    # graph, since a truncated response fails schema validation.
    anthropic_max_tokens: int = 8192

    # Possibility engine tuning
    engine_beam_width: int = 6
    engine_min_candidates: int = 3
    # How many consequence orders the projection prompt is asked to reach.
    engine_max_causal_depth: int = 2
    engine_dedup_threshold: float = 0.72
    # Revise loop bound (PRD 22). 0 disables the loop entirely.
    engine_max_revise_iterations: int = 2
    # How deep the user may expand the possibility graph. Depth 0 is reality.
    engine_max_depth: int = 4

    # Deferred infrastructure (not used yet):
    # redis_url: str = "redis://localhost:6379/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
