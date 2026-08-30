import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_llm_provider, provider_is_mock
from app.core.config import get_settings
from app.core.database import get_db
from app.engines.comparison import compare_nodes
from app.graphs.expansion import run_expansion
from app.graphs.generation import run_generation, stream_generation
from app.llm.base import LLMError, LLMProvider
from app.schemas.domain import DomainType, RealityState
from app.services import scenario_service as service
from app.services.pipeline import PossibilityPipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


class ScenarioCreateRequest(BaseModel):
    input: str = Field(min_length=20, max_length=4000)
    domain: str | None = None


class ScenarioCreatedResponse(BaseModel):
    id: UUID
    status: str


class RealityResponse(BaseModel):
    scenario_id: UUID
    state: dict
    # True when the payload came from canned fixtures rather than a live model.
    mock: bool = False


class GraphSummaryResponse(BaseModel):
    scenario_id: UUID
    node_count: int
    edge_count: int
    branch_count: int
    branches: list[dict]
    mock: bool = False


class ExpandResponse(BaseModel):
    scenario_id: UUID
    node_id: UUID
    created: bool
    nodes: list[dict]
    edges: list[dict]
    mock: bool = False


class CompareRequest(BaseModel):
    node_ids: list[UUID] = Field(min_length=2, max_length=2)


def _require_scenario(session: Session, scenario_id: UUID):
    scenario = service.get_scenario(session, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    return scenario


def _branch_summaries(branches) -> list[dict]:
    return [
        {
            "label": b.candidate.label,
            "strategy": b.candidate.strategy,
            "plausibility": b.consequence.plausibility.value,
            "score": b.score,
            "reversible": b.candidate.reversible,
        }
        for b in branches
    ]


@router.post("", response_model=ScenarioCreatedResponse, status_code=201)
def create_scenario(payload: ScenarioCreateRequest, session: Session = Depends(get_db)):
    domain_value: str | None = None
    if payload.domain:
        try:
            domain_value = DomainType(payload.domain).value
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"unknown domain '{payload.domain}'") from exc
    scenario = service.create_scenario(session, payload.input, domain=domain_value)
    return ScenarioCreatedResponse(id=scenario.id, status=scenario.status)


@router.get("/{scenario_id}")
def get_scenario(scenario_id: UUID, session: Session = Depends(get_db)):
    scenario = _require_scenario(session, scenario_id)
    return {
        "id": scenario.id,
        "title": scenario.title,
        "domain": scenario.domain,
        "status": scenario.status,
        "created_at": scenario.created_at,
    }


@router.post("/{scenario_id}/extract", response_model=RealityResponse)
async def extract_reality(
    scenario_id: UUID,
    session: Session = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
):
    scenario = _require_scenario(session, scenario_id)
    pipeline = PossibilityPipeline(provider)
    forced_domain = DomainType(scenario.domain) if scenario.domain != "general" else None
    try:
        state = await pipeline.extract_reality(scenario.raw_input, domain_hint=forced_domain)
    except LLMError as exc:
        logger.error("LLMError in extract: %s", exc, exc_info=True)
        # The failed stage carries the retry count and error text; dropping it
        # leaves no record of why extraction failed.
        service.record_failed_executions(session, scenario_id, pipeline.executions)
        raise HTTPException(status_code=502, detail=f"reality extraction failed: {exc}") from exc
    except Exception as exc:
        logger.error("Unexpected error in extract: %s", exc, exc_info=True)
        service.record_failed_executions(session, scenario_id, pipeline.executions)
        raise HTTPException(status_code=500, detail=f"internal error: {exc}") from exc

    service.record_executions(session, scenario_id, pipeline.executions)
    version = service.save_reality_state(session, scenario_id, state)
    return RealityResponse(
        scenario_id=scenario_id,
        state={"version": version, **state.model_dump(mode="json")},
        mock=provider_is_mock(provider),
    )


