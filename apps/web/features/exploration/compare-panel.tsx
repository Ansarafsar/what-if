"use client";

import { useQuery } from "@tanstack/react-query";

import { useGraphStore } from "@/features/exploration/graph-store";
import { compareNodes, type GraphNode } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * PRD 50's relative dimension table (Career ↑↑ · Money ↑ · Freedom ↓).
 *
 * The backend computes this deterministically from effects already stored on
 * both nodes, so opening a comparison costs no tokens.
 */
export function ComparePanel({
  scenarioId,
  left,
  right,
}: {
  scenarioId: string;
  left: GraphNode;
  right: GraphNode;
}) {
  const clearCompare = useGraphStore((s) => s.clearCompare);

  const { data, isPending, error } = useQuery({
    queryKey: ["compare", scenarioId, left.id, right.id],
    queryFn: () => compareNodes(scenarioId, [left.id, right.id]),
    staleTime: Infinity,
  });

  return (
    <div className="rounded-xl border bg-card p-5" data-testid="compare-panel">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">
          <span className="text-primary">{left.title}</span>
          <span className="text-muted-foreground"> vs </span>
          <span className="text-primary">{right.title}</span>
        </h3>
        <button
          type="button"
          onClick={clearCompare}
          className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
        >
          Clear comparison
        </button>
      </div>

      {isPending && <p className="text-sm text-muted-foreground">Comparing…</p>}
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error instanceof Error ? error.message : "Comparison failed"}
        </p>
      )}

      {data && (
        <>
          <p className="mb-3 text-xs text-muted-foreground" data-testid="compare-note">
            {data.note}
          </p>

          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="pb-1 font-medium">Dimension</th>
                <th className="pb-1 font-medium">Difference</th>
                <th className="pb-1 text-right font-medium">Favours</th>
              </tr>
            </thead>
            <tbody>
              {data.dimensions.map((row) => (
                <tr key={row.dimension} className="border-t">
                  <td className="py-1.5 font-medium">{row.dimension}</td>
                  <td
                    className={cn(
                      "py-1.5 tabular-nums",
                      row.direction === "left" && "text-success",
                      row.direction === "right" && "text-destructive",
                      row.direction === "even" && "text-muted-foreground"
                    )}
                  >
                    <span aria-hidden="true">{row.marker}</span>{" "}
                    <span className="text-xs text-muted-foreground">
                      ({row.left.toFixed(2)} vs {row.right.toFixed(2)})
                    </span>
                  </td>
                  <td className="py-1.5 text-right text-xs text-muted-foreground">
                    {row.direction === "even"
                      ? "neither"
                      : row.direction === "left"
                        ? left.title
                        : right.title}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {data.state.length > 0 && (
            <>
              <h4 className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                World state
              </h4>
              <table className="w-full text-sm" data-testid="compare-state">
                <tbody>
                  {data.state.map((row) => (
                    <tr key={row.key} className="border-t">
                      <td className="py-1 pr-2 font-medium">{row.key}</td>
                      <td className={cn("py-1 pr-2", row.same && "text-muted-foreground")}>
                        {row.left === undefined ? "—" : String(row.left)}
                      </td>
                      <td className={cn("py-1", row.same && "text-muted-foreground")}>
                        {row.right === undefined ? "—" : String(row.right)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </div>
  );
}
