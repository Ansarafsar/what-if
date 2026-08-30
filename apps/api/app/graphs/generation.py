"""The generation state machine.

    detect_forks -> generate_candidates -> generate_consequences
      -> verify_constraints -> critique -> partition
      -> [conditional] --revise--> generate_consequences (max 2 iterations)
                       --accept--> force_accept -> rank -> build_graph

The revise edge is the capability the linear pipeline could not express: the
critic's verdicts and the constraint engine's violations feed back into a
targeted regeneration of only the failing branches, bounded by max_iterations.
"""

from collections.abc import AsyncIterator
from functools import partial
from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.engines.graph_builder import build_graph
from app.graphs import nodes as N
from app.graphs.state import WhatIfState, new_state
from app.schemas.domain import RealityState
from app.services.pipeline import ExecutionRecord, PipelineOutcome, PossibilityPipeline


def _bind(fn, pipeline: PossibilityPipeline):
    return partial(fn, pipeline=pipeline)


def build_generation_graph(pipeline: PossibilityPipeline):
    builder = StateGraph(WhatIfState)

    builder.add_node("detect_forks", _bind(N.detect_forks_node, pipeline))
    builder.add_node("generate_candidates", _bind(N.generate_candidates_node, pipeline))
    builder.add_node("generate_consequences", _bind(N.generate_consequences_node, pipeline))
    builder.add_node("verify_constraints", _bind(N.verify_constraints_node, pipeline))
    builder.add_node("critique", _bind(N.critique_node, pipeline))
    builder.add_node("partition", _bind(N.partition_node, pipeline))
    builder.add_node("revise", _bind(N.revise_node, pipeline))
    builder.add_node("force_accept", _bind(N.force_accept_node, pipeline))
    builder.add_node("rank", _bind(N.rank_node, pipeline))

    builder.add_edge(START, "detect_forks")
    builder.add_edge("detect_forks", "generate_candidates")
    builder.add_edge("generate_candidates", "generate_consequences")
    builder.add_edge("generate_consequences", "verify_constraints")
    builder.add_edge("verify_constraints", "critique")
    builder.add_edge("critique", "partition")

    builder.add_conditional_edges(
        "partition",
        N.should_revise,
        {"revise": "revise", "accept": "force_accept"},
    )
    # A revision produces new candidates, so they re-enter at consequences and
    # walk the same verify -> critique -> partition path as the first pass.
    builder.add_edge("revise", "generate_consequences")
    builder.add_edge("force_accept", "rank")
    builder.add_edge("rank", END)

    return builder.compile()


STAGE_LABELS: dict[str, str] = {
    "detect_forks": "Finding decision points",
    "generate_candidates": "Generating possible paths",
    "generate_consequences": "Projecting consequences",
    "verify_constraints": "Checking constraints",
    "critique": "Adversarial review of branches",
    "partition": "Sorting what survived",
    "revise": "Revising branches that failed review",
    "force_accept": "Admitting surviving branches",
    "rank": "Ranking and deduplicating",
}


def _initial_state(
    pipeline: PossibilityPipeline,
    scenario_id: UUID,
    reality: RealityState,
    max_iterations: int | None,
) -> WhatIfState:
    settings = pipeline.settings
    return new_state(
        scenario_id=scenario_id,
        reality_state=reality,
        max_iterations=(
            settings.engine_max_revise_iterations if max_iterations is None else max_iterations
        ),
        min_candidates=settings.engine_min_candidates,
    )


async def stream_generation(
    pipeline: PossibilityPipeline,
    scenario_id: UUID,
    reality: RealityState,
    max_iterations: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield one event per completed graph node, then a final outcome event.

    This is what makes the progress indicator honest: the UI reports the stage
    the engine actually finished, including a revise iteration, instead of
    cycling canned copy on a timer.
    """
    initial = _initial_state(pipeline, scenario_id, reality, max_iterations)
    compiled = build_generation_graph(pipeline)

    final: WhatIfState = dict(initial)  # type: ignore[assignment]
    async for update in compiled.astream(
        initial, {"recursion_limit": 50}, stream_mode="updates"
    ):
        for node_name, partial_state in update.items():
            if isinstance(partial_state, dict):
                final.update(partial_state)
            yield {
                "type": "stage",
                "stage": node_name,
                "label": STAGE_LABELS.get(node_name, node_name),
                "iteration": final.get("iteration", 0),
                "branch_count": len(final.get("verified_branches") or []),
            }

    outcome = _assemble(pipeline, scenario_id, reality, final)
    yield {
        "type": "complete",
        "node_count": len(outcome.graph.nodes),
        "edge_count": len(outcome.graph.edges),
        "branch_count": len(outcome.branches),
        "outcome": outcome,
    }


async def run_generation(
    pipeline: PossibilityPipeline,
    scenario_id: UUID,
    reality: RealityState,
    max_iterations: int | None = None,
) -> PipelineOutcome:
    """Run the graph and assemble the possibility graph from its final state."""
    initial = _initial_state(pipeline, scenario_id, reality, max_iterations)

    compiled = build_generation_graph(pipeline)
    # Each node may loop; the default recursion limit is generous enough for
    # max_iterations=2 but is raised explicitly so the bound stays ours.
    final: WhatIfState = await compiled.ainvoke(initial, {"recursion_limit": 50})
    return _assemble(pipeline, scenario_id, reality, final)


def _assemble(
    pipeline: PossibilityPipeline,
    scenario_id: UUID,
    reality: RealityState,
    final: WhatIfState,
) -> PipelineOutcome:
    primary = final["primary_fork"]
    surviving = final["verified_branches"]

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

    graph = build_graph(
        scenario_id=scenario_id,
        reality_summary=reality.summary,
        fork_question=primary.question,
        fork_description=primary.description,
        branches=surviving,
        reality_state=reality,
        secondary_forks=[f for f in final["forks"] if f.id != primary.id],
    )

    return PipelineOutcome(
        graph=graph,
        branches=surviving,
        fork=primary,
        executions=pipeline.executions,
    )
