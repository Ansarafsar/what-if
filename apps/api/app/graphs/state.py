from typing import Any, TypedDict
from uuid import UUID

from app.schemas.domain import (
    BranchReview,
    CandidateAction,
    ConsequenceResult,
    ForkPoint,
    RealityState,
    ScoredBranch,
)


class WhatIfState(TypedDict, total=False):
    """The single state object every node in the generation graph reads and writes.

    LangGraph merges each node's returned partial dict into this, so a node only
    returns the keys it actually changed. Nothing here is mutated in place.
    """

    scenario_id: UUID
    raw_input: str
    reality_state: RealityState
    domain: str

    forks: list[ForkPoint]
    primary_fork: ForkPoint | None

    candidate_branches: list[CandidateAction]
    consequences: dict[str, ConsequenceResult]
    critic_reviews: dict[str, BranchReview]

    verified_branches: list[ScoredBranch]
    rejected_branches: list[dict[str, Any]]
    revising_branches: list[CandidateAction]
    validation_errors: dict[str, list[str]]

    iteration: int
    max_iterations: int
    min_candidates: int
    executions: list[Any]

    # Expansion-only
    parent_node_id: UUID | None
    parent_depth: int
    path_labels: list[str]


def new_state(
    scenario_id: UUID,
    reality_state: RealityState,
    max_iterations: int,
    min_candidates: int = 0,
    raw_input: str = "",
) -> WhatIfState:
    return WhatIfState(
        scenario_id=scenario_id,
        raw_input=raw_input,
        reality_state=reality_state,
        domain=reality_state.domain.value,
        forks=[],
        primary_fork=None,
        candidate_branches=[],
        consequences={},
        critic_reviews={},
        verified_branches=[],
        rejected_branches=[],
        revising_branches=[],
        validation_errors={},
        iteration=0,
        max_iterations=max_iterations,
        min_candidates=min_candidates,
        executions=[],
        parent_node_id=None,
        parent_depth=0,
        path_labels=[],
    )
