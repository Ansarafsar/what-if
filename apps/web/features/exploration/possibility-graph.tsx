"use client";

import { useCallback, useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { EvidenceChip } from "@/components/ui/evidence-chip";
import { BranchDetailSheet } from "@/features/exploration/branch-detail";
import { ComparePanel } from "@/features/exploration/compare-panel";
import { hasChildren, useGraphStore } from "@/features/exploration/graph-store";
import type { GraphNode, PossibilityGraph } from "@/lib/api";
import { computeLayout } from "@/lib/graph-layout";
import { cn } from "@/lib/utils";

const PLAUSIBILITY_BAR: Record<string, string> = {
  high: "bg-success",
  medium: "bg-yellow-500",
  low: "bg-orange-500",
  speculative: "bg-muted-foreground",
};

const MAX_EDGE_LABEL = 34;

/** Edge labels sit between columns; a whole sentence there overlaps the graph. */
function truncateLabel(text: string): string {
  const clean = text.trim();
  if (clean.length <= MAX_EDGE_LABEL) return clean;
  return `${clean.slice(0, MAX_EDGE_LABEL - 1).trimEnd()}…`;
}

/** The evidence band a projected outcome carries; forks and reality are given. */
function bandFor(node: GraphNode): string {
  if (node.node_type === "reality") return "grounded";
  if (node.node_type === "decision") return "inferred";
  return node.plausibility === "speculative" ? "speculative" : "assumed";
}

type NodeData = {
  node: GraphNode;
  expandable: boolean;
  expanded: boolean;
  expanding: boolean;
  onExpand: (id: string) => void;
};

function RealityNode({ data }: NodeProps) {
  const { node } = data as unknown as NodeData;
  return (
    <div className="w-[220px] rounded-2xl border-2 border-primary bg-card px-5 py-3 text-center shadow-lg">
      <Handle type="source" position={Position.Right} />
      <p className="text-xs font-semibold uppercase tracking-widest text-primary">Reality</p>
      <p className="text-sm font-medium">{node.title}</p>
    </div>
  );
}

function DecisionNode({ data }: NodeProps) {
  const { node } = data as unknown as NodeData;
  const unexplored = node.metadata.expanded === false;
  return (
    <div
      className={cn(
        "w-[260px] rounded-lg border-2 px-4 py-3 shadow-lg",
        unexplored
          ? "border-dashed border-purple-400 bg-purple-500/5"
          : "border-purple-500 bg-purple-500/10"
      )}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <p className="text-[10px] font-semibold uppercase tracking-widest text-purple-600 dark:text-purple-400">
        {unexplored ? "Unexplored fork" : "Fork point"}
      </p>
      <p className="text-sm font-medium leading-snug">
        {node.metadata.question ?? node.description}
      </p>
    </div>
  );
}

function StateNode({ data, selected }: NodeProps) {
  const { node, expandable, expanded, expanding, onExpand } = data as unknown as NodeData;
  return (
    <div
      className={cn(
        "w-[280px] rounded-xl border bg-card p-4 text-left shadow-md transition-shadow hover:shadow-lg",
        selected ? "border-primary ring-2 ring-primary/40" : "border-border"
      )}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] uppercase tracking-wide text-secondary-foreground">
          {node.metadata.strategy ?? "path"}
        </span>
        <div className="flex items-center gap-1.5">
          <EvidenceChip type={bandFor(node)} compact />
          {node.metadata.reversible && (
            <span title="Reversible path" className="text-[10px] text-success">
              ↺ reversible
            </span>
          )}
        </div>
      </div>
      <p className="mb-2 text-sm font-semibold leading-snug">{node.title}</p>
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase text-muted-foreground">{node.plausibility}</span>
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            className={cn("h-full rounded-full", PLAUSIBILITY_BAR[node.plausibility ?? "speculative"])}
            style={{ width: `${Math.round((node.score ?? 0) * 100)}%` }}
          />
        </div>
        <span className="text-[10px] tabular-nums text-muted-foreground">
          {(node.score ?? 0).toFixed(2)}
        </span>
      </div>

      {expandable && !expanded && (
        <button
          type="button"
          data-testid={`expand-${node.id}`}
          disabled={expanding}
          onClick={(event) => {
            event.stopPropagation();
            onExpand(node.id);
          }}
          className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:opacity-60"
        >
          {expanding ? (
            <>
              <span className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" />
              Forking from here…
            </>
          ) : (
            <>▸ Fork again from here</>
          )}
        </button>
      )}
      {expanded && (
        <p className="mt-3 text-center text-[11px] text-muted-foreground">Expanded</p>
      )}
    </div>
  );
}

