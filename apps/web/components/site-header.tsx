import Link from "next/link";

import { ApiStatusPill } from "@/features/system/api-status-pill";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4">
        <Link href="/" className="flex items-center gap-2 rounded-md transition-opacity hover:opacity-80">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full bg-primary" />
          <span className="text-sm font-bold tracking-tight">WHAT IF</span>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            counterfactual explorer
          </span>
        </Link>
        {/* Live API state rather than a hardcoded phase label that goes stale
            the moment the phase moves on. */}
        <ApiStatusPill />
      </div>
    </header>
  );
}
