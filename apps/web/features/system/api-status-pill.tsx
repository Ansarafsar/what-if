"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { getHealth, type HealthResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

type Status = "checking" | "online" | "offline";

export function ApiStatusPill({ className }: { className?: string }) {
  const [status, setStatus] = React.useState<Status>("checking");
  const [version, setVersion] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((health: HealthResponse) => {
        if (cancelled) return;
        setVersion(health.version);
        setStatus("online");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("offline");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const label =
    status === "online"
      ? `API online${version ? ` · v${version}` : ""}`
      : status === "offline"
        ? "API offline"
        : "Checking API…";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground",
        className
      )}
      data-testid="api-status"
      data-status={status}
    >
      {status === "checking" ? (
        <Loader2 aria-hidden className="h-3 w-3 animate-spin" />
      ) : (
        <span
          aria-hidden
          className={cn(
            "inline-block h-2 w-2 rounded-full",
            status === "online" ? "bg-success" : "bg-destructive"
          )}
        />
      )}
      {label}
    </span>
  );
}
