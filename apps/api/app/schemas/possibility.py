from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.domain import (
    Assumption,
    CandidateAction,
    ConsequenceResult,
    ConstraintItem,
    DecisionHint,
    DomainType,
    Effect,
    EventItem,
    Evidence,
    EvidenceType,
    ForkPoint,
    Plausibility,
    RealityState,
)

__all__ = [
    "Assumption",
    "CandidateAction",
    "ConsequenceResult",
    "ConstraintItem",
    "DecisionHint",
    "DomainType",
    "Effect",
    "EventItem",
    "Evidence",
    "EvidenceType",
    "ForkPoint",
    "Plausibility",
    "PossibilityEdge",
    "PossibilityGraph",
    "PossibilityNode",
    "RealityExtractionOutput",
    "RealityState",
]


class RealityExtractionOutput(BaseModel):
    """Schema the LLM must satisfy in the extraction stage."""

    title: str = Field(min_length=3, max_length=120)
    domain: DomainType = DomainType.GENERAL
    summary: str = Field(min_length=10, max_length=600)
    actors: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    decision_hints: list[DecisionHint] = Field(default_factory=list)
    constraints: list[ConstraintItem] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    beliefs: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class PossibilityNode(BaseModel):
    id: UUID
    scenario_id: UUID
    parent_id: UUID | None = None
    node_type: str
    title: str
    description: str
    plausibility: Plausibility | None = None
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PossibilityEdge(BaseModel):
    id: UUID
    scenario_id: UUID
    source_id: UUID
    target_id: UUID
    transition: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PossibilityGraph(BaseModel):
    scenario_id: UUID
    nodes: list[PossibilityNode]
    edges: list[PossibilityEdge]

    def validate_acyclic(self) -> None:
        adjacency: dict[UUID, list[UUID]] = {}
        for edge in self.edges:
            adjacency.setdefault(edge.source_id, []).append(edge.target_id)

        visited: set[UUID] = set()
        stack: set[UUID] = set()

        def visit(node_id: UUID) -> None:
            if node_id in stack:
                raise ValueError("possibility graph contains a cycle")
            if node_id in visited:
                return
            stack.add(node_id)
            for child in adjacency.get(node_id, []):
                visit(child)
            stack.remove(node_id)
            visited.add(node_id)

        for node in self.nodes:
            visit(node.id)
