"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
  type OnNodeDrag,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { EvidenceChip } from "@/components/ui/evidence-chip";
import { BranchDetailSheet } from "@/features/exploration/branch-detail";
import { ComparePanel } from "@/features/exploration/compare-panel";
import { hasChildren, useGraphStore } from "@/features/exploration/graph-store";
import type { GraphNode, PossibilityGraph } from "@/lib/api";
import { computeLayout } from "@/lib/graph-layout";
import { cn } from "@/lib/utils";

/**
 * The bar's length is the score, so its colour has to be the score too.
 * Colouring by plausibility while sizing by score made a short bar green and a
 * longer one yellow, because plausibility is only 25% of the weighted score -
 * the other factors routinely invert the ordering.
 */
function scoreBar(score: number): string {
  if (score >= 0.66) return "bg-success";
  if (score >= 0.33) return "bg-yellow-500";
  return "bg-orange-500";
}

const MAX_EDGE_LABEL = 24;

/** Edge labels sit between columns; a whole sentence there overlaps the graph. */
function truncateLabel(text: string): string {
  const clean = text.trim();
  if (clean.length <= MAX_EDGE_LABEL) return clean;
  return `${clean.slice(0, MAX_EDGE_LABEL - 1).trimEnd()}…`;
}

/** Minimap dots read as the graph's shape, so they follow the node type. */
function miniMapColor(node: Node): string {
  if (node.type === "reality") return "#6d5ce7";
  if (node.type === "decision") return "#a78bfa";
  return "#94a3b8";
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
    <div className="h-[80px] w-[220px] overflow-hidden rounded-2xl border-2 border-primary bg-card px-5 py-3 text-center shadow-lg">
      <Handle type="source" position={Position.Right} />
      <p className="text-xs font-semibold uppercase tracking-widest text-primary">Reality</p>
      {/* Clamped: dagre reserves NODE_SIZE.reality, so unbounded wrapping here
          would grow the node past its reserved slot and overlap its neighbour. */}
      <p className="line-clamp-2 text-sm font-medium" title={node.title}>
        {node.title}
      </p>
    </div>
  );
}

function DecisionNode({ data }: NodeProps) {
  const { node } = data as unknown as NodeData;
  const unexplored = node.metadata.expanded === false;
  return (
    <div
      className={cn(
        "h-[96px] w-[260px] overflow-hidden rounded-lg border-2 px-4 py-3 shadow-lg",
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
      {/* A fork question is often a full sentence; clamping keeps the node at
          the height dagre laid out for it. Full text is in the detail sheet. */}
      <p
        className="line-clamp-3 text-sm font-medium leading-snug"
        title={node.metadata.question ?? node.description}
      >
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
        "flex h-[156px] w-[280px] flex-col overflow-hidden rounded-xl border bg-card p-4 text-left shadow-md transition-shadow hover:shadow-lg",
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
          {node.plausibility && (
            <span
              title={`Plausibility: ${node.plausibility}`}
              className="text-[10px] uppercase tracking-wide text-muted-foreground"
            >
              {node.plausibility}
            </span>
          )}
          <EvidenceChip type={bandFor(node)} compact />
          {node.metadata.reversible && (
            <span title="Reversible path" className="text-[10px] text-success">
              ↺
            </span>
          )}
        </div>
      </div>
      <p className="mb-2 line-clamp-2 text-sm font-semibold leading-snug" title={node.title}>
        {node.title}
      </p>
      {/* Pushes the score bar and action to the card's foot, so cards with a
          one-line and a two-line title still align and stay the same height. */}
      <div className="flex-1" />
      <div
        className="flex items-center gap-2"
        title={`score ${(node.score ?? 0).toFixed(2)} · plausibility ${node.plausibility ?? "unrated"}`}
      >
        <span className="text-[10px] uppercase text-muted-foreground">score</span>
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            className={cn("h-full rounded-full", scoreBar(node.score ?? 0))}
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

  // React Flow owns node state so nodes can be dragged. The dagre layout stays
  // the source of truth for *which* nodes exist and where they start; hand-moved
  // positions are kept in their own ref so they survive a re-derivation
  // (expanding a node, changing the selection) without snapping back.
  //
  // The overrides have to live outside node state: reading them back off the
  // current nodes would make "reset" impossible, because the sync effect would
  // immediately restore the very positions reset just cleared.
  const dragged = useRef<Map<string, { x: number; y: number }>>(new Map());

  // A different scenario is a different graph; its node ids should not inherit
  // positions the user dragged to on the previous one.
  useEffect(() => {
    dragged.current.clear();
  }, [scenarioId]);

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node>(flowNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge>(flowEdges);

  useEffect(() => {
    setRfNodes(
      flowNodes.map((n) => ({ ...n, position: dragged.current.get(n.id) ?? n.position }))
    );
  }, [flowNodes, setRfNodes]);

  useEffect(() => setRfEdges(flowEdges), [flowEdges, setRfEdges]);

  const handleNodeDragStop = useCallback<OnNodeDrag<Node>>((_event, node) => {
    dragged.current.set(node.id, node.position);
  }, []);

  /** Drop hand-dragged positions and return to the computed dagre layout. */
  const resetLayout = useCallback(() => {
    dragged.current.clear();
    setRfNodes(flowNodes);
  }, [flowNodes, setRfNodes]);

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
        <span className="flex items-center gap-3">
          <span>Click to inspect · shift-click to compare · drag to rearrange</span>
          <button
            type="button"
            onClick={resetLayout}
            data-testid="reset-layout"
            className="rounded-md border px-2 py-0.5 transition-colors hover:border-primary hover:text-primary"
          >
            Reset layout
          </button>
        </span>
      </div>

      <div className="h-[70vh] max-h-[760px] min-h-[420px] w-full overflow-hidden rounded-xl border bg-card">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          // Extra bottom padding keeps the last rank clear of the minimap,
          // which floats over the bottom-right corner of the canvas.
          fitViewOptions={{ padding: 0.18 }}
          minZoom={0.15}
          maxZoom={1.5}
          nodesDraggable
          nodesConnectable={false}
          elevateNodesOnSelect
          onNodeClick={handleNodeClick}
          onNodeDragStop={handleNodeDragStop}
          proOptions={{ hideAttribution: false }}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} />
          <Controls showInteractive={false} />
          {/* Floats over the canvas, so it is small, faded until hovered, and
              hidden on small screens where it would cover most of the graph. */}
          <MiniMap
            pannable
            zoomable
            nodeStrokeWidth={2}
            nodeColor={miniMapColor}
            style={{ width: 132, height: 88 }}
            className="!bg-card/80 !hidden !rounded-lg !border opacity-60 transition-opacity hover:opacity-100 md:!block"
          />
        </ReactFlow>
      </div>

      {/* Node shape and colour carry meaning; without a key the graph is a
          pile of boxes on first look. */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-2.5 rounded-full border-2 border-primary" />
          Reality — what you told us
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-2.5 rounded-sm border-2 border-purple-500 bg-purple-500/20" />
          Fork point
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-2.5 rounded-sm border-2 border-dashed border-purple-400" />
          Unexplored fork
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-2.5 w-2.5 rounded-sm border border-border bg-card" />
          Outcome — bar shows score
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg aria-hidden width="18" height="6" viewBox="0 0 18 6">
            <line x1="0" y1="3" x2="18" y2="3" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" />
          </svg>
          Dashed edge — speculative
        </span>
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
