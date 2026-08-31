"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PossibilityGraphView } from "@/features/exploration/possibility-graph";
import { RealityReview } from "@/features/exploration/reality-review";
import { useGraphStore } from "@/features/exploration/graph-store";
import {
  expandNode,
  extractReality,
  getGraph,
  getReality,
  type RealityState,
} from "@/lib/api";
import { streamGeneration } from "@/lib/generation-stream";

/**
 * Loading and extraction are server state, so TanStack Query owns them. Only
 * the states the user drives - generating, then exploring - are local.
 */
type LocalPhase = "idle" | "generating" | "graph";

interface Bootstrap {
  reality: RealityState;
  mock: boolean;
  graphLoaded: boolean;
}

/** Fetch the reality state, extracting it first if this is a fresh scenario. */
async function bootstrapScenario(scenarioId: string): Promise<Bootstrap> {
  const existing = await getReality(scenarioId).catch(() => null);
  if (existing) {
    return { reality: existing.state, mock: existing.mock, graphLoaded: true };
  }
  const extracted = await extractReality(scenarioId);
  return { reality: extracted.state, mock: extracted.mock, graphLoaded: false };
}

const EXTRACT_STEPS = [
  "Reading your situation…",
  "Separating facts from assumptions…",
  "Marking what is unknown…",
];

function Spinner({ label, detail }: { label: string; detail?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <span className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      <p className="text-sm text-muted-foreground">{label}</p>
      {detail && <p className="text-xs text-muted-foreground/70">{detail}</p>}
    </div>
  );
}

/** Extraction is a single blocking call, so a rotating hint is honest here. */
function RotatingHint({ steps }: { steps: string[] }) {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setIndex((i) => (i + 1) % steps.length), 4000);
    return () => clearInterval(timer);
  }, [steps.length]);
  return <Spinner label={steps[index]} detail="This runs several reasoning passes." />;
}

/** Generation reports the stage the engine actually finished. */
function StageProgress({ stages }: { stages: { label: string; iteration: number }[] }) {
  const current = stages[stages.length - 1];
  return (
    <div className="flex flex-col items-center gap-3 py-12" data-testid="stage-progress">
      <span className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      <p className="text-sm font-medium">{current?.label ?? "Starting the engine…"}</p>
      {current && current.iteration > 0 && (
        <p className="text-xs text-muted-foreground">
          Revision pass {current.iteration} — repairing branches that failed review
        </p>
      )}
      <ol className="mt-2 space-y-1 text-xs text-muted-foreground">
        {stages.slice(0, -1).map((stage, i) => (
          <li key={`${stage.label}-${i}`}>✓ {stage.label}</li>
        ))}
      </ol>
    </div>
  );
}

