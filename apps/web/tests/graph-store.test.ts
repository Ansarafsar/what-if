import { beforeEach, describe, expect, it } from "vitest";

import { hasChildren, useGraphStore } from "@/features/exploration/graph-store";
import type { GraphEdge, GraphNode, PossibilityGraph } from "@/lib/api";

const node = (id: string, type: GraphNode["node_type"] = "state"): GraphNode => ({
  id,
  parent_id: null,
  node_type: type,
  title: id,
  description: "",
  plausibility: null,
  score: 0,
  metadata: {},
});

const edge = (source: string, target: string): GraphEdge => ({
  id: `${source}-${target}`,
  source_id: source,
  target_id: target,
  transition: "",
  metadata: {},
});

const graph: PossibilityGraph = {
  scenario_id: "s1",
  nodes: [node("root", "reality"), node("d1", "decision"), node("a"), node("b")],
  edges: [edge("root", "d1"), edge("d1", "a"), edge("d1", "b")],
};

describe("graph store", () => {
  beforeEach(() => useGraphStore.getState().reset());

  it("merges an expansion subgraph without duplicating nodes", () => {
    useGraphStore.getState().setGraph(graph);
    useGraphStore.getState().mergeSubgraph(
      [node("a"), node("d2", "decision"), node("a1")],
      [edge("a", "d2"), edge("d2", "a1")]
    );

    const merged = useGraphStore.getState().graph!;
    expect(merged.nodes).toHaveLength(6);
    expect(merged.nodes.filter((n) => n.id === "a")).toHaveLength(1);
    expect(merged.edges).toHaveLength(5);
  });

  it("tracks several nodes expanding at once", () => {
    const store = useGraphStore.getState();
    store.startExpanding("a");
    store.startExpanding("b");
    expect(useGraphStore.getState().expanding.has("a")).toBe(true);
    expect(useGraphStore.getState().expanding.has("b")).toBe(true);

    useGraphStore.getState().finishExpanding("a");
    expect(useGraphStore.getState().expanding.has("a")).toBe(false);
    expect(useGraphStore.getState().expanding.has("b")).toBe(true);
  });

  it("keeps a selection and a comparison at the same time", () => {
    useGraphStore.getState().setGraph(graph);
    useGraphStore.getState().select("a");
    useGraphStore.getState().toggleCompare("b");

    expect(useGraphStore.getState().selectedId).toBe("a");
    expect(useGraphStore.getState().compareId).toBe("b");
  });

  it("clears the comparison when the same node is shift-clicked twice", () => {
    useGraphStore.getState().toggleCompare("b");
    useGraphStore.getState().toggleCompare("b");
    expect(useGraphStore.getState().compareId).toBeNull();
  });

  it("records and then clears an expansion error", () => {
    useGraphStore.getState().startExpanding("a");
    useGraphStore.getState().finishExpanding("a", "depth limit reached");
    expect(useGraphStore.getState().expandErrors.a).toBe("depth limit reached");

    useGraphStore.getState().startExpanding("a");
    expect(useGraphStore.getState().expandErrors.a).toBeUndefined();
  });

  it("knows which nodes already have children", () => {
    expect(hasChildren(graph, "d1")).toBe(true);
    expect(hasChildren(graph, "a")).toBe(false);
    expect(hasChildren(null, "a")).toBe(false);
  });
});
