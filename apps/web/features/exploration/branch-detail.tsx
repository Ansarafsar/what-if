"use client";

import { useEffect } from "react";

import { EvidenceChip } from "@/components/ui/evidence-chip";
import type { GraphNode } from "@/lib/api";
import { cn } from "@/lib/utils";

const DIRECTION_ARROW = { up: "↑", down: "↓", flat: "→", uncertain: "?" } as const;

function Section({ title, children, tone }: { title: string; children: React.ReactNode; tone?: "danger" }) {
  return (
    <section className="mb-5">
      <h4
        className={cn(
          "mb-2 text-xs font-semibold uppercase tracking-wider",
          tone === "danger" ? "text-destructive" : "text-muted-foreground"
        )}
      >
        {title}
      </h4>
      {children}
    </section>
  );
}

/** "Why did this branch rank here?" - PRD 48, from score_breakdown. */
function ScoreBreakdown({ breakdown }: { breakdown: Record<string, number> }) {
  const entries = Object.entries(breakdown);
  if (entries.length === 0) return null;
  const scale = Math.max(...entries.map(([, value]) => Math.abs(value)), 0.01);

  return (
    <ul className="space-y-1.5" data-testid="score-breakdown">
      {entries.map(([label, value]) => (
        <li key={label} className="grid grid-cols-[7rem_1fr_3rem] items-center gap-2 text-xs">
          <span className="capitalize text-muted-foreground">{label.replace(/_/g, " ")}</span>
          <span className="relative flex h-2 items-center rounded-full bg-muted">
            <span
              className={cn(
                "absolute h-2 rounded-full",
                value >= 0 ? "left-1/2 bg-success" : "right-1/2 bg-destructive"
              )}
              style={{ width: `${(Math.abs(value) / scale) * 50}%` }}
            />
          </span>
          <span className="text-right tabular-nums text-muted-foreground">{value.toFixed(3)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Before → after, straight from the branch's state_delta. */
function StateDelta({ delta }: { delta: Record<string, unknown> }) {
  const entries = Object.entries(delta);
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing changes yet on this path.</p>;
  }
  return (
    <table className="w-full text-sm" data-testid="state-delta">
      <thead>
        <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
          <th className="pb-1 font-medium">Variable</th>
          <th className="pb-1 font-medium">Before</th>
          <th className="pb-1 font-medium">After</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([key, value]) => {
          const pair = Array.isArray(value) && value.length === 2;
          return (
            <tr key={key} className="border-t">
              <td className="py-1 pr-2 font-medium">{key}</td>
              <td className="py-1 pr-2 text-muted-foreground">
                {pair ? String((value as unknown[])[0]) : "—"}
              </td>
              <td className="py-1">{String(pair ? (value as unknown[])[1] : value)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function DecisionBody({ node }: { node: GraphNode }) {
  const unexplored = node.metadata.expanded === false;
  return (
    <>
      <Section title="Question">
        <p className="text-sm">{node.metadata.question ?? node.description}</p>
      </Section>
      {typeof node.metadata.importance === "number" && (
        <Section title="Importance">
          <p className="text-sm tabular-nums">{node.metadata.importance.toFixed(2)}</p>
        </Section>
      )}
      {unexplored && (
        <p className="rounded-md bg-purple-500/10 p-3 text-xs text-purple-700 dark:text-purple-300">
          This fork was detected but not expanded. Its branches have not been generated yet.
        </p>
      )}
    </>
  );
}

function RealityBody({ node }: { node: GraphNode }) {
  const state = node.metadata.resulting_state;
  return (
    <>
      <Section title="Summary">
        <p className="text-sm text-muted-foreground">{node.description}</p>
      </Section>
      {state && state.facts.length > 0 && (
        <Section title="Evidence">
          <ul className="space-y-1.5" data-testid="evidence-chips">
            {state.facts.map((fact, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <EvidenceChip type={fact.evidence_type} />
                <span>{fact.claim}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}

function StateBody({ node }: { node: GraphNode }) {
  const evidence = node.metadata.evidence ?? {};
  const violations = evidence.constraint_violations ?? [];
  const state = node.metadata.resulting_state;

  return (
    <>
      <p className="mb-5 whitespace-pre-line text-sm text-muted-foreground">{node.description}</p>

      {violations.length > 0 && (
        <div
          className="mb-5 rounded-md border border-destructive/40 bg-destructive/10 p-3"
          data-testid="constraint-violations"
          role="alert"
        >
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-destructive">
            Constraint violations
          </p>
          <ul className="space-y-1 text-sm text-destructive">
            {violations.map((violation, i) => (
              <li key={i}>⚠ {violation}</li>
            ))}
          </ul>
        </div>
      )}

      {node.metadata.rationale && (
        <Section title="Why did this appear?">
          <p className="text-sm" data-testid="rationale">
            {node.metadata.rationale}
          </p>
        </Section>
      )}

      <Section title="Effects">
        <ul className="space-y-1.5">
          {(node.metadata.effects ?? []).map((effect, i) => (
            <li key={i} className="flex items-start gap-2 text-sm">
              <span
                className={cn(
                  "mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                  effect.direction === "up" && "bg-success/15 text-success",
                  effect.direction === "down" && "bg-destructive/15 text-destructive",
                  (effect.direction === "flat" || effect.direction === "uncertain") &&
                    "bg-muted text-muted-foreground"
                )}
              >
                {DIRECTION_ARROW[effect.direction]}
              </span>
              <span>
                <span className="font-medium">{effect.dimension}</span>
                <span className="text-muted-foreground">
                  {" "}
                  ({effect.magnitude}, {effect.order > 1 ? `${effect.order}nd-order` : "direct"}) —{" "}
                </span>
                {effect.explanation}
              </span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="What changes in your world">
        <StateDelta delta={node.metadata.state_delta ?? {}} />
      </Section>

      <Section title="Why this ranked here">
        <ScoreBreakdown breakdown={node.metadata.score_breakdown ?? {}} />
      </Section>

      <Section title="Assumptions">
        <ul className="space-y-1 text-sm">
          {(evidence.assumptions ?? []).map((assumption, i) => (
            <li key={i}>
              <EvidenceChip type="assumed" compact /> {assumption.claim}
              {assumption.depends_on.length > 0 && (
                <span className="block pl-3 text-xs text-muted-foreground">
                  depends on: {assumption.depends_on.join(", ")}
                </span>
              )}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Why this plausibility?">
        <ul className="space-y-1 text-sm">
          {(evidence.grounded_reasons ?? []).map((reason, i) => (
            <li key={i}>• {reason}</li>
          ))}
        </ul>
      </Section>

      {(evidence.risks ?? []).length > 0 && (
        <Section title="Risks" tone="danger">
          <ul className="space-y-1 text-sm">
            {evidence.risks!.map((risk, i) => (
              <li key={i}>• {risk}</li>
            ))}
          </ul>
        </Section>
      )}

      {evidence.critic && evidence.critic.verdict !== "pass" && (
        <p className="rounded-md bg-yellow-500/10 p-2 text-xs text-yellow-700 dark:text-yellow-400">
          Critic ({evidence.critic.verdict}): {evidence.critic.issues.join("; ")}
        </p>
      )}

      {state && state.state_variables && Object.keys(state.state_variables).length > 0 && (
        <Section title="World after this choice">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            {Object.entries(state.state_variables).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-muted-foreground">{key}</dt>
                <dd className="tabular-nums">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </Section>
      )}
    </>
  );
}

/**
 * Detail as a side sheet rather than a below-the-fold block, and for every node
 * type - clicking a fork used to show nothing at all.
 */
export function BranchDetailSheet({ node, onClose }: { node: GraphNode; onClose: () => void }) {
  const path = node.metadata.path_labels ?? [];

  // The sheet covers the graph on small screens, so Escape and a click on the
  // backdrop have to dismiss it - the ✕ was previously the only way out.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div
        className="fixed inset-0 z-30 bg-background/60 backdrop-blur-[2px] md:bg-transparent md:backdrop-blur-none"
        onClick={onClose}
        aria-hidden
      />
      <aside
        className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l bg-card shadow-2xl"
        data-testid="branch-detail"
        role="dialog"
        aria-modal="true"
        aria-label={`Details for ${node.title}`}
      >
        <div className="sticky top-0 flex items-start justify-between gap-3 border-b bg-card/95 p-5 backdrop-blur">
          <div className="min-w-0">
            {path.length > 0 && (
              <p
                className="mb-1 truncate text-[11px] text-muted-foreground"
                title={path.join(" → ")}
                data-testid="path-labels"
              >
                {path.join(" → ")}
              </p>
            )}
            <h3 className="text-base font-semibold">{node.title}</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close details"
            className="shrink-0 rounded-md px-2 py-1 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            {node.plausibility && (
              <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-secondary-foreground">
                plausibility: {node.plausibility}
              </span>
            )}
            {node.score !== null && (
              <span className="rounded-full bg-secondary px-2 py-0.5 text-xs tabular-nums text-secondary-foreground">
                score {node.score.toFixed(2)}
              </span>
            )}
            {typeof node.metadata.depth === "number" && (
              <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-secondary-foreground">
                depth {node.metadata.depth}
              </span>
            )}
          </div>

          {node.node_type === "state" && <StateBody node={node} />}
          {node.node_type === "decision" && <DecisionBody node={node} />}
          {node.node_type === "reality" && <RealityBody node={node} />}
        </div>
      </aside>
    </>
  );
}
