from collections.abc import Generator
from contextlib import contextmanager

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.database import get_session_factory, session_scope
from app.schemas import ComponentHealth, HealthResponse, ReadinessResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )


@router.get("/ready", response_model=ReadinessResponse)
def ready(
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ReadinessResponse:
    components: dict[str, ComponentHealth] = {}

    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
            session.commit()
        components["database"] = ComponentHealth(status="ok")
    except Exception as exc:  # noqa: BLE001 - readiness must report, not raise
        components["database"] = ComponentHealth(status="error", error=str(exc))

    overall = "ok" if all(c.status == "ok" for c in components.values()) else "degraded"
    return ReadinessResponse(status=overall, components=components)
