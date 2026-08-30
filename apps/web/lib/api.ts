import type { ZodType } from "zod";

import {
  compareResponseSchema,
  expandResponseSchema,
  generateSummarySchema,
  healthResponseSchema,
  nodeDetailSchema,
  possibilityGraphSchema,
  realityResponseSchema,
  scenarioCreatedSchema,
} from "@/lib/schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type {
  Assumption,
  BranchSummary,
  CompareDimension,
  CompareResponse,
  CompareStateRow,
  ConstraintItem,
  DecisionHint,
  Effect,
  EventItem,
  EvidenceType,
  ExpandResponse,
  FactItem,
  GenerateSummary,
  GraphEdge,
  GraphNode,
  HealthResponse,
  NodeDetail,
  Plausibility,
  PossibilityGraph,
  RealityState,
  ScenarioCreated,
} from "@/lib/schemas";

export const DOMAINS = [
  { value: null, label: "Auto-detect", emoji: "✨" },
  { value: "career", label: "Career / Job", emoji: "💼" },
  { value: "relationship", label: "Relationship", emoji: "❤️" },
  { value: "business", label: "Business", emoji: "🚀" },
  { value: "software", label: "Project / Git", emoji: "💻" },
  { value: "purchase", label: "Purchase", emoji: "🛒" },
  { value: "finance", label: "Money", emoji: "💰" },
  { value: "habit", label: "Habit / Principle", emoji: "🌱" },
  { value: "reflection", label: "Dream / Reflect", emoji: "🌙" },
] as const;

async function request<T>(
  path: string,
  schema: ZodType<T>,
  init?: RequestInit & { timeoutMs?: number }
): Promise<T> {
  const { timeoutMs = 10_000, ...rest } = init ?? {};
  const response = await fetch(`${API_URL}/api/v1${path}`, {
    ...rest,
    signal: AbortSignal.timeout(timeoutMs),
    headers: { "Content-Type": "application/json", Accept: "application/json", ...(rest.headers ?? {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {}
    throw new Error(detail);
  }

  // Validate at the boundary: a backend shape change should fail here, naming
  // the field, rather than surfacing as `undefined` three components later.
  const parsed = schema.safeParse(await response.json());
  if (!parsed.success) {
    const first = parsed.error.issues[0];
    throw new Error(
      `Unexpected response from ${path}: ${first.path.join(".") || "root"} ${first.message}`
    );
  }
  return parsed.data;
}

export function getHealth() {
  return request("/health", healthResponseSchema);
}

export function createScenario(input: string, domain?: string | null) {
  return request("/scenarios", scenarioCreatedSchema, {
    method: "POST",
    body: JSON.stringify({ input, domain: domain ?? undefined }),
    timeoutMs: 15_000,
  });
}

export function extractReality(id: string) {
  return request(`/scenarios/${id}/extract`, realityResponseSchema, {
    method: "POST",
    timeoutMs: 240_000,
  });
}

export function getReality(id: string) {
  return request(`/scenarios/${id}/reality`, realityResponseSchema, { timeoutMs: 15_000 });
}

export function generatePossibilities(id: string) {
  return request(`/scenarios/${id}/generate`, generateSummarySchema, {
    method: "POST",
    timeoutMs: 900_000,
  });
}

export function getGraph(id: string) {
  return request(`/scenarios/${id}/graph`, possibilityGraphSchema, { timeoutMs: 30_000 });
}

export function getNode(scenarioId: string, nodeId: string) {
  return request(`/scenarios/${scenarioId}/nodes/${nodeId}`, nodeDetailSchema, {
    timeoutMs: 15_000,
  });
}

export function expandNode(scenarioId: string, nodeId: string) {
  return request(`/scenarios/${scenarioId}/nodes/${nodeId}/expand`, expandResponseSchema, {
    method: "POST",
    timeoutMs: 900_000,
  });
}

export function compareNodes(scenarioId: string, nodeIds: [string, string]) {
  return request(`/scenarios/${scenarioId}/compare`, compareResponseSchema, {
    method: "POST",
    body: JSON.stringify({ node_ids: nodeIds }),
    timeoutMs: 15_000,
  });
}
