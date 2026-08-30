import { cn } from "@/lib/utils";

/**
 * Evidence band marker.
 *
 * PRD 47: never rely on colour alone. Each band carries an icon and a text
 * label as well, so the distinction survives greyscale and colour blindness.
 */
const EVIDENCE_BANDS: Record<string, { className: string; icon: string; label: string; title: string }> = {
  grounded: {
    className: "bg-success/15 text-success",
    icon: "●",
    label: "grounded",
    title: "Stated by you",
  },
  inferred: {
    className: "bg-primary/15 text-primary",
    icon: "◐",
    label: "inferred",
    title: "Reasonably follows from what you stated",
  },
  assumed: {
    className: "bg-yellow-500/15 text-yellow-600 dark:text-yellow-400",
    icon: "◔",
    label: "assumed",
    title: "Assumed so the scenario can be reasoned about",
  },
  speculative: {
    className: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
    icon: "○",
    label: "speculative",
    title: "A possible future, not a fact",
  },
  unknown: {
    className: "bg-muted text-muted-foreground",
    icon: "?",
    label: "unknown",
    title: "Referenced but not determinable",
  },
};

export function EvidenceChip({
  type,
  className,
  compact = false,
}: {
  type: string;
  className?: string;
  compact?: boolean;
}) {
  const band = EVIDENCE_BANDS[type] ?? EVIDENCE_BANDS.unknown;
  return (
    <span
      title={band.title}
      data-evidence={type}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        band.className,
        className
      )}
    >
      <span aria-hidden="true">{band.icon}</span>
      <span className={cn(compact && "sr-only")}>{band.label}</span>
    </span>
  );
}

export { EVIDENCE_BANDS };