@router.get("/{scenario_id}/reality", response_model=RealityResponse)
def get_reality(scenario_id: UUID, session: Session = Depends(get_db)):
    _require_scenario(session, scenario_id)
    state = service.get_latest_reality(session, scenario_id)
    if state is None:
        raise HTTPException(status_code=404, detail="no reality state extracted yet")
    return RealityResponse(scenario_id=scenario_id, state=state.model_dump(mode="json"))


@router.post("/{scenario_id}/generate", response_model=GraphSummaryResponse)
async def generate_possibilities(
    scenario_id: UUID,
    session: Session = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
):
    _require_scenario(session, scenario_id)
    state = service.get_latest_reality(session, scenario_id)
    if state is None:
        raise HTTPException(status_code=409, detail="extract reality before generating possibilities")

    state.scenario_id = scenario_id
    pipeline = PossibilityPipeline(provider)
    try:
        outcome = await run_generation(pipeline, scenario_id, state)
    except LLMError as exc:
        # Without this the only trace of a production failure is a 502 status
        # line, which is not enough to tell a rate limit from a broken prompt.
        logger.error("generation failed for %s: %s", scenario_id, exc, exc_info=True)
        service.record_failed_executions(session, scenario_id, pipeline.executions)
        raise HTTPException(status_code=502, detail=f"possibility generation failed: {exc}") from exc
    except ValueError as exc:
        logger.warning("generation rejected for %s: %s", scenario_id, exc)
        service.record_failed_executions(session, scenario_id, pipeline.executions)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    service.record_executions(session, scenario_id, outcome.executions)
    service.save_graph(session, outcome)

    return GraphSummaryResponse(
        scenario_id=scenario_id,
        node_count=len(outcome.graph.nodes),
        edge_count=len(outcome.graph.edges),
        branch_count=len(outcome.branches),
        branches=_branch_summaries(outcome.branches),
        mock=provider_is_mock(provider),
    )