const nodeTypes = { reality: RealityNode, decision: DecisionNode, state: StateNode };

export function PossibilityGraphView({
  graph,
  scenarioId,
  onExpand,
  onNodeSelect,
}: {
  graph: PossibilityGraph;
  scenarioId: string;
  onExpand: (nodeId: string) => void;
  onNodeSelect?: (node: GraphNode) => void;
}) {
  const selectedId = useGraphStore((s) => s.selectedId);
  const compareId = useGraphStore((s) => s.compareId);
  const expanding = useGraphStore((s) => s.expanding);
  const expandErrors = useGraphStore((s) => s.expandErrors);
  const select = useGraphStore((s) => s.select);
  const toggleCompare = useGraphStore((s) => s.toggleCompare);

  const maxDepth = useMemo(
    () => Math.max(0, ...graph.nodes.map((n) => Number(n.metadata.depth ?? 0))),
    [graph.nodes]
  );

  const { flowNodes, flowEdges } = useMemo(() => {
    const positions = computeLayout(graph.nodes, graph.edges);
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));

    const flowNodes: Node[] = graph.nodes.map((node) => ({
      id: node.id,
      type: node.node_type,
      position: positions[node.id] ?? { x: 0, y: 0 },
      selected: node.id === selectedId || node.id === compareId,
      data: {
        node,
        expandable: node.node_type === "state",
        expanded: hasChildren(graph, node.id),
        expanding: expanding.has(node.id),
        onExpand,
      } satisfies NodeData as unknown as Record<string, unknown>,
      draggable: false,
    }));

    const flowEdges: Edge[] = graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source_id,
      target: edge.target_id,
      // A fork's question can run to a full sentence, which printed straight
      // across the neighbouring node. The node itself carries the full text.
      label: truncateLabel(edge.transition),
      labelShowBg: true,
      labelBgPadding: [6, 3] as [number, number],
      labelBgBorderRadius: 4,
      labelStyle: { fontSize: 10 },
      style: {
        strokeDasharray:
          byId.get(edge.target_id)?.plausibility === "speculative" ? "6 4" : undefined,
      },
    }));
    return { flowNodes, flowEdges };
  }, [graph, selectedId, compareId, expanding, onExpand]);

  const selected = graph.nodes.find((n) => n.id === selectedId) ?? null;
  const compared = graph.nodes.find((n) => n.id === compareId) ?? null;

  const handleNodeClick = useCallback(
    (event: React.MouseEvent, flowNode: Node) => {
      const found = graph.nodes.find((n) => n.id === flowNode.id);
      if (!found) return;
      // Shift-click picks the second node for a comparison rather than
      // replacing the selection.
      if (event.shiftKey && found.node_type === "state") {
        toggleCompare(found.id);
        return;
      }
      select(found.id);
      onNodeSelect?.(found);
    },
    [graph.nodes, onNodeSelect, select, toggleCompare]
  );

  const currentError = selectedId ? expandErrors[selectedId] : undefined;

  return (
    <div className="space-y-4" data-testid="possibility-graph">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span data-testid="graph-depth">
          {graph.nodes.length} nodes · depth {maxDepth}
        </span>
        <span>Click a branch to inspect it · shift-click a second branch to compare</span>
      </div>

      <div className="h-[520px] w-full overflow-hidden rounded-xl border bg-card">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.2}
          nodesConnectable={false}
          onNodeClick={handleNodeClick}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      {currentError && (
        <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive" role="alert">
          {currentError}
        </p>
      )}

      {selected && compared && (
        <ComparePanel scenarioId={scenarioId} left={selected} right={compared} />
      )}

      {selected && <BranchDetailSheet node={selected} onClose={() => select(null)} />}
    </div>
  );
}
