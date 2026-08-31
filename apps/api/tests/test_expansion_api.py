"""Expansion, node detail and compare routes.

These run against MockProvider, so they assert wiring and cost behaviour -
depth, idempotence, additive writes - not reasoning quality.
"""

from uuid import uuid4

import pytest


def generated(client, scenario_id):
    client.post(f"/api/v1/scenarios/{scenario_id}/extract")
    response = client.post(f"/api/v1/scenarios/{scenario_id}/generate")
    assert response.status_code == 200, response.text
    return client.get(f"/api/v1/scenarios/{scenario_id}/graph").json()


def first_state_node(graph):
    """A branch that actually moves the world, so state assertions are meaningful.

    Some branches legitimately have an empty state_delta ("Delay decision one
    month" changes nothing yet), which is valid but uninteresting to diff.
    """
    with_delta = [
        n for n in graph["nodes"]
        if n["node_type"] == "state" and n["metadata"].get("state_delta")
    ]
    return with_delta[0] if with_delta else next(
        n for n in graph["nodes"] if n["node_type"] == "state"
    )


def test_node_detail_exposes_state_and_children(client, bengaluru_scenario):
    graph = generated(client, bengaluru_scenario)
    node = first_state_node(graph)

    detail = client.get(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{node['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["depth"] == 2
    assert body["child_ids"] == []
    assert body["metadata"]["resulting_state"]["state_variables"]


def test_branch_with_empty_delta_still_carries_a_world(client, bengaluru_scenario):
    """A branch that changes nothing yet ("delay one month") inherits its
    parent's world unchanged - it must still be expandable."""
    graph = generated(client, bengaluru_scenario)
    empty = next(
        (n for n in graph["nodes"]
         if n["node_type"] == "state" and not n["metadata"].get("state_delta")),
        None,
    )
    if empty is None:
        pytest.skip("fixture produced no empty-delta branch")

    detail = client.get(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{empty['id']}").json()
    assert detail["metadata"]["resulting_state"]["state_variables"] == {}

    expanded = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{empty['id']}/expand")
    assert expanded.status_code == 200
    assert expanded.json()["created"] is True


def test_expand_appends_children_from_the_branch_world(client, bengaluru_scenario):
    graph = generated(client, bengaluru_scenario)
    node = first_state_node(graph)
    before = len(graph["nodes"])

    response = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{node['id']}/expand")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] is True

    added_types = [n["node_type"] for n in body["nodes"]]
    assert added_types.count("decision") == 1
    assert added_types.count("state") >= 3

    # The new decision hangs off the branch we expanded, not off the root
    decision = next(n for n in body["nodes"] if n["node_type"] == "decision")
    assert decision["parent_id"] == node["id"]
    assert decision["metadata"]["depth"] == 3

    child = next(n for n in body["nodes"] if n["node_type"] == "state")
    assert child["metadata"]["depth"] == 4
    assert child["metadata"]["path_labels"][0] == node["title"]

    after = client.get(f"/api/v1/scenarios/{bengaluru_scenario}/graph").json()
    assert len(after["nodes"]) > before


def test_expansion_does_not_destroy_the_existing_graph(client, bengaluru_scenario):
    """save_graph used to delete every node on write; expansion must not."""
    graph = generated(client, bengaluru_scenario)
    original_ids = {n["id"] for n in graph["nodes"]}
    node = first_state_node(graph)

    client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{node['id']}/expand")

    after = client.get(f"/api/v1/scenarios/{bengaluru_scenario}/graph").json()
    assert original_ids <= {n["id"] for n in after["nodes"]}


def test_expand_is_idempotent_and_costs_no_second_llm_call(
    client, bengaluru_scenario, mock_provider
):
    graph = generated(client, bengaluru_scenario)
    node = first_state_node(graph)

    client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{node['id']}/expand")
    calls_after_first = len(mock_provider.calls)

    second = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{node['id']}/expand")
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["nodes"]
    assert len(mock_provider.calls) == calls_after_first


def test_depth_four_is_reachable(client, bengaluru_scenario):
    graph = generated(client, bengaluru_scenario)
    node = first_state_node(graph)

    first = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{node['id']}/expand").json()
    grandchild = next(n for n in first["nodes"] if n["node_type"] == "state")
    assert grandchild["metadata"]["depth"] == 4

    full = client.get(f"/api/v1/scenarios/{bengaluru_scenario}/graph").json()
    assert max(n["metadata"].get("depth", 0) for n in full["nodes"]) == 4


def test_expand_refuses_past_max_depth(client, bengaluru_scenario):
    graph = generated(client, bengaluru_scenario)
    node = first_state_node(graph)

    first = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{node['id']}/expand").json()
    depth_four = next(n for n in first["nodes"] if n["metadata"]["depth"] == 4)

    blocked = client.post(
        f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{depth_four['id']}/expand"
    )
    assert blocked.status_code == 422
    assert "depth" in blocked.json()["detail"]


def test_expand_rejects_the_reality_root(client, bengaluru_scenario):
    """Reality is the world you start in - there is nothing above it to fork."""
    graph = generated(client, bengaluru_scenario)
    root = next(n for n in graph["nodes"] if n["node_type"] == "reality")

    response = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{root['id']}/expand")
    assert response.status_code == 422


class TestUnexpandedForkExpansion:
    """The forks generation found but deliberately left unexpanded.

    Storing them costs nothing; expanding all of them up front would multiply
    the LLM calls before the user has looked at the graph. So the calls are
    deferred to the click, and this is that click.
    """

    def _unexpanded(self, graph):
        return [
            n
            for n in graph["nodes"]
            if n["node_type"] == "decision" and n["metadata"].get("expanded") is False
        ]

    def test_generation_leaves_secondary_forks_unexpanded(self, client, bengaluru_scenario):
        graph = generated(client, bengaluru_scenario)
        assert self._unexpanded(graph), "fixture should leave at least one fork unexpanded"

    def test_expanding_a_fork_creates_its_branches(self, client, bengaluru_scenario):
        graph = generated(client, bengaluru_scenario)
        fork = self._unexpanded(graph)[0]

        response = client.post(
            f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{fork['id']}/expand"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["created"] is True
        branches = [n for n in body["nodes"] if n["node_type"] == "state"]
        assert branches, "expansion must return the new branches"
        # Children hang off the fork itself; no second decision node is made.
        assert all(e["source_id"] == fork["id"] for e in body["edges"])

    def test_response_carries_the_now_expanded_fork(self, client, bengaluru_scenario):
        """The client merges by id, so a stale fork would stay dashed."""
        graph = generated(client, bengaluru_scenario)
        fork = self._unexpanded(graph)[0]

        body = client.post(
            f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{fork['id']}/expand"
        ).json()

        returned = next(n for n in body["nodes"] if n["id"] == fork["id"])
        assert returned["metadata"]["expanded"] is True

    def test_expanded_fork_stops_reporting_as_unexpanded(self, client, bengaluru_scenario):
        graph = generated(client, bengaluru_scenario)
        fork = self._unexpanded(graph)[0]
        client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{fork['id']}/expand")

        after = client.get(f"/api/v1/scenarios/{bengaluru_scenario}/graph").json()
        reloaded = next(n for n in after["nodes"] if n["id"] == fork["id"])
        assert reloaded["metadata"]["expanded"] is True

    def test_expanding_a_fork_is_idempotent(self, client, bengaluru_scenario, mock_provider):
        """Re-clicking a fork must not spend the calls a second time."""
        graph = generated(client, bengaluru_scenario)
        fork = self._unexpanded(graph)[0]
        client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{fork['id']}/expand")

        before = len(mock_provider.calls)
        again = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{fork['id']}/expand")

        assert again.status_code == 200
        assert again.json()["created"] is False
        assert len(mock_provider.calls) == before, "cached fork expansion must not call the LLM"

    def test_fork_expansion_skips_fork_detection(self, client, bengaluru_scenario, mock_provider):
        """The question is already on disk, so re-detecting it would be waste."""
        graph = generated(client, bengaluru_scenario)
        fork = self._unexpanded(graph)[0]
        before = [c for c in mock_provider.calls if "fork" in str(c).lower()]

        client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{fork['id']}/expand")

        after = [c for c in mock_provider.calls if "fork" in str(c).lower()]
        assert len(after) == len(before), "fork detection must not run again"


def test_expand_unknown_node_404(client, bengaluru_scenario):
    generated(client, bengaluru_scenario)
    response = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/nodes/{uuid4()}/expand")
    assert response.status_code == 404


class TestCompare:
    def test_compare_returns_relative_dimensions(self, client, bengaluru_scenario, mock_provider):
        graph = generated(client, bengaluru_scenario)
        states = [n for n in graph["nodes"] if n["node_type"] == "state"]
        before = len(mock_provider.calls)

        response = client.post(
            f"/api/v1/scenarios/{bengaluru_scenario}/compare",
            json={"node_ids": [states[0]["id"], states[1]["id"]]},
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["relative"] is True
        assert body["left"]["id"] == states[0]["id"]
        assert body["dimensions"]
        for row in body["dimensions"]:
            assert row["direction"] in {"left", "right", "even"}
            assert set(row["marker"]) <= {"↑", "↓", "="}
        # deterministic: no tokens spent
        assert len(mock_provider.calls) == before

    def test_compare_diffs_world_state(self, client, bengaluru_scenario):
        graph = generated(client, bengaluru_scenario)
        states = [n for n in graph["nodes"] if n["node_type"] == "state"]
        body = client.post(
            f"/api/v1/scenarios/{bengaluru_scenario}/compare",
            json={"node_ids": [states[0]["id"], states[1]["id"]]},
        ).json()

        assert body["state"]
        assert any(row["same"] is False for row in body["state"])

    def test_compare_rejects_same_node_twice(self, client, bengaluru_scenario):
        graph = generated(client, bengaluru_scenario)
        node = first_state_node(graph)
        response = client.post(
            f"/api/v1/scenarios/{bengaluru_scenario}/compare",
            json={"node_ids": [node["id"], node["id"]]},
        )
        assert response.status_code == 422

    def test_compare_unknown_node_404(self, client, bengaluru_scenario):
        graph = generated(client, bengaluru_scenario)
        node = first_state_node(graph)
        response = client.post(
            f"/api/v1/scenarios/{bengaluru_scenario}/compare",
            json={"node_ids": [node["id"], str(uuid4())]},
        )
        assert response.status_code == 404


class TestGenerationStream:
    def _events(self, client, scenario_id):
        import json

        client.post(f"/api/v1/scenarios/{scenario_id}/extract")
        with client.stream("POST", f"/api/v1/scenarios/{scenario_id}/generate/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            return [
                json.loads(line[len("data: "):])
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]

    def test_stream_reports_each_stage_then_completes(self, client, bengaluru_scenario):
        events = self._events(client, bengaluru_scenario)

        stages = [e["stage"] for e in events if e["type"] == "stage"]
        assert stages[0] == "detect_forks"
        assert "critique" in stages
        assert "revise" in stages  # the demo fixture flags one branch
        assert events[-1]["type"] == "complete"
        assert events[-1]["branch_count"] >= 3
        assert events[-1]["branches"]

    def test_stream_persists_the_graph(self, client, bengaluru_scenario):
        self._events(client, bengaluru_scenario)
        graph = client.get(f"/api/v1/scenarios/{bengaluru_scenario}/graph")
        assert graph.status_code == 200
        assert graph.json()["nodes"]

    def test_stream_before_extract_conflicts(self, client, bengaluru_scenario):
        response = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/generate/stream")
        assert response.status_code == 409


class TestFailuresAreObservable:
    """A 502 whose only trace is a status line cannot be diagnosed in production.

    Every failing stage must leave an llm_executions row carrying the retry
    count and error text.
    """

    class BrokenProvider:
        provider_id = "mock"

        def __init__(self, fail_stage: str, responses: dict):
            self.fail_stage = fail_stage
            self.responses = responses
            self.calls: list[str] = []

        async def generate_structured(self, *, system_prompt, user_prompt, schema, stage, temperature=0.4):
            from app.llm.base import LLMValidationError
            from app.llm.mock import MockProvider

            self.calls.append(stage)
            if stage == self.fail_stage:
                raise LLMValidationError(f"stage '{stage}' exploded for the test")
            return await MockProvider(self.responses).generate_structured(
                system_prompt=system_prompt, user_prompt=user_prompt,
                schema=schema, stage=stage, temperature=temperature,
            )

    def _client_with(self, test_session_factory, provider):
        from fastapi.testclient import TestClient

        from app.api.deps import get_llm_provider
        from app.core.database import get_db, get_session_factory
        from app.main import create_app

        app = create_app()

        def override_get_db():
            session = test_session_factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_session_factory] = lambda: test_session_factory
        app.dependency_overrides[get_llm_provider] = lambda: provider
        return TestClient(app)

    def _executions(self, test_session_factory):
        from sqlalchemy import select

        from app.models import LLMExecutionModel

        with test_session_factory() as session:
            return list(session.execute(select(LLMExecutionModel)).scalars().all())

    def test_failed_extraction_is_recorded(self, test_session_factory):
        from app.llm.demo_responses import DEMO_RESPONSES

        provider = self.BrokenProvider("reality_extraction", dict(DEMO_RESPONSES))
        client = self._client_with(test_session_factory, provider)

        created = client.post("/api/v1/scenarios", json={"input": "A situation worth exploring here."})
        scenario_id = created.json()["id"]
        response = client.post(f"/api/v1/scenarios/{scenario_id}/extract")
        assert response.status_code == 502

        rows = self._executions(test_session_factory)
        assert rows, "a failed extraction left no llm_executions row"
        failed = [r for r in rows if not r.success]
        assert failed and "exploded" in (failed[0].error or "")

    def test_failed_generation_is_recorded(self, test_session_factory):
        from app.llm.demo_responses import DEMO_RESPONSES

        provider = self.BrokenProvider("fork_detection", dict(DEMO_RESPONSES))
        client = self._client_with(test_session_factory, provider)

        created = client.post("/api/v1/scenarios", json={"input": "A situation worth exploring here."})
        scenario_id = created.json()["id"]
        client.post(f"/api/v1/scenarios/{scenario_id}/extract")
        response = client.post(f"/api/v1/scenarios/{scenario_id}/generate")
        assert response.status_code == 502
        assert "possibility generation failed" in response.json()["detail"]

        failed = [r for r in self._executions(test_session_factory) if not r.success]
        assert failed, "a failed generation left no llm_executions row"
        assert failed[0].stage == "fork_detection"


def test_responses_flag_mock_provider(client, bengaluru_scenario):
    extracted = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/extract").json()
    assert extracted["mock"] is True
    summary = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/generate").json()
    assert summary["mock"] is True
