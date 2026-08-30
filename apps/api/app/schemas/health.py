from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str


class ComponentHealth(BaseModel):
    status: str
    error: str | None = None


class ReadinessResponse(BaseModel):
    status: str
    components: dict[str, ComponentHealth]
