import { describe, expect, it } from "vitest";

import type { GraphEdge, GraphNode } from "@/lib/api";
import { computeLayout, NODE_SIZE, UNEXPANDED_DECISION_HEIGHT } from "@/lib/graph-layout";

/** Positions are top-left corners; alignment is about centres. */
const centerY = (
  layout: Record<string, { x: number; y: number }>,
  id: string,
  type: GraphNode["node_type"]
) => layout[id].y + NODE_SIZE[type].height / 2;

const node = (id: string, type: GraphNode["node_type"]): GraphNode => ({
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

describe("graph layout", () => {
  const nodes = [
    node("root", "reality"),
    node("decision", "decision"),
    node("a", "state"),
    node("b", "state"),
    node("c", "state"),
  ];
  const edges = [edge("root", "decision"), edge("decision", "a"), edge("decision", "b"), edge("decision", "c")];
  const layout = computeLayout(nodes, edges);

  it("places root leftmost and branches rightmost", () => {
    expect(layout.root.x).toBeLessThan(layout.decision.x);
    expect(layout.decision.x).toBeLessThan(layout.a.x);
  });

  it("centers siblings vertically around the parent axis", () => {
    const ys = ["a", "b", "c"].map((id) => centerY(layout, id, "state")).sort((p, q) => p - q);
    expect(ys[1]).toBeCloseTo(centerY(layout, "decision", "decision"), 0);
    expect(ys[0]).toBeLessThan(ys[1]);
    expect(ys[2]).toBeGreaterThan(ys[1]);
  });

  it("gives every node a unique position", () => {
    const keys = new Set(nodes.map((n) => `${layout[n.id].x},${layout[n.id].y}`));
    expect(keys.size).toBe(nodes.length);
  });
});

describe("graph layout beyond depth 2", () => {
  // reality -> fork -> branch -> fork -> branch: the shape expansion produces,
  // which the old hardcoded 3-column layout collapsed into one stack.
  const nodes = [
    node("root", "reality"),
    node("fork1", "decision"),
    node("a", "state"),
    node("b", "state"),
    node("fork2", "decision"),
    node("a1", "state"),
    node("a2", "state"),
  ];
  const edges = [
    edge("root", "fork1"),
    edge("fork1", "a"),
    edge("fork1", "b"),
    edge("a", "fork2"),
    edge("fork2", "a1"),
    edge("fork2", "a2"),
  ];
  const layout = computeLayout(nodes, edges);

  it("keeps every depth in its own column", () => {
    const columns = [layout.root.x, layout.fork1.x, layout.a.x, layout.fork2.x, layout.a1.x];
    for (let i = 1; i < columns.length; i += 1) {
      expect(columns[i]).toBeGreaterThan(columns[i - 1]);
    }
  });

  it("does not stack a grandchild on top of its grandparent", () => {
    expect(layout.a1.x).not.toBe(layout.a.x);
    expect(layout.a1.x).toBeGreaterThan(layout.b.x);
  });

  it("separates every node at depth 4", () => {
    expect(layout.a1.y).not.toBe(layout.a2.y);
  });

  it("ignores edges pointing at nodes that are not present yet", () => {
    const partial = computeLayout(nodes, [...edges, edge("a2", "not-merged-yet")]);
    expect(Object.keys(partial)).toHaveLength(nodes.length);
    expect(partial["not-merged-yet"]).toBeUndefined();
  });
});

describe("unexpanded fork sizing", () => {
  /**
   * An unexpanded fork renders an extra "Explore this fork" button, so it must
   * be laid out taller than an expanded one - otherwise the button overlaps
   * whatever dagre placed beneath it.
   */
  const forkNode = (id: string, expanded: boolean): GraphNode => ({
    ...node(id, "decision"),
    metadata: { expanded },
  });

  it("gives an unexpanded fork more vertical room than an expanded one", () => {
    const siblings = [
      node("root", "reality"),
      forkNode("open", false),
      forkNode("done", true),
    ];
    const layout = computeLayout(siblings, [edge("root", "open"), edge("root", "done")]);

    const gap = Math.abs(layout.open.y - layout.done.y);
    expect(gap).toBeGreaterThanOrEqual(UNEXPANDED_DECISION_HEIGHT);
  });

  it("leaves an expanded fork at the standard decision height", () => {
    const pair = [node("root", "reality"), forkNode("done", true), node("x", "state")];
    const layout = computeLayout(pair, [edge("root", "done"), edge("done", "x")]);
    expect(layout.done).toBeDefined();
    expect(UNEXPANDED_DECISION_HEIGHT).toBeGreaterThan(NODE_SIZE.decision.height);
  });
});
