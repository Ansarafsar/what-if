"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Compass, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { createScenario, DOMAINS } from "@/lib/api";
import { cn } from "@/lib/utils";

const FLAGSHIP =
  "I got a job offer in Bengaluru. I currently live with my parents, I'm comfortable with my current job, I have a relationship here, and I've always wanted to build a startup. The new job pays 40% more.";

export function ScenarioPrompt() {
  const router = useRouter();
  const [value, setValue] = React.useState("");
  const [domain, setDomain] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const filled = value.trim().length >= 20;

  async function submit() {
    if (!filled || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createScenario(value.trim(), domain);
      router.push(`/scenario/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create scenario");
      setSubmitting(false);
    }
  }

  return (
    <div className="w-full max-w-2xl">
      <p className="mb-3 text-center text-sm font-medium">What do you want to fork?</p>
      <div className="mb-4 flex flex-wrap justify-center gap-1.5" data-testid="domain-picker">
        {DOMAINS.map((option) => (
          <button
            key={option.label}
            type="button"
            onClick={() => setDomain(option.value)}
            className={cn(
              "rounded-full border px-3 py-1.5 text-xs transition-colors",
              domain === option.value
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            )}
            aria-pressed={domain === option.value}
          >
            <span aria-hidden className="mr-1">{option.emoji}</span>
            {option.label}
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="p-4">
          <label htmlFor="scenario-input" className="sr-only">
            Describe your situation
          </label>
          <textarea
            id="scenario-input"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Describe the situation you want to explore…"
            rows={5}
            maxLength={4000}
            disabled={submitting}
            className="w-full resize-none rounded-md border border-input bg-transparent p-3 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <div className="mt-1 flex items-center justify-between px-1 text-xs text-muted-foreground">
            <button
              type="button"
              onClick={() => setValue(FLAGSHIP)}
              className="underline-offset-2 hover:underline"
            >
              Use the example scenario
            </button>
            <span>{value.length}/4000</span>
          </div>
        </CardContent>
        <CardFooter className="flex-col items-stretch gap-2 border-t pt-4">
          <Button type="button" onClick={() => void submit()} disabled={!filled || submitting}>
            {submitting ? <Loader2 aria-hidden className="animate-spin" /> : <Compass aria-hidden />}
            Explore possibilities
          </Button>
          {error && (
            <p role="alert" className="text-center text-xs text-destructive">
              {error}
            </p>
          )}
          <p className="text-center text-xs text-muted-foreground">
            WHAT IF separates facts from assumptions — it never predicts your future.
          </p>
        </CardFooter>
      </Card>
    </div>
  );
}
