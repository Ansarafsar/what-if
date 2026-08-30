"""HTTP plumbing tests.

These run against MockProvider(DEMO_RESPONSES), so any assertion about the
*content* of a response only proves the canned fixture round-tripped through
the API and the database. Reasoning quality is asserted in evals/, against a
live model. Keep assertions here structural.
"""


def test_create_scenario(client, mock_provider):
    response = client.post(
        "/api/v1/scenarios",
        json={"input": "I got a job offer in Bengaluru and I am unsure whether to move."},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "created"
    assert body["id"]


def test_create_scenario_rejects_short_input(client):
    assert client.post("/api/v1/scenarios", json={"input": "too short"}).status_code == 422


def test_extract_roundtrips_evidence_bands(client, bengaluru_scenario, mock_provider):
    """Structural: extraction is called and evidence bands survive the trip.

    This asserts plumbing, not grounding quality - the claims below come from
    the canned fixture. Real grounding is scored in evals/harness/run.py.
    """
    response = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/extract")
    assert response.status_code == 200
    state = response.json()["state"]

    assert state["domain"] == "career"
    bands = {f["evidence_type"] for f in state["facts"]}
    assert bands <= {"grounded", "inferred", "assumed", "speculative", "unknown"}
    assert any(f["evidence_type"] == "grounded" for f in state["facts"])
    assert state["missing_information"]

    assert "reality_extraction" in mock_provider.calls


def test_get_reality_persists(client, bengaluru_scenario):
    client.post(f"/api/v1/scenarios/{bengaluru_scenario}/extract")
    fetched = client.get(f"/api/v1/scenarios/{bengaluru_scenario}/reality")
    assert fetched.status_code == 200
    assert fetched.json()["state"]["title"]


def test_generate_before_extract_conflicts(client, bengaluru_scenario):
    response = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/generate")
    assert response.status_code == 409


def test_full_pipeline_generates_graph(client, bengaluru_scenario, mock_provider):
    client.post(f"/api/v1/scenarios/{bengaluru_scenario}/extract")

    generated = client.post(f"/api/v1/scenarios/{bengaluru_scenario}/generate")
    assert generated.status_code == 200, generated.text
    summary = generated.json()

    assert summary["branch_count"] >= 3
    # reality root + expanded decision + one node per branch + one unexpanded
    # decision per fork that was detected but not expanded on this pass
    assert summary["node_count"] >= summary["branch_count"] + 2
    strategies = {b["strategy"] for b in summary["branches"]}
    assert "blind_spot" in strategies or "hybrid" in strategies

    stages = set(mock_provider.calls)
    assert {
        "fork_detection",
        "candidate_generation",
        "consequence_generation",
        "critic_review",
    } <= stages

    graph = client.get(f"/api/v1/scenarios/{bengaluru_scenario}/graph").json()
    node_types = [n["node_type"] for n in graph["nodes"]]
    assert node_types.count("reality") == 1
    assert node_types.count("decision") >= 1

    branch_nodes = [n for n in graph["nodes"] if n["node_type"] == "state"]
    assert all(n["plausibility"] for n in branch_nodes)
    assert all("effects" in n["metadata"] for n in branch_nodes)
    # Phase 1: every branch knows the world it produced, so it can be expanded
    assert all(n["metadata"].get("resulting_state") for n in branch_nodes)
    assert all(n["metadata"]["depth"] == 2 for n in branch_nodes)

    edge_pairs = {(e["source_id"], e["target_id"]) for e in graph["edges"]}
    assert len(edge_pairs) == len(graph["edges"])

    decision_id = next(
        n["id"]
        for n in graph["nodes"]
        if n["node_type"] == "decision" and n["metadata"].get("expanded")
    )
    root_id = next(n["id"] for n in graph["nodes"] if n["node_type"] == "reality")
    assert any(s == root_id and t == decision_id for s, t in edge_pairs)


def test_scenario_status_transitions(client, bengaluru_scenario):
    assert client.get(f"/api/v1/scenarios/{bengaluru_scenario}").json()["status"] == "created"
    client.post(f"/api/v1/scenarios/{bengaluru_scenario}/extract")
    assert client.get(f"/api/v1/scenarios/{bengaluru_scenario}").json()["status"] == "extracted"
    client.post(f"/api/v1/scenarios/{bengaluru_scenario}/generate")
    assert client.get(f"/api/v1/scenarios/{bengaluru_scenario}").json()["status"] == "generated"


def test_unknown_scenario_404(client):
    from uuid import uuid4

    missing = uuid4()
    assert client.get(f"/api/v1/scenarios/{missing}").status_code == 404
    assert client.get(f"/api/v1/scenarios/{missing}/graph").status_code == 404