export function ScenarioWorkspace({ scenarioId }: { scenarioId: string }) {
  const [phase, setPhase] = useState<LocalPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [mockOverride, setMockOverride] = useState<boolean | null>(null);
  const [stages, setStages] = useState<{ label: string; iteration: number }[]>([]);

  const graph = useGraphStore((s) => s.graph);
  const setGraph = useGraphStore((s) => s.setGraph);
  const mergeSubgraph = useGraphStore((s) => s.mergeSubgraph);
  const startExpanding = useGraphStore((s) => s.startExpanding);
  const finishExpanding = useGraphStore((s) => s.finishExpanding);
  const reset = useGraphStore((s) => s.reset);

  const abortRef = useRef<AbortController | null>(null);

  const bootstrap = useQuery({
    queryKey: ["scenario", scenarioId],
    queryFn: () => bootstrapScenario(scenarioId),
    retry: false,
    staleTime: Infinity,
  });

  // A graph saved on an earlier visit loads alongside the reality state.
  const savedGraph = useQuery({
    queryKey: ["graph", scenarioId],
    queryFn: () => getGraph(scenarioId).catch(() => null),
    enabled: bootstrap.data?.graphLoaded === true,
    retry: false,
    staleTime: Infinity,
  });

  useEffect(() => () => reset(), [reset, scenarioId]);
  useEffect(() => () => abortRef.current?.abort(), []);

  // Adopting a previously saved graph is a store sync, not a render-time state
  // update, so it belongs in an effect - but only once, when it arrives.
  useEffect(() => {
    if (savedGraph.data && !graph) {
      setGraph(savedGraph.data);
    }
  }, [savedGraph.data, graph, setGraph]);

  const reality = bootstrap.data?.reality ?? null;
  const isMock = mockOverride ?? bootstrap.data?.mock ?? false;
  const showGraph = phase === "graph" || (phase === "idle" && Boolean(graph));

  const runGeneration = useCallback(async () => {
    setError(null);
    setStages([]);
    setPhase("generating");

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      let failed: string | null = null;
      await streamGeneration(
        scenarioId,
        (event) => {
          if (event.type === "stage") {
            setStages((prev) => [...prev, { label: event.label, iteration: event.iteration }]);
          } else if (event.type === "complete") {
            setMockOverride(event.mock);
          } else if (event.type === "error") {
            failed = event.detail;
          }
        },
        controller.signal
      );
      if (failed) throw new Error(failed);

      setGraph(await getGraph(scenarioId));
      setPhase("graph");
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : "Generation failed");
      setPhase("idle");
    }
  }, [scenarioId, setGraph]);

  const expansion = useMutation({
    mutationFn: (nodeId: string) => expandNode(scenarioId, nodeId),
    onMutate: (nodeId: string) => startExpanding(nodeId),
    onSuccess: (data) => {
      mergeSubgraph(data.nodes, data.edges);
      finishExpanding(data.node_id);
    },
    onError: (err, nodeId) => {
      finishExpanding(nodeId, err instanceof Error ? err.message : "Expansion failed");
    },
  });

  const handleExpand = useCallback(
    (nodeId: string) => expansion.mutate(nodeId),
    [expansion]
  );

  if (bootstrap.isPending) return <RotatingHint steps={EXTRACT_STEPS} />;

  if (bootstrap.isError) {
    const message =
      bootstrap.error instanceof Error ? bootstrap.error.message : "Extraction failed";
    const isRateLimit = message.includes("429") || message.toLowerCase().includes("rate limit");
    // A schema mismatch is permanent: the request succeeded and the payload
    // failed to parse, so telling the user to try again would be a lie.
    const isContractError = message.startsWith("Unexpected response from");
    return (
      <Card>
        <CardContent className="space-y-4 p-6 text-center">
          <p className="text-sm font-medium text-destructive">
            {isRateLimit
              ? "The AI service hit its daily usage limit."
              : isContractError
                ? "The API returned data this build does not understand."
                : "Extraction failed — the AI service may be temporarily overloaded."}
          </p>
          <p className="text-xs text-muted-foreground">
            {isRateLimit
              ? "Free tier resets at midnight UTC. Try again tomorrow, or add credits to your OpenRouter account."
              : isContractError
                ? "Retrying will not help — the frontend and backend are out of sync."
                : "This usually resolves on its own. Try again in a moment."}
          </p>
          {/* The precise reason, so a contract mismatch is diagnosable from the
              screen instead of only from the console. */}
          <p className="text-xs text-muted-foreground/70 break-words">{message}</p>
          <Button variant="outline" onClick={() => void bootstrap.refetch()}>
            Retry extraction
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {isMock && (
        <p
          className="rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-xs text-yellow-700 dark:text-yellow-400"
          data-testid="mock-banner"
          role="status"
        >
          Demo mode: these answers come from canned fixtures, not a live model. Set
          <code className="mx-1">LLM_PROVIDER=openrouter</code> for real reasoning.
        </p>
      )}

      {reality && !showGraph && <RealityReview state={reality} />}

      {error && (
        <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      {phase === "idle" && !graph && (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-6 text-center">
          <Button size="lg" onClick={() => void runGeneration()} data-testid="generate-button">
            Map possibilities
          </Button>
          <p className="max-w-lg text-xs leading-relaxed text-muted-foreground">
            Runs fork detection → candidate generation → consequence projection → adversarial
            review → revision → ranking. Branches that fail review are regenerated, not
            silently dropped.
          </p>
        </div>
      )}

      {phase === "generating" && <StageProgress stages={stages} />}

      {showGraph && graph && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">Possibility space</h2>
            <p className="text-xs text-muted-foreground">
              Every branch can be forked again from its own world state.
            </p>
          </div>
          <PossibilityGraphView
            graph={graph}
            scenarioId={scenarioId}
            onExpand={handleExpand}
          />
          <details className="rounded-xl border bg-card">
            <summary className="cursor-pointer p-4 text-sm font-medium">
              Review extracted reality
            </summary>
            <div className="px-4 pb-4">{reality && <RealityReview state={reality} />}</div>
          </details>
        </>
      )}

      <Link href="/" className="block text-center text-xs text-muted-foreground hover:underline">
        ← Start a different scenario
      </Link>
    </div>
  );
}
