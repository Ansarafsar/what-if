"""Tests for the LangGraph generation machine, especially the revise loop.

The revise edge is the capability the old linear pipeline could not express, so
it gets asserted from three directions: it fires when the critic rejects, it is
bounded, and it stays out of the way on a clean run.
"""

import copy
from uuid import uuid4

import pytest

from app.graphs.generation import run_generation
from app.llm.demo_responses import DEMO_RESPONSES
from app.llm.mock import MockProvider
from app.services.pipeline import PossibilityPipeline


def responses(**overrides) -> dict:
    data = copy.deepcopy(DEMO_RESPONSES)
    data.update(overrides)
    return data


async def generate(provider):
    pipeline = PossibilityPipeline(provider)
    state = await pipeline.extract_reality("A Bengaluru job offer paying 40% more.")
    outcome = await run_generation(pipeline, uuid4(), state)
    return outcome, pipeline


def all_pass_reviews() -> dict:
    reviews = copy.deepcopy(DEMO_RESPONSES["critic_review"])
    for review in reviews["reviews"]:
        review["verdict"] = "pass"
        review["issues"] = []
        review["unsupported_claims"] = []
    return reviews


@pytest.mark.asyncio
async def test_clean_run_never_enters_revise():
    provider = MockProvider(responses(critic_review=all_pass_reviews()))
    outcome, _ = await generate(provider)

    assert "candidate_revision" not in provider.calls
    assert not [e for e in outcome.executions if e.stage == "revise_iteration"]
    assert len(outcome.branches) >= 3


@pytest.mark.asyncio
async def test_revise_fires_on_revise_verdict():
    """The stock fixture flags one branch 'revise'."""
    provider = MockProvider(responses())
    outcome, _ = await generate(provider)

    assert provider.calls.count("candidate_revision") == 1
    assert [e for e in outcome.executions if e.stage == "revise_iteration"]
    labels = [b.candidate.label for b in outcome.branches]
    assert "Reject, fund startup runway" in labels
    assert "Reject and build startup" not in labels


@pytest.mark.asyncio
async def test_revise_regenerates_only_failing_branches():
    provider = MockProvider(responses())
    await generate(provider)

    # 6 candidates on the first pass, then exactly 1 replacement re-projected
    assert provider.calls.count("consequence_generation") == 7


@pytest.mark.asyncio
async def test_revise_fires_on_reject_verdict():
    reviews = copy.deepcopy(DEMO_RESPONSES["critic_review"])
    reviews["reviews"][0]["verdict"] = "reject"
    reviews["reviews"][0]["issues"] = ["fabricates a relocation package"]
    provider = MockProvider(responses(critic_review=reviews))
    outcome, _ = await generate(provider)

    assert "candidate_revision" in provider.calls
    assert outcome.branches


@pytest.mark.asyncio
async def test_revise_stops_at_max_iterations():
    """Every branch flagged forever - the loop must still terminate."""
    reviews = copy.deepcopy(DEMO_RESPONSES["critic_review"])
    for review in reviews["reviews"]:
        review["verdict"] = "revise"
    revision = copy.deepcopy(DEMO_RESPONSES["candidate_revision"])
    # The replacement reuses a flagged label, so it fails review again.
    revision["candidates"][0]["label"] = "Reject and build startup"

    provider = MockProvider(responses(critic_review=reviews, candidate_revision=revision))
    outcome, pipeline = await generate(provider)

    assert provider.calls.count("candidate_revision") == pipeline.settings.engine_max_revise_iterations
    # force-accept admits survivors rather than failing the request
    assert outcome.branches


@pytest.mark.asyncio
async def test_constraint_violation_routes_to_revise_not_silent_drop():
    """A hard violation must survive as data, not vanish (pipeline.py used to
    `continue` past it, leaving constraint_violations always empty)."""
    extraction = copy.deepcopy(DEMO_RESPONSES["reality_extraction"])
    extraction["constraints"].append(
        {
            "description": "Salary must not drop below the current package",
            "kind": "financial",
            "key": "salary",
            "operator": ">=",
            "value": 100000,
        }
    )
    provider = MockProvider(responses(reality_extraction=extraction, critic_review=all_pass_reviews()))
    outcome, _ = await generate(provider)

    # "Reject and build startup" sets salary 80000, breaching the constraint
    assert "candidate_revision" in provider.calls
    assert all(not b.constraint_violations for b in outcome.branches)


@pytest.mark.asyncio
async def test_multiple_forks_are_persisted_as_unexpanded_decisions():
    provider = MockProvider(responses())
    outcome, _ = await generate(provider)

    decisions = [n for n in outcome.graph.nodes if n.node_type == "decision"]
    assert len(decisions) > 1
    assert sum(1 for d in decisions if d.metadata["expanded"]) == 1
    assert any(not d.metadata["expanded"] for d in decisions)
    outcome.graph.validate_acyclic()


@pytest.mark.asyncio
async def test_every_branch_node_knows_its_world():
    provider = MockProvider(responses())
    outcome, _ = await generate(provider)

    for node in outcome.graph.nodes:
        if node.node_type != "state":
            continue
        assert node.metadata["resulting_state"]["state_variables"] is not None
        assert node.metadata["depth"] == 2
        assert node.metadata["path_labels"] == [node.title]


@pytest.mark.asyncio
async def test_stage_executions_are_recorded_for_every_llm_call():
    provider = MockProvider(responses())
    outcome, _ = await generate(provider)

    stages = {e.stage for e in outcome.executions}
    assert {
        "fork_detection",
        "candidate_generation",
        "consequence_generation",
        "critic_review",
        "candidate_revision",
    } <= stages
    assert all(e.prompt_version for e in outcome.executions if e.provider == "MockProvider")
