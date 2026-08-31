import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import LIVE_PROVIDERS
from app.api.routes import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.middleware import request_context_middleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Only a live provider escapes the demo warning; an unrecognised value is
    # refused per-request in deps.get_llm_provider rather than served fixtures.
    if settings.llm_provider not in LIVE_PROVIDERS:
        logger.warning(
            "=" * 72
            + "\nLLM_PROVIDER=%r - every scenario will be answered from canned demo "
            "fixtures,\nnot from a model. Responses are marked \"mock\": true. Set "
            "LLM_PROVIDER to one of: %s\n(with that provider's API key) for real "
            "reasoning.\n" + "=" * 72,
            settings.llm_provider,
            ", ".join(sorted(LIVE_PROVIDERS)),
        )
    yield


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    app = FastAPI(
        title="WHAT IF API",
        description=(
            "Counterfactual possibility explorer: fork reality, walk the branches, "
            "fork again."
        ),
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api/v1")

    app.middleware("http")(request_context_middleware)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "api": "/api/v1",
        }

    return app


app = create_app()
