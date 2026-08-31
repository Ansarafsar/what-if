"""Lazy expansion: generate one node's children from that node's own world.

This is the same machine as generation minus the root assembly. It starts from
`metadata.resulting_state` written by the graph builder, so the children of
"Accept the offer" are reasoned about in a world where the offer was accepted -
not in the original reality.
"""

from dataclasses import dataclass, field
from functools import partial
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.engines.graph_builder import build_branch_nodes, build_decision_node
from app.graphs import nodes as N
from app.graphs.state import WhatIfState, new_state
from app.schemas.domain import ForkPoint, RealityState
from app.schemas.possibility import PossibilityEdge, PossibilityNode
from app.services.pipeline import ExecutionRecord, PossibilityPipeline


@dataclass
class ExpansionResult:
    nodes: list[PossibilityNode]
    edges: list[PossibilityEdge]
    branches: list = field(default_factory=list)
    fork: ForkPoint | None = None
    executions: list = field(default_factory=list)


def _add_generation_nodes(builder: StateGraph, pipeline: PossibilityPipeline) -> None:
    """Wire the stages shared by both expansion graphs.

    Everything from candidate generation onwards is identical whether the fork
    was just detected or was stored unexpanded at generation time - only the way
    `primary_fork` arrives in the state differs.
    """
    builder.add_node("generate_candidates", partial(N.generate_candidates_node, pipeline=pipeline))
    builder.add_node("generate_consequences", partial(N.generate_consequences_node, pipeline=pipeline))
    builder.add_node("verify_constraints", partial(N.verify_constraints_node, pipeline=pipeline))
    builder.add_node("critique", partial(N.critique_node, pipeline=pipeline))
    builder.add_node("partition", partial(N.partition_node, pipeline=pipeline))
    builder.add_node("revise", partial(N.revise_node, pipeline=pipeline))
    builder.add_node("force_accept", partial(N.force_accept_node, pipeline=pipeline))
    builder.add_node("rank", partial(N.rank_node, pipeline=pipeline))

    builder.add_edge("generate_candidates", "generate_consequences")
    builder.add_edge("generate_consequences", "verify_constraints")
    builder.add_edge("verify_constraints", "critique")
    builder.add_edge("critique", "partition")
    builder.add_conditional_edges(
        "partition", N.should_revise, {"revise": "revise", "accept": "force_accept"}
    )
    builder.add_edge("revise", "generate_consequences")
    builder.add_edge("force_accept", "rank")
    builder.add_edge("rank", END)


def build_fork_expansion_graph(pipeline: PossibilityPipeline):
    """Expansion for a fork the engine already found and stored unexpanded.

    Detection is skipped: the fork question is known, so re-deriving it would
    spend a call to rediscover something already on disk - and risks the model
    naming a *different* fork than the node the user clicked.
    """
    builder = StateGraph(WhatIfState)
    _add_generation_nodes(builder, pipeline)
    builder.add_edge(START, "generate_candidates")
    return builder.compile()


def build_expansion_graph(pipeline: PossibilityPipeline):
    builder = StateGraph(WhatIfState)

    builder.add_node("detect_forks", partial(N.detect_forks_node, pipeline=pipeline))
    builder.add_node("generate_candidates", partial(N.generate_candidates_node, pipeline=pipeline))
    builder.add_node("generate_consequences", partial(N.generate_consequences_node, pipeline=pipeline))
    builder.add_node("verify_constraints", partial(N.verify_constraints_node, pipeline=pipeline))
    builder.add_node("critique", partial(N.critique_node, pipeline=pipeline))
    builder.add_node("partition", partial(N.partition_node, pipeline=pipeline))
    builder.add_node("revise", partial(N.revise_node, pipeline=pipeline))
    builder.add_node("force_accept", partial(N.force_accept_node, pipeline=pipeline))
    builder.add_node("rank", partial(N.rank_node, pipeline=pipeline))

    builder.add_edge(START, "detect_forks")
    builder.add_edge("detect_forks", "generate_candidates")
    builder.add_edge("generate_candidates", "generate_consequences")
    builder.add_edge("generate_consequences", "verify_constraints")
    builder.add_edge("verify_constraints", "critique")
    builder.add_edge("critique", "partition")
    builder.add_conditional_edges(
        "partition", N.should_revise, {"revise": "revise", "accept": "force_accept"}
    )
    builder.add_edge("revise", "generate_consequences")
    builder.add_edge("force_accept", "rank")
    builder.add_edge("rank", END)

    return builder.compile()


