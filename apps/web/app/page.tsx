import { ScenarioPrompt } from "@/features/exploration/scenario-prompt";
import { EvidenceChip } from "@/components/ui/evidence-chip";

/**
 * The landing page has to answer "what is this and why should I trust it?"
 * before the textarea is worth filling in. Three claims, each one a thing the
 * engine actually enforces rather than a marketing line.
 */
const PILLARS = [
  {
    title: "Facts, not vibes",
    body: "Every claim is tagged grounded, inferred, assumed or speculative. Missing information stays UNKNOWN — it is never invented.",
  },
  {
    title: "Code disposes",
    body: "The model proposes structured JSON; constraint checking, scoring and comparison are deterministic engines. Same input, same graph.",
  },
  {
    title: "Forkable, not final",
    body: "Every outcome stores the world it produced, so you can fork again from inside it — not from the original reality.",
  },
];

export default function HomePage() {
  // The page opens on a small pill rather than a heading, so the symmetric
  // section padding that suits a text-led page left a dead band under the
  // header. The top is tightened independently of the bottom.
  return (
    <div className="mx-auto flex max-w-6xl flex-col px-4 pb-14 pt-8 sm:pb-20 sm:pt-10">
      <section className="flex flex-col items-center">
        <span className="mb-4 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs text-muted-foreground">
          <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
          Counterfactual possibility explorer
        </span>

        <h1 className="text-balance text-center text-4xl font-bold tracking-tight sm:text-6xl">
          You are here.
        </h1>
        <p className="mt-4 max-w-xl text-balance text-center text-lg text-muted-foreground">
          Describe a real situation. WHAT IF extracts what is actually known, generates
          alternative trajectories, and lets you walk the possibility graph that survives.
        </p>

        <div className="mt-10 flex w-full justify-center">
          <ScenarioPrompt />
        </div>
      </section>

      <section className="mt-20 grid gap-4 sm:grid-cols-3">
        {PILLARS.map((pillar) => (
          <div key={pillar.title} className="rounded-xl border bg-card p-5">
            <h2 className="text-sm font-semibold">{pillar.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{pillar.body}</p>
          </div>
        ))}
      </section>

      <section className="mt-12 rounded-xl border bg-card p-5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          How to read the output
        </h2>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
          {(["grounded", "inferred", "assumed", "speculative", "unknown"] as const).map((band) => (
            <span key={band} className="inline-flex items-center gap-2 text-xs text-muted-foreground">
              <EvidenceChip type={band} />
            </span>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Anything downstream of a fork is speculative by construction. Plausibility is stated as
          high / medium / low — never as a fake probability percentage.
        </p>
      </section>
    </div>
  );
}
