import { create } from "zustand";

import type { GraphEdge, GraphNode, PossibilityGraph } from "@/lib/api";

/**
 * Graph, selection and per-node expansion state.
 *
 * The workspace previously held everything in a linear `Phase` union, which
 * could not represent "viewing the graph AND expanding node 7" - the two states
 * the exploration loop lives in. Expansion is tracked as a set so several nodes
 * can be in flight at once, each with its own spinner.
 */
export interface GraphStore {
  graph: PossibilityGraph | null;
  selectedId: string | null;
  compareId: string | null;
  expanding: Set<string>;
  expandErrors: Record<string, string>;

  setGraph: (graph: PossibilityGraph | null) => void;
  mergeSubgraph: (nodes: GraphNode[], edges: GraphEdge[]) => void;
  select: (id: string | null) => void;
  toggleCompare: (id: string) => void;
  clearCompare: () => void;
  startExpanding: (id: string) => void;
  finishExpanding: (id: string, error?: string) => void;
  reset: () => void;
}

/** Merge without duplicating: expansion returns nodes we may already hold. */
function mergeById<T extends { id: string }>(existing: T[], incoming: T[]): T[] {
  const seen = new Map(existing.map((item) => [item.id, item]));
  for (const item of incoming) seen.set(item.id, item);
  return [...seen.values()];
}

export const useGraphStore = create<GraphStore>((set) => ({
  graph: null,
  selectedId: null,
  compareId: null,
  expanding: new Set<string>(),
  expandErrors: {},

  setGraph: (graph) => set({ graph, selectedId: null, compareId: null }),

  mergeSubgraph: (nodes, edges) =>
    set((state) => {
      if (!state.graph) return state;
      return {
        graph: {
          ...state.graph,
          nodes: mergeById(state.graph.nodes, nodes),
          edges: mergeById(state.graph.edges, edges),
        },
      };
    }),

  select: (id) => set({ selectedId: id }),

  toggleCompare: (id) =>
    set((state) => ({
      // Shift-clicking the node that is already the comparison clears it.
      compareId: state.compareId === id ? null : id === state.selectedId ? state.compareId : id,
    })),

  clearCompare: () => set({ compareId: null }),

  startExpanding: (id) =>
    set((state) => {
      const expanding = new Set(state.expanding);
      expanding.add(id);
      // A fresh attempt clears the previous failure for this node.
      const expandErrors = { ...state.expandErrors };
      delete expandErrors[id];
      return { expanding, expandErrors };
    }),

  finishExpanding: (id, error) =>
    set((state) => {
      const expanding = new Set(state.expanding);
      expanding.delete(id);
      return {
        expanding,
        expandErrors: error ? { ...state.expandErrors, [id]: error } : state.expandErrors,
      };
    }),

  reset: () =>
    set({
      graph: null,
      selectedId: null,
      compareId: null,
      expanding: new Set<string>(),
      expandErrors: {},
    }),
}));

/** True when this node already has children in the loaded graph. */
export function hasChildren(graph: PossibilityGraph | null, nodeId: string): boolean {
  return Boolean(graph?.edges.some((edge) => edge.source_id === nodeId));
}
