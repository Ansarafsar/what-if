import dagre from "dagre";

import type { GraphEdge, GraphNode } from "@/lib/api";

export interface PositionedNode {
  node: GraphNode;
  x: number;
  y: number;
}

/**
 * Rendered size per node type. Dagre needs real dimensions to avoid overlap,
 * and these match the fixed widths the node components use.
 */
export const NODE_SIZE: Record<GraphNode["node_type"], { width: number; height: number }> = {
  reality: { width: 220, height: 80 },
  decision: { width: 260, height: 96 },
  state: { width: 280, height: 132 },
};

/**
 * Lay the possibility graph out left-to-right at arbitrary depth.
 *
 * The previous implementation clamped every node past depth 2 into the same
 * column, which was invisible while the graph was exactly three tiers deep and
 * would have stacked every expanded node on top of its grandparent.
 */
export function computeLayout(
  nodes: GraphNode[],
  edges: GraphEdge[]
): Record<string, { x: number; y: number }> {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({
    rankdir: "LR",
    // Edge labels carry the branch text, so ranks need room for a label to sit
    // between two columns instead of printing across the next node.
    ranksep: 190,
    nodesep: 48,
    marginx: 20,
    marginy: 20,
  });
  graph.setDefaultEdgeLabel(() => ({}));

  const known = new Set(nodes.map((n) => n.id));
  for (const node of nodes) {
    // Dagre writes the computed x/y back into the label object, so every node
    // needs its own copy - sharing one would leave siblings stacked.
    const size = NODE_SIZE[node.node_type] ?? NODE_SIZE.state;
    graph.setNode(node.id, { ...size });
  }
  for (const edge of edges) {
    // An expansion response can reference a node the caller has not merged yet;
    // dagre would silently invent a zero-size node for it.
    if (known.has(edge.source_id) && known.has(edge.target_id)) {
      graph.setEdge(edge.source_id, edge.target_id);
    }
  }

  dagre.layout(graph);

  const positions: Record<string, { x: number; y: number }> = {};
  for (const node of nodes) {
    const laid = graph.node(node.id);
    const size = NODE_SIZE[node.node_type] ?? NODE_SIZE.state;
    // Dagre reports centres; React Flow positions by top-left corner.
    positions[node.id] = laid
      ? { x: laid.x - size.width / 2, y: laid.y - size.height / 2 }
      : { x: 0, y: 0 };
  }
  return positions;
}
