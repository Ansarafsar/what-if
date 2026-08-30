from uuid import UUID, uuid4

from app.engines.state_transition import resulting_state
from app.schemas.domain import RealityState, ScoredBranch
from app.schemas.possibility import PossibilityEdge, PossibilityGraph, PossibilityNode


def _branch_metadata(
    branch: ScoredBranch,
    parent_state: RealityState | None,
    depth: int,
    path_labels: list[str],
) -> dict:
    """Everything the UI or a later expansion needs, computed once here."""
    candidate = branch.candidate
    consequence = branch.consequence

    evidence_summary = {
        "grounded_reasons": consequence.plausibility_reasons,
        "assumptions": [a.model_dump() for a in consequence.assumptions],
        "risks": consequence.risks,
    }
    if branch.review is not None:
        evidence_summary["critic"] = {
            "verdict": branch.review.verdict,
            "issues": branch.review.issues,
        }
    if branch.constraint_violations:
        evidence_summary["constraint_violations"] = branch.constraint_violations

    metadata = {
        "strategy": candidate.strategy,
        "rationale": candidate.rationale,
        "reversible": candidate.reversible,
        "state_delta": candidate.state_delta,
        "effects": [e.model_dump() for e in consequence.effects],
        "score_breakdown": branch.score_breakdown,
        "evidence": evidence_summary,
        "depth": depth,
        "path_labels": path_labels,
        "expanded": False,
    }

    if parent_state is not None:
        child_state = resulting_state(
            parent=parent_state,
            delta=candidate.state_delta,
            branch_label=candidate.label,
            branch_narrative=consequence.narrative,
        )
        metadata["resulting_state"] = child_state.model_dump(mode="json")

    return metadata


def build_branch_nodes(
    scenario_id: UUID,
    decision_id: UUID,
    branches: list[ScoredBranch],
    parent_state: RealityState | None,
    depth: int,
    path_labels: list[str],
) -> tuple[list[PossibilityNode], list[PossibilityEdge]]:
    """One outcome node (plus its edge) per surviving branch under a decision.

    Shared by the initial build and by expansion so both produce identically
    shaped nodes - an expanded node is indistinguishable from a first-paint one.
    """
    nodes: list[PossibilityNode] = []
    edges: list[PossibilityEdge] = []

    for branch in branches:
        candidate = branch.candidate
        node = PossibilityNode(
            id=uuid4(),
            scenario_id=scenario_id,
            parent_id=decision_id,
            node_type="state",
            title=candidate.label,
            description=branch.consequence.narrative,
            plausibility=branch.consequence.plausibility,
            score=branch.score,
            metadata=_branch_metadata(
                branch,
                parent_state,
                depth,
                [*path_labels, candidate.label],
            ),
        )
        nodes.append(node)
        edges.append(
            PossibilityEdge(
                id=uuid4(),
                scenario_id=scenario_id,
                source_id=decision_id,
                target_id=node.id,
                transition=candidate.label,
                metadata={"reversible": candidate.reversible},
            )
        )

    return nodes, edges


def build_decision_node(
    scenario_id: UUID,
    parent_id: UUID,
    fork_question: str,
    fork_description: str,
    depth: int,
    path_labels: list[str],
    expanded: bool,
    fork_id: str = "",
    importance: float = 0.5,
) -> tuple[PossibilityNode, PossibilityEdge]:
    node = PossibilityNode(
        id=uuid4(),
        scenario_id=scenario_id,
        parent_id=parent_id,
        node_type="decision",
        title="Fork point",
        description=fork_description,
        metadata={
            "question": fork_question,
            "fork_id": fork_id,
            "importance": importance,
            "depth": depth,
            "path_labels": path_labels,
            "expanded": expanded,
        },
    )
    edge = PossibilityEdge(
        id=uuid4(),
        scenario_id=scenario_id,
        source_id=parent_id,
        target_id=node.id,
        transition=fork_question,
    )
    return node, edge


def build_graph(
    scenario_id: UUID,
    reality_summary: str,
    fork_question: str,
    fork_description: str,
    branches: list[ScoredBranch],
    reality_state: RealityState | None = None,
    secondary_forks: list | None = None,
) -> PossibilityGraph:
    """Assemble the initial possibility graph.

    Structure: reality root -> decision node -> one outcome node per surviving
    branch. Any forks detected but not expanded on this pass become sibling
    decision nodes marked unexpanded, so the user can open them without a
    regenerate. Every branch node carries its narrative, effects, assumptions,
    evidence summary and *resulting world state* in metadata, so the UI never
    re-derives anything and an expansion knows which world it starts from.
    """
    root = PossibilityNode(
        id=uuid4(),
        scenario_id=scenario_id,
        parent_id=None,
        node_type="reality",
        title="You are here",
        description=reality_summary,
        metadata={
            "depth": 0,
            "path_labels": [],
            "resulting_state": reality_state.model_dump(mode="json") if reality_state else None,
        },
    )

    decision, root_edge = build_decision_node(
        scenario_id=scenario_id,
        parent_id=root.id,
        fork_question=fork_question,
        fork_description=fork_description,
        depth=1,
        path_labels=[],
        expanded=True,
    )

    nodes: list[PossibilityNode] = [root, decision]
    edges: list[PossibilityEdge] = [root_edge]

    branch_nodes, branch_edges = build_branch_nodes(
        scenario_id=scenario_id,
        decision_id=decision.id,
        branches=branches,
        parent_state=reality_state,
        depth=2,
        path_labels=[],
    )
    nodes.extend(branch_nodes)
    edges.extend(branch_edges)

    for fork in secondary_forks or []:
        extra, extra_edge = build_decision_node(
            scenario_id=scenario_id,
            parent_id=root.id,
            fork_question=fork.question,
            fork_description=fork.description,
            depth=1,
            path_labels=[],
            expanded=False,
            fork_id=fork.id,
            importance=fork.importance,
        )
        nodes.append(extra)
        edges.append(extra_edge)

    graph = PossibilityGraph(scenario_id=scenario_id, nodes=nodes, edges=edges)
    graph.validate_acyclic()
    return graph
