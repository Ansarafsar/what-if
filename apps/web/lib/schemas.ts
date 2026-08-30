/**
 * Runtime-validated contracts for every API response the web app consumes.
 *
 * `api.ts` used to cast responses with `as T`, so a backend shape change failed
 * silently at render time with an undefined field. Parsing here turns that into
 * one loud error at the fetch boundary, naming the field that moved.
 */
import { z } from "zod";

export const evidenceTypeSchema = z.enum([
  "grounded",
  "inferred",
  "assumed",
  "speculative",
  "unknown",
]);

export const plausibilitySchema = z.enum(["high", "medium", "low", "speculative"]);

export const effectSchema = z.object({
  dimension: z.string(),
  direction: z.enum(["up", "down", "flat", "uncertain"]),
  magnitude: z.enum(["low", "medium", "high"]),
  order: z.number(),
  explanation: z.string(),
});

export const assumptionSchema = z.object({
  claim: z.string(),
  depends_on: z.array(z.string()).default([]),
});

export const factSchema = z.object({
  claim: z.string(),
  evidence_type: evidenceTypeSchema,
  source: z.string().default("user_input"),
  confidence: z.number().default(1),
});

export const eventItemSchema = z.object({
  description: z.string(),
  timestamp: z.string().nullable().default(null),
  evidence_type: evidenceTypeSchema,
});

export const decisionHintSchema = z.object({
  question: z.string(),
  options_hint: z.array(z.string()).default([]),
  importance: z.number().default(0.5),
});

export const constraintItemSchema = z.object({
  description: z.string(),
  kind: z.string(),
  key: z.string().nullable().default(null),
  operator: z.string().nullable().default(null),
  value: z.number().nullable().default(null),
});

export const realityStateSchema = z.object({
  // Pydantic serialises `UUID | None` as an explicit null, not an omitted key,
  // so this must be nullable and not merely optional.
  scenario_id: z.string().nullable().optional(),
  title: z.string(),
  summary: z.string(),
  domain: z.string(),
  actors: z.array(z.string()).default([]),
  entities: z.array(z.string()).default([]),
  events: z.array(eventItemSchema).default([]),
  decision_hints: z.array(decisionHintSchema).default([]),
  constraints: z.array(constraintItemSchema).default([]),
  goals: z.array(z.string()).default([]),
  relationships: z.array(z.string()).default([]),
  resources: z.array(z.string()).default([]),
  beliefs: z.array(z.string()).default([]),
  uncertainties: z.array(z.string()).default([]),
  missing_information: z.array(z.string()).default([]),
  facts: z.array(factSchema).default([]),
  state_variables: z.record(z.string(), z.unknown()).default({}),
});

export const nodeMetadataSchema = z
  .object({
    question: z.string().optional(),
    fork_id: z.string().optional(),
    importance: z.number().optional(),
    strategy: z.string().optional(),
    rationale: z.string().optional(),
    reversible: z.boolean().optional(),
    state_delta: z.record(z.string(), z.unknown()).optional(),
    effects: z.array(effectSchema).optional(),
    score_breakdown: z.record(z.string(), z.number()).optional(),
    depth: z.number().optional(),
    path_labels: z.array(z.string()).optional(),
    expanded: z.boolean().optional(),
    resulting_state: realityStateSchema.nullable().optional(),
    evidence: z
      .object({
        grounded_reasons: z.array(z.string()).optional(),
        assumptions: z.array(assumptionSchema).optional(),
        risks: z.array(z.string()).optional(),
        critic: z.object({ verdict: z.string(), issues: z.array(z.string()) }).optional(),
        constraint_violations: z.array(z.string()).optional(),
      })
      .optional(),
  })
  // Metadata is an open JSONB bag; unknown keys are data, not errors.
  .passthrough();

export const graphNodeSchema = z.object({
  id: z.string(),
  parent_id: z.string().nullable(),
  node_type: z.enum(["reality", "decision", "state"]),
  title: z.string(),
  description: z.string(),
  plausibility: plausibilitySchema.nullable(),
  score: z.number().nullable(),
  metadata: nodeMetadataSchema.default({}),
});