@router.post("/{scenario_id}/generate/stream")
async def generate_possibilities_stream(
    scenario_id: UUID,
    session: Session = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
):
    """Server-sent events, one per completed graph stage.

    Same work as POST /generate; the difference is that the client learns which
    stage the engine is actually on instead of guessing on a timer.
    """
    _require_scenario(session, scenario_id)
    state = service.get_latest_reality(session, scenario_id)
    if state is None:
        raise HTTPException(status_code=409, detail="extract reality before generating possibilities")

    state.scenario_id = scenario_id
    pipeline = PossibilityPipeline(provider)
    is_mock = provider_is_mock(provider)

    async def events():
        def sse(payload: dict) -> str:
            return f"data: {json.dumps(payload, default=str)}\n\n"

        try:
            async for event in stream_generation(pipeline, scenario_id, state):
                if event["type"] != "complete":
                    yield sse(event)
                    continue

                outcome = event.pop("outcome")
                service.record_executions(session, scenario_id, outcome.executions)
                service.save_graph(session, outcome)
                session.commit()
                yield sse(
                    {
                        **event,
                        "branches": _branch_summaries(outcome.branches),
                        "mock": is_mock,
                    }
                )
        except (LLMError, ValueError) as exc:
            service.record_failed_executions(session, scenario_id, pipeline.executions)
            logger.error("generation stream failed: %s", exc, exc_info=True)
            yield sse({"type": "error", "detail": str(exc)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{scenario_id}/graph")
def get_graph(scenario_id: UUID, session: Session = Depends(get_db)):
    _require_scenario(session, scenario_id)
    graph = service.get_graph(session, scenario_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="possibility graph not generated yet")
    return graph.model_dump(mode="json")


@router.get("/{scenario_id}/nodes/{node_id}")
def get_node(scenario_id: UUID, node_id: UUID, session: Session = Depends(get_db)):
    _require_scenario(session, scenario_id)
    row = service.get_node(session, scenario_id, node_id)
    if row is None:
        raise HTTPException(status_code=404, detail="node not found")
    children = service.get_children(session, node_id)
    return {
        "id": row.id,
        "scenario_id": row.scenario_id,
        "parent_id": row.parent_id,
        "node_type": row.node_type,
        "title": row.title,
        "description": row.description,
        "plausibility": row.plausibility,
        "score": row.score,
        "depth": row.depth,
        "expanded_at": row.expanded_at,
        "child_ids": [c.id for c in children],
        "metadata": row.node_metadata or {},
    }


@router.post("/{scenario_id}/nodes/{node_id}/expand", response_model=ExpandResponse)
async def expand_node(
    scenario_id: UUID,
    node_id: UUID,
    session: Session = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
):
    """Generate this node's children from this node's own world state.

    Idempotent by design (PRD 70): a node that already has children returns them
    without touching the LLM, so re-clicking a branch is free.
    """
    _require_scenario(session, scenario_id)
    row = service.get_node(session, scenario_id, node_id)
    if row is None:
        raise HTTPException(status_code=404, detail="node not found")
    if row.node_type != "state":
        raise HTTPException(
            status_code=422, detail="only outcome nodes can be expanded; pick a branch, not a fork"
        )

    metadata = row.node_metadata or {}
    settings = get_settings()

    existing = service.get_children(session, node_id)
    if existing:
        node_ids = {c.id for c in existing}
        descendants = service.get_children(session, existing[0].id) if existing else []
        node_ids |= {d.id for d in descendants}
        edges = service.get_subtree_edges(session, scenario_id, node_ids | {node_id})
        graph = service.graph_from_rows([*existing, *descendants], edges)
        return ExpandResponse(
            scenario_id=scenario_id,
            node_id=node_id,
            created=False,
            nodes=[n.model_dump(mode="json") for n in graph.nodes],
            edges=[e.model_dump(mode="json") for e in graph.edges],
            mock=provider_is_mock(provider),
        )

    depth = row.depth or int(metadata.get("depth", 0) or 0)
    if depth + 2 > settings.engine_max_depth:
        raise HTTPException(
            status_code=422,
            detail=f"maximum exploration depth {settings.engine_max_depth} reached",
        )

    raw_state = metadata.get("resulting_state")
    if not raw_state:
        raise HTTPException(
            status_code=409,
            detail="this node predates state tracking; regenerate the scenario to expand it",
        )
    parent_state = RealityState.model_validate(raw_state)

    pipeline = PossibilityPipeline(provider)
    try:
        result = await run_expansion(
            pipeline,
            scenario_id=scenario_id,
            parent_node_id=node_id,
            parent_state=parent_state,
            parent_depth=depth,
            path_labels=list(metadata.get("path_labels") or []),
        )
    except LLMError as exc:
        logger.error("expansion failed for node %s: %s", node_id, exc, exc_info=True)
        service.record_failed_executions(session, scenario_id, pipeline.executions)
        raise HTTPException(status_code=502, detail=f"expansion failed: {exc}") from exc
    except ValueError as exc:
        logger.warning("expansion rejected for node %s: %s", node_id, exc)
        service.record_failed_executions(session, scenario_id, pipeline.executions)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    service.record_executions(session, scenario_id, result.executions)
    service.append_nodes(session, result.nodes, result.edges)
    service.mark_expanded(session, row)

    return ExpandResponse(
        scenario_id=scenario_id,
        node_id=node_id,
        created=True,
        nodes=[n.model_dump(mode="json") for n in result.nodes],
        edges=[e.model_dump(mode="json") for e in result.edges],
        mock=provider_is_mock(provider),
    )


@router.post("/{scenario_id}/compare")
def compare(scenario_id: UUID, payload: CompareRequest, session: Session = Depends(get_db)):
    """Deterministic diff of two branches. No LLM call, no tokens spent."""
    _require_scenario(session, scenario_id)
    left_id, right_id = payload.node_ids
    if left_id == right_id:
        raise HTTPException(status_code=422, detail="pick two different nodes to compare")

    rows = []
    for node_id in (left_id, right_id):
        row = service.get_node(session, scenario_id, node_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"node {node_id} not found")
        rows.append(row)

    graph = service.graph_from_rows(rows, [])
    left, right = graph.nodes
    return compare_nodes(left, right)
