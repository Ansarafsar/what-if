import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    LLMExecutionModel,
    PossibilityEdgeModel,
    PossibilityNodeModel,
    RealityStateModel,
    ScenarioInputModel,
    ScenarioModel,
)
from app.schemas.domain import Evidence, RealityState
from app.schemas.possibility import PossibilityGraph
from app.services.pipeline import PipelineOutcome

logger = logging.getLogger(__name__)


def create_scenario(session: Session, raw_input: str, domain: str | None = None) -> ScenarioModel:
    scenario = ScenarioModel(raw_input=raw_input, domain=domain or "general")
    session.add(scenario)
    session.flush()
    session.add(ScenarioInputModel(scenario_id=scenario.id, content=raw_input))
    session.flush()
    return scenario


def get_scenario(session: Session, scenario_id: UUID) -> ScenarioModel | None:
    return session.get(ScenarioModel, scenario_id)


def save_reality_state(session: Session, scenario_id: UUID, state: RealityState) -> int:
    latest_version = session.execute(
        select(RealityStateModel.version)
        .where(RealityStateModel.scenario_id == scenario_id)
        .order_by(RealityStateModel.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    version = (latest_version or 0) + 1
    row = RealityStateModel(
        scenario_id=scenario_id,
        version=version,
        state_json=state.model_dump(mode="json"),
    )
    session.add(row)

    scenario = session.get(ScenarioModel, scenario_id)
    if scenario is not None:
        scenario.domain = state.domain.value
        scenario.title = state.title
        scenario.status = "extracted"
    session.flush()
    return version


def get_latest_reality(session: Session, scenario_id: UUID) -> RealityState | None:
    row = session.execute(
        select(RealityStateModel)
        .where(RealityStateModel.scenario_id == scenario_id)
        .order_by(RealityStateModel.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return RealityState.model_validate(row.state_json)


def _insert_node(session: Session, node) -> None:
    session.add(
        PossibilityNodeModel(
            id=node.id,
            scenario_id=node.scenario_id,
            parent_id=node.parent_id,
            node_type=node.node_type,
            title=node.title,
            description=node.description,
            plausibility=node.plausibility.value if node.plausibility else None,
            score=node.score,
            depth=int(node.metadata.get("depth", 0) or 0),
            node_metadata=node.metadata,
        )
    )


def _insert_edge(session: Session, edge) -> None:
    session.add(
        PossibilityEdgeModel(
            id=edge.id,
            scenario_id=edge.scenario_id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            transition=edge.transition,
            edge_metadata=edge.metadata,
        )
    )


def save_graph(session: Session, outcome: PipelineOutcome) -> None:
    """Initial write. A regenerate genuinely replaces everything, so the
    wholesale delete is correct here - and only here. Expansion must use
    append_nodes, which never deletes."""
    scenario_id = outcome.graph.scenario_id

    session.execute(delete(PossibilityEdgeModel).where(PossibilityEdgeModel.scenario_id == scenario_id))
    session.execute(delete(PossibilityNodeModel).where(PossibilityNodeModel.scenario_id == scenario_id))

    for node in outcome.graph.nodes:
        _insert_node(session, node)
    for edge in outcome.graph.edges:
        _insert_edge(session, edge)

    scenario = session.get(ScenarioModel, scenario_id)
    if scenario is not None:
        scenario.status = "generated"
    session.flush()


def append_nodes(session: Session, nodes, edges) -> None:
    """Additive insert used by expansion. Existing subtrees are untouched."""
    for node in nodes:
        _insert_node(session, node)
    for edge in edges:
        _insert_edge(session, edge)
    session.flush()


def get_node(session: Session, scenario_id: UUID, node_id: UUID) -> PossibilityNodeModel | None:
    row = session.get(PossibilityNodeModel, node_id)
    if row is None or row.scenario_id != scenario_id:
        return None
    return row


def get_children(session: Session, node_id: UUID) -> list[PossibilityNodeModel]:
    return list(
        session.execute(
            select(PossibilityNodeModel).where(PossibilityNodeModel.parent_id == node_id)
        ).scalars().all()
    )


def get_subtree_edges(session: Session, scenario_id: UUID, node_ids: set[UUID]):
    return [
        edge
        for edge in session.execute(
            select(PossibilityEdgeModel).where(PossibilityEdgeModel.scenario_id == scenario_id)
        ).scalars().all()
        if edge.source_id in node_ids or edge.target_id in node_ids
    ]


def mark_expanded(session: Session, node: PossibilityNodeModel) -> None:
    from datetime import datetime, timezone

    metadata = dict(node.node_metadata or {})
    metadata["expanded"] = True
    node.node_metadata = metadata
    node.expanded_at = datetime.now(timezone.utc)
    session.flush()


def get_graph(session: Session, scenario_id: UUID) -> PossibilityGraph | None:
    nodes = session.execute(
        select(PossibilityNodeModel).where(PossibilityNodeModel.scenario_id == scenario_id)
    ).scalars().all()
    if not nodes:
        return None
    edges = session.execute(
        select(PossibilityEdgeModel).where(PossibilityEdgeModel.scenario_id == scenario_id)
    ).scalars().all()
    return graph_from_rows(nodes, edges)


def graph_from_rows(nodes, edges) -> PossibilityGraph:
    from app.schemas.possibility import PossibilityEdge as EdgeSchema
    from app.schemas.possibility import PossibilityNode as NodeSchema
    from app.schemas.domain import Plausibility

    node_schemas = [
        NodeSchema(
            id=row.id,
            scenario_id=row.scenario_id,
            parent_id=row.parent_id,
            node_type=row.node_type,
            title=row.title,
            description=row.description,
            plausibility=Plausibility(row.plausibility) if row.plausibility else None,
            score=row.score,
            metadata=row.node_metadata or {},
        )
        for row in nodes
    ]
    edge_schemas = [
        EdgeSchema(
            id=row.id,
            scenario_id=row.scenario_id,
            source_id=row.source_id,
            target_id=row.target_id,
            transition=row.transition,
            metadata=row.edge_metadata or {},
        )
        for row in edges
    ]
    return PossibilityGraph(scenario_id=node_schemas[0].scenario_id, nodes=node_schemas, edges=edge_schemas)


def record_failed_executions(session: Session, scenario_id: UUID | None, executions) -> None:
    """Persist stage records on a path that is about to raise.

    `get_db` rolls the session back when a request raises - including the
    HTTPException a 502 handler throws - so rows merely flushed here would be
    discarded, leaving a failure with no diagnostic trace. Committing keeps the
    audit trail; it touches only llm_executions, which is append-only.
    """
    record_executions(session, scenario_id, executions)
    try:
        session.commit()
    except Exception:  # pragma: no cover - never mask the original failure
        logger.exception("could not persist execution records for %s", scenario_id)
        session.rollback()


def record_executions(session: Session, scenario_id: UUID | None, executions) -> None:
    for record in executions:
        session.add(
            LLMExecutionModel(
                scenario_id=scenario_id,
                stage=record.stage,
                provider=record.provider,
                model=record.model,
                prompt_name=record.prompt_name,
                prompt_version=record.prompt_version,
                latency_ms=record.latency_ms,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                retry_count=record.retry_count,
                success=record.success,
                error=record.error,
            )
        )
    session.flush()
