import { afterEach, describe, expect, it, vi } from "vitest";

import { extractReality, getGraph, getReality } from "@/lib/api";

function mockJson(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status }))
  );
}

const validGraph = {
  scenario_id: "s1",
  nodes: [
    {
      id: "n1",
      parent_id: null,
      node_type: "state",
      title: "Accept",
      description: "",
      plausibility: "high",
      score: 0.5,
      metadata: { depth: 2, effects: [] },
    },
  ],
  edges: [],
};

describe("api response validation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses a well-formed graph", async () => {
    mockJson(validGraph);
    const graph = await getGraph("s1");
    expect(graph.nodes[0].metadata.depth).toBe(2);
  });

  it("defaults optional collections rather than yielding undefined", async () => {
    mockJson({ ...validGraph, edges: [{ id: "e1", source_id: "n1", target_id: "n2", transition: "" }] });
    const graph = await getGraph("s1");
    expect(graph.edges[0].metadata).toEqual({});
  });

  it("fails loudly when the backend changes a field type", async () => {
    mockJson({ ...validGraph, nodes: [{ ...validGraph.nodes[0], score: "high" }] });
    await expect(getGraph("s1")).rejects.toThrow(/Unexpected response/);
  });

  it("names the field that moved", async () => {
    mockJson({ ...validGraph, nodes: [{ ...validGraph.nodes[0], node_type: "outcome" }] });
    await expect(getGraph("s1")).rejects.toThrow(/node_type/);
  });

  it("keeps unknown metadata keys instead of rejecting them", async () => {
    mockJson({
      ...validGraph,
      nodes: [{ ...validGraph.nodes[0], metadata: { depth: 2, future_field: "kept" } }],
    });
    const graph = await getGraph("s1");
    expect((graph.nodes[0].metadata as Record<string, unknown>).future_field).toBe("kept");
  });

  it("surfaces the server detail on an error response", async () => {
    mockJson({ detail: "no reality state extracted yet" }, 404);
    await expect(getReality("s1")).rejects.toThrow("no reality state extracted yet");
  });
});

/**
 * Pydantic serialises `X | None` as an explicit null rather than omitting the
 * key, so `.optional()` alone rejects a perfectly good response. This shipped
 * once: every live extraction returned 200 with valid data and the UI still
 * showed "Extraction failed", because `state.scenario_id` came back null.
 */
describe("nullable fields the backend actually sends", () => {
  afterEach(() => vi.unstubAllGlobals());

  const realityBody = (overrides: Record<string, unknown> = {}) => ({
    scenario_id: "s1",
    mock: false,
    state: {
      scenario_id: null,
      title: "Acquisition offer",
      summary: "A two-person studio weighing an acquisition.",
      domain: "business",
      actors: [],
      entities: [],
      events: [{ description: "Offer received", timestamp: null, evidence_type: "grounded" }],
      decision_hints: [],
      constraints: [
        { description: "Runway", kind: "financial", key: null, operator: null, value: null },
      ],
      goals: [],
      relationships: [],
      resources: [],
      beliefs: [],
      uncertainties: [],
      missing_information: [],
      facts: [],
      state_variables: {},
      ...overrides,
    },
  });

  it("accepts a null scenario_id inside the reality state", async () => {
    mockJson(realityBody());
    const result = await getReality("s1");
    expect(result.state.scenario_id).toBeNull();
    expect(result.state.domain).toBe("business");
  });

  it("accepts null timestamp and null constraint key/operator/value", async () => {
    mockJson(realityBody());
    const result = await getReality("s1");
    expect(result.state.events[0].timestamp).toBeNull();
    expect(result.state.constraints[0].key).toBeNull();
  });

  it("tolerates the extra version field extract adds to the state", async () => {
    mockJson(realityBody({ version: 3 }));
    await expect(extractReality("s1")).resolves.toBeTruthy();
  });

  it("accepts a graph node with null parent_id, plausibility and score", async () => {
    mockJson({
      scenario_id: "s1",
      nodes: [
        {
          id: "root",
          parent_id: null,
          node_type: "reality",
          title: "You are here",
          description: "",
          plausibility: null,
          score: null,
          metadata: { depth: 0, resulting_state: null },
        },
      ],
      edges: [],
    });
    const graph = await getGraph("s1");
    expect(graph.nodes[0].parent_id).toBeNull();
    expect(graph.nodes[0].metadata.resulting_state).toBeNull();
  });
});
