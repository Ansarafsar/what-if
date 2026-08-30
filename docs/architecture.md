# Architecture

WHAT IF is a domain-aware counterfactual reasoning platform. Instead of asking one
LLM to simulate an entire future, it decomposes a scenario into verified facts,
generates candidate counterfactuals through domain-specific reasoning, validates
them against constraints and evidence, and stores the survivors as an explorable
possibility graph.

## Core pipeline

```text
USER INPUT
   ↓
REALITY INGESTION
   ↓
FACT / EVIDENCE LAYER        ← GROUNDED · INFERRED · ASSUMED · SPECULATIVE · UNKNOWN
   ↓
DOMAIN ROUTER                ← career, relationship, software, finance, ...
   ↓
DOMAIN REASONING             ← each domain declares variables, dimensions, hard rules
   ↓
GENERATE → VERIFY → CRITIQUE → REVISE   (LangGraph, max 2 iterations)
   ↓
POSSIBILITY GRAPH            ← beam search, pruning, value-aware deduplication
   ↓
EXPLORE / COMPARE / FORK AGAIN   ← lazy expansion from each node's own world state
```

## Why state transition is the load-bearing piece

Expansion is not primarily an endpoint problem. A node can only be forked again if
it knows *which world it lives in* — otherwise "generate children of Accept the
offer" reasons from the original reality and produces branches that contradict the
choice already made.

So every outcome node persists, in `metadata`:

| key | purpose |
|---|---|
| `resulting_state` | the full `RealityState` after applying this branch's `state_delta` |
| `depth` | integer, mirrored into an indexed column for tree queries |
| `path_labels` | ordered ancestor labels, fed to the prompt so children stay coherent |

`resulting_state` carries `state_variables` — the structured world snapshot each
delta is applied to — and appends every applied delta to `facts` as `SPECULATIVE`
evidence. Nothing downstream of a fork is grounded, and the marker keeps that
visible rather than letting a projection quietly acquire the authority of a fact.

## The revise loop

`critique` produces verdicts and `verify_constraints` produces violations. Both
route into a conditional edge:

- **revise** while any branch failed and the iteration budget is unspent
- **accept** otherwise, or once `ENGINE_MAX_REVISE_ITERATIONS` (default 2) is hit

The revise node regenerates **only failing branches**; passing branches carry
their consequences and reviews forward untouched, so a repair costs one LLM call
per broken branch. On force-accept, branches the critic merely disliked are
admitted, but branches breaching a hard constraint are rejected — a constraint is
not a preference.

This replaced an earlier `continue` that dropped any violating branch on the
floor, which had the side effect of making `ScoredBranch.constraint_violations`
permanently empty and the scoring penalty that read it dead code.

## The critical rule

> An LLM possibility is not a reality.

The LLM proposes structured hypotheses. The application validates, structures,
scores, stores and visualizes them. Nothing generated is ever presented as factual
prediction; plausibility is expressed as `HIGH / MEDIUM / LOW / SPECULATIVE`, never
as a fake probability percentage.

## Backend layers

| Layer | Location | Responsibility |
|---|---|---|
| API | `app/api` | HTTP concerns only: routers, deps, schemas |
| Orchestration | `app/graphs` | LangGraph state machines: generation, expansion |
| Application | `app/services` | Use cases and persistence: pipeline, scenario_service |
| Domain | `app/models`, `app/schemas` | RealityState, CandidateAction, StateDelta |
| Engine | `app/engines` | Deterministic algorithms: constraints, transitions, ranking, comparison |
| Infrastructure | `app/core`, providers | Database, Redis (deferred), LLM providers |

`app/graphs/nodes.py` holds the node functions; both the generation and expansion
graphs are assembled from the same set, so an expanded subtree is produced by
exactly the same reasoning as the first paint. Each node wraps an existing
`PossibilityPipeline` method, which keeps every LLM call flowing through
`_run_stage` — the single place prompt version, latency, tokens and retries are
recorded to `llm_executions`.

## What is deterministic

Anything ordinary code can do is not given to the model:

| Concern | Where | Notes |
|---|---|---|
| Constraint checking | `engines/constraint_engine.py` | Numeric key/operator/value only; the LLM cannot override it. Evaluates the scenario's constraints **and** the domain's standing invariants |
| State projection | `engines/state_transition.py` | Pre-fork keys are preserved; base state is never mutated |
| Scoring and dedup | `engines/scoring.py` | Value-aware similarity, beam pruning; same inputs → same graph |
| Branch comparison | `engines/comparison.py` | Effects and world-state diff; no LLM call, no tokens |
| Layout | `apps/web/lib/graph-layout.ts` | dagre, arbitrary depth |

## Current status

Implemented end to end: reality extraction, LangGraph generation with a bounded
revise loop, multi-fork persistence, lazy expansion from per-node world state,
deterministic comparison, the React Flow exploration UI, and a 21-fixture eval
harness. See the roadmap table in the root README.

Deliberately deferred:

- **Redis** — expansion is persisted in Postgres and idempotent, so no caching or
  shared-state consumer exists yet. The service slot stays reserved in
  `docker-compose.yml` as a comment.
- **A root npm workspace** — `packages/shared` stays empty until a second consumer
  of the schemas appears; today a package there could not resolve `zod`.

## Non-negotiable engineering principles

1. LLM calls live behind a provider interface; the engine never imports a vendor SDK.
2. Work ordinary code can do deterministically must not be given to the LLM.
3. Every claim carries evidence classification; missing info becomes `UNKNOWN`,
   never invented.
4. Graph generation is lazy; beam search bounds generation. Expansion is
   idempotent and depth-guarded, so exploring costs tokens only the first time.
5. Each phase leaves the repository runnable.
6. Demo data announces itself. Mock responses are flagged in the payload and
   warned about at startup; an unknown provider is refused rather than silently
   answering every scenario with the same canned fixture.
7. Reasoning quality is measured in `evals/` against a live model. A test running
   on `MockProvider` can only ever re-read the fixture it was seeded with.
8. Config that is declared must be consumed. Domain `dimensions`, `constraints`
   and `prompt_addendum` were each defined per domain and never reached the
   model or the engine - dead config that looks like a working feature.
   `tests/test_prompts_llm.py` now asserts every variable a stage passes is
   interpolated by its template, in both directions.
9. A failure must leave a trace. Every error path logs and persists its
   `llm_executions` row *before* raising - `get_db` rolls the session back when
   a request raises, so a row that is only flushed is silently discarded.