export const graphEdgeSchema = z.object({
  id: z.string(),
  source_id: z.string(),
  target_id: z.string(),
  transition: z.string(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export const possibilityGraphSchema = z.object({
  scenario_id: z.string(),
  nodes: z.array(graphNodeSchema),
  edges: z.array(graphEdgeSchema),
});

export const branchSummarySchema = z.object({
  label: z.string(),
  strategy: z.string(),
  plausibility: plausibilitySchema,
  score: z.number(),
  reversible: z.boolean(),
});

export const generateSummarySchema = z.object({
  scenario_id: z.string(),
  node_count: z.number(),
  edge_count: z.number(),
  branch_count: z.number(),
  branches: z.array(branchSummarySchema),
  mock: z.boolean().default(false),
});

export const realityResponseSchema = z.object({
  scenario_id: z.string(),
  state: realityStateSchema,
  mock: z.boolean().default(false),
});

export const scenarioCreatedSchema = z.object({
  id: z.string(),
  status: z.string(),
});

export const healthResponseSchema = z.object({
  status: z.string(),
  service: z.string(),
  version: z.string(),
  environment: z.string(),
});

export const expandResponseSchema = z.object({
  scenario_id: z.string(),
  node_id: z.string(),
  created: z.boolean(),
  nodes: z.array(graphNodeSchema),
  edges: z.array(graphEdgeSchema),
  mock: z.boolean().default(false),
});

export const compareDimensionSchema = z.object({
  dimension: z.string(),
  left: z.number(),
  right: z.number(),
  delta: z.number(),
  direction: z.enum(["left", "right", "even"]),
  marker: z.string(),
  shared: z.boolean(),
});

export const compareStateRowSchema = z.object({
  key: z.string(),
  left: z.unknown(),
  right: z.unknown(),
  same: z.boolean(),
  only_in: z.enum(["left", "right"]).nullable(),
});

export const compareSideSchema = z.object({
  id: z.string(),
  title: z.string(),
  plausibility: plausibilitySchema.nullable(),
  score: z.number().nullable(),
  path_labels: z.array(z.string()).default([]),
});

export const compareResponseSchema = z.object({
  left: compareSideSchema,
  right: compareSideSchema,
  dimensions: z.array(compareDimensionSchema),
  state: z.array(compareStateRowSchema),
  relative: z.boolean(),
  note: z.string(),
});

export const nodeDetailSchema = z.object({
  id: z.string(),
  scenario_id: z.string(),
  parent_id: z.string().nullable(),
  node_type: z.string(),
  title: z.string(),
  description: z.string(),
  plausibility: plausibilitySchema.nullable(),
  score: z.number().nullable(),
  depth: z.number(),
  expanded_at: z.string().nullable(),
  child_ids: z.array(z.string()),
  metadata: nodeMetadataSchema.default({}),
});

export type EvidenceType = z.infer<typeof evidenceTypeSchema>;
export type Plausibility = z.infer<typeof plausibilitySchema>;
export type Effect = z.infer<typeof effectSchema>;
export type Assumption = z.infer<typeof assumptionSchema>;
export type FactItem = z.infer<typeof factSchema>;
export type EventItem = z.infer<typeof eventItemSchema>;
export type DecisionHint = z.infer<typeof decisionHintSchema>;
export type ConstraintItem = z.infer<typeof constraintItemSchema>;
export type RealityState = z.infer<typeof realityStateSchema>;
export type GraphNode = z.infer<typeof graphNodeSchema>;
export type GraphEdge = z.infer<typeof graphEdgeSchema>;
export type PossibilityGraph = z.infer<typeof possibilityGraphSchema>;
export type BranchSummary = z.infer<typeof branchSummarySchema>;
export type GenerateSummary = z.infer<typeof generateSummarySchema>;
export type RealityResponse = z.infer<typeof realityResponseSchema>;
export type ScenarioCreated = z.infer<typeof scenarioCreatedSchema>;
export type HealthResponse = z.infer<typeof healthResponseSchema>;
export type ExpandResponse = z.infer<typeof expandResponseSchema>;
export type CompareDimension = z.infer<typeof compareDimensionSchema>;
export type CompareStateRow = z.infer<typeof compareStateRowSchema>;
export type CompareResponse = z.infer<typeof compareResponseSchema>;
export type NodeDetail = z.infer<typeof nodeDetailSchema>;
