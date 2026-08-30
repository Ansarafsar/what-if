"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { EvidenceChip } from "@/components/ui/evidence-chip";
import type { RealityState } from "@/lib/api";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h4>
      {children}
    </div>
  );
}

export function RealityReview({ state }: { state: RealityState }) {
  return (
    <Card data-testid="reality-review">
      <CardContent className="space-y-5 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="default" className="uppercase" data-testid="domain-badge">
            {state.domain}
          </Badge>
          <h3 className="text-lg font-semibold">{state.title}</h3>
        </div>

        <p className="text-sm text-muted-foreground">{state.summary}</p>

        <div className="grid gap-6 md:grid-cols-2">
          <Section title="What happened">
            <ul className="space-y-1.5">
              {state.events.map((event, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <EvidenceChip type={event.evidence_type} />
                  <span>{event.description}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Decisions in play">
            <ul className="space-y-2">
              {state.decision_hints.map((hint, i) => (
                <li key={i} className="text-sm">
                  <span className="font-medium">{hint.question}</span>
                  {hint.options_hint.length > 0 && (
                    <span className="block text-xs text-muted-foreground">
                      e.g. {hint.options_hint.slice(0, 5).join(" · ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Constraints">
            <ul className="space-y-1.5">
              {state.constraints.map((constraint, i) => (
                <li key={i} className="text-sm">
                  <span className="mr-1.5 rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase text-secondary-foreground">
                    {constraint.kind}
                  </span>
                  {constraint.description}
                  {constraint.key && constraint.operator && constraint.value !== null && (
                    <code className="ml-1 text-xs text-primary">
                      ({constraint.key} {constraint.operator} {constraint.value})
                    </code>
                  )}
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Goals & beliefs">
            <ul className="space-y-1 text-sm">
              {[...state.goals, ...state.beliefs].map((goal, i) => (
                <li key={i}>• {goal}</li>
              ))}
            </ul>
          </Section>

          {(state.uncertainties.length > 0 || state.missing_information.length > 0) && (
            <Section title="Unknown / missing (never invented)">
              <ul className="space-y-1 text-sm text-muted-foreground">
                {[...state.uncertainties.map((u) => `? ${u}`), ...state.missing_information.map((m) => `✗ ${m}`)].map(
                  (item, i) => (
                    <li key={i}>{item}</li>
                  )
                )}
              </ul>
            </Section>
          )}

          {(state.relationships.length > 0 || state.resources.length > 0) && (
            <Section title="People & resources">
              <div className="flex flex-wrap gap-1.5">
                {[...state.relationships, ...state.resources].map((item, i) => (
                  <span key={i} className="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
                    {item}
                  </span>
                ))}
              </div>
            </Section>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