async def run_expansion(
    pipeline: PossibilityPipeline,
    scenario_id: UUID,
    parent_node_id: UUID,
    parent_state: RealityState,
    parent_depth: int,
    path_labels: list[str],
) -> ExpansionResult:
    """Produce a decision node plus its children under `parent_node_id`.

    The caller is responsible for depth guarding and for persisting the result
    with append_nodes - this function never deletes anything.
    """
    settings = pipeline.settings
    initial = new_state(
        scenario_id=scenario_id,
        reality_state=parent_state,
        max_iterations=settings.engine_max_revise_iterations,
        min_candidates=settings.engine_min_candidates,
    )
    initial["parent_node_id"] = parent_node_id
    initial["parent_depth"] = parent_depth
    initial["path_labels"] = path_labels

    compiled = build_expansion_graph(pipeline)
    final: WhatIfState = await compiled.ainvoke(initial, {"recursion_limit": 50})

    fork = final["primary_fork"]
    branches = final["verified_branches"]

    decision, decision_edge = build_decision_node(
        scenario_id=scenario_id,
        parent_id=parent_node_id,
        fork_question=fork.question,
        fork_description=fork.description,
        depth=parent_depth + 1,
        path_labels=path_labels,
        expanded=True,
        fork_id=fork.id,
        importance=fork.importance,
    )

    branch_nodes, branch_edges = build_branch_nodes(
        scenario_id=scenario_id,
        decision_id=decision.id,
        branches=branches,
        parent_state=parent_state,
        depth=parent_depth + 2,
        path_labels=path_labels,
    )

    for iteration in range(final["iteration"]):
        pipeline.executions.append(
            ExecutionRecord(
                stage="revise_iteration",
                provider="engine",
                model="langgraph",
                prompt_name="candidate_revision",
                prompt_version="v1",
                retry_count=iteration + 1,
            )
        )

    return ExpansionResult(
        nodes=[decision, *branch_nodes],
        edges=[decision_edge, *branch_edges],
        branches=branches,
        fork=fork,
        executions=pipeline.executions,
    )


async def run_fork_expansion(
    pipeline: PossibilityPipeline,
    scenario_id: UUID,
    fork_node_id: UUID,
    fork: ForkPoint,
    parent_state: RealityState,
    fork_depth: int,
    path_labels: list[str],
) -> ExpansionResult:
    """Fill in an unexpanded fork with its outcome branches.

    Unlike `run_expansion` this creates no decision node - the fork node already
    exists and was drawn from the moment the graph was generated. Its children
    hang directly off `fork_node_id`, and because the fork is a sibling of the
    one already expanded it reasons from the *same* world state, not from a
    branch outcome. The caller depth-guards and persists.
    """
    settings = pipeline.settings
    initial = new_state(
        scenario_id=scenario_id,
        reality_state=parent_state,
        max_iterations=settings.engine_max_revise_iterations,
        min_candidates=settings.engine_min_candidates,
    )
    initial["parent_node_id"] = fork_node_id
    initial["parent_depth"] = fork_depth
    initial["path_labels"] = path_labels
    # Injected in place of the detect_forks stage the fork graph omits.
    initial["forks"] = [fork]
    initial["primary_fork"] = fork

    compiled = build_fork_expansion_graph(pipeline)
    final: WhatIfState = await compiled.ainvoke(initial, {"recursion_limit": 50})

    branches = final["verified_branches"]

    branch_nodes, branch_edges = build_branch_nodes(
        scenario_id=scenario_id,
        decision_id=fork_node_id,
        branches=branches,
        parent_state=parent_state,
        depth=fork_depth + 1,
        path_labels=path_labels,
    )

    for iteration in range(final["iteration"]):
        pipeline.executions.append(
            ExecutionRecord(
                stage="revise_iteration",
                provider="engine",
                model="langgraph",
                prompt_name="candidate_revision",
                prompt_version="v1",
                retry_count=iteration + 1,
            )
        )

    return ExpansionResult(
        nodes=branch_nodes,
        edges=branch_edges,
        branches=branches,
        fork=fork,
        executions=pipeline.executions,
    )
