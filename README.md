<div align="center">

# WHAT IF

**A counterfactual possibility explorer.**

Give it a real situation. It extracts what is actually known, generates alternative
trajectories, validates them against constraints and evidence, and lets you explore
the surviving possibility graph.

[![CI](https://github.com/Ansarafsar/what-if/actions/workflows/ci.yml/badge.svg)](https://github.com/Ansarafsar/what-if/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-8b5cf6)](https://ansarafsar.github.io/what-if/)
![Python](https://img.shields.io/badge/python-3.12+-3776ab?logo=python&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Pydantic%20v2-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-orchestration-1c3c3c)
![Tests](https://img.shields.io/badge/tests-230%20api%20%C2%B7%2039%20web-brightgreen)

[Live docs & architecture](https://ansarafsar.github.io/what-if/) ·
[Quick start](#quick-start) ·
[Architecture](#architecture) ·
[Failover](#reliability--failover)

</div>

---

> *"What if I could fork reality and explore the lives hidden behind the decisions
> I didn't make?"*

WHAT IF is **not** a chatbot, fortune teller, or decision maker. The LLM proposes
structured hypotheses; the application validates, scores, and visualizes them.
Every claim is classified as `GROUNDED`, `INFERRED`, `ASSUMED`, or `SPECULATIVE`.

<table>
<tr>
<td width="33%" valign="top">

### 🧭 Facts, not vibes
Every claim carries an evidence class. Missing information becomes `UNKNOWN` —
never invented.

</td>
<td width="33%" valign="top">

### ⚙️ LLM proposes, code disposes
Constraint checking, scoring, dedup and comparison are deterministic engines.
Same input → same graph.

</td>
<td width="33%" valign="top">

### 🌱 Forkable, not final
Every outcome stores the world it produced, so you fork again *from inside it* —
not from the original reality.

</td>
</tr>
</table>

## Quick start

Docker is the only prerequisite. Nothing else needs to be installed, and **no API
key is required to boot** — without one the stack serves canned demo data and
labels every response as such.

```bash
git clone https://github.com/Ansarafsar/what-if.git
cd what-if
cp .env.example .env        # Windows PowerShell: copy .env.example .env
docker compose up --build   # first build takes a few minutes
```

Open **http://localhost:3000**.

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API | http://localhost:8000/api/v1/health |
| Swagger docs | http://localhost:8000/docs |
| PostgreSQL (pgvector image) | localhost:5432 |

### Turning on real reasoning

The demo fixture is one hardcoded scenario — to explore *your* situation you need
a live provider. OpenRouter is the recommended default: it has free models, so a
key costs nothing to try. Edit `.env`:

```bash
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...                    # https://openrouter.ai/keys
LLM_MODEL=deepseek/deepseek-chat-v3-0324:free
```

Then `docker compose up --build` again. [OpenAI and Anthropic](#llm-providers)
are supported identically if you already have a key for either.

### About the database

You do not create, migrate, or seed anything by hand:

- Postgres runs as the `whatif-db` service from the `pgvector/pgvector:pg16`
  image — no local Postgres install needed.
- The `vector` extension is enabled on first boot by
  [`infra/postgres/init/01_extensions.sql`](infra/postgres/init/01_extensions.sql).
- The schema lives in the repo as **Alembic migrations**
  ([`apps/api/alembic/versions/`](apps/api/alembic/versions/)), and
  [`entrypoint.sh`](apps/api/entrypoint.sh) runs `alembic upgrade head` every
  time the API container starts. There is no `schema.sql` to import — the
  migrations *are* the schema, so they can never drift from one.
- Data persists in the `pgdata` Docker volume across restarts. To start from an
  empty database: `docker compose down -v`.

<details>
<summary><b>Development without Docker</b></summary>

Backend — [uv](https://docs.astral.sh/uv/) manages the virtualenv, the Python
version and the locked dependencies:

```bash
cd apps/api
uv sync --extra dev     # creates .venv, installs from uv.lock
uv run pytest           # 230 tests, no database or API key needed
```

`uv.lock` is committed, so `uv sync` reproduces the exact dependency set that CI
runs. Run any command inside the environment with `uv run <cmd>` — activating the
venv is optional.

The test suite runs against the mock provider and an in-memory database, but the
**dev server needs a real Postgres**. Easiest is to borrow the one from Compose
and run only the API on the host:

```bash
docker compose up whatif-db -d          # Postgres on localhost:5432
cd apps/api
uv run alembic upgrade head             # apply the schema
uv run uvicorn app.main:app --reload
```

`DATABASE_URL` in `.env.example` already points at `localhost:5432` with the
default credentials, so this works unchanged.

Frontend:

```bash
cd apps/web
npm install
npm run dev        # dev server on :3000, expects the API on :8000
npm test           # vitest - 39 tests
npm run build      # production build + typecheck
```

</details>

<details>
<summary><b>Repository layout</b></summary>

```text
what-if/
├── apps/
│   ├── web/            Next.js 16 · TypeScript · Tailwind v4 · shadcn-style UI
│   └── api/            FastAPI · Pydantic v2 · SQLAlchemy 2 · Alembic
├── packages/shared/    reserved; API schemas currently live in apps/web/lib/schemas.ts
├── infra/
│   ├── docker/         Dockerfile.api · Dockerfile.web
│   └── postgres/init/  bootstrap extensions (pgvector)
├── evals/              21 scenario fixtures + scoring harness
├── docs/               architecture notes
├── site/               static docs site (HTML/CSS/JS) deployed to GitHub Pages
└── scripts/
```

</details>

## How it works

```mermaid
flowchart TD
    A[Raw situation text] --> B[Reality extraction]
    B --> C{Evidence layer<br/>grounded · inferred · assumed · speculative · unknown}
    C --> D[Domain router]
    D --> E[LangGraph generation]
    E --> F[(Possibility graph<br/>Postgres)]
    F --> G[Explore · Compare · Fork again]
    G -->|lazy expansion from<br/>node's own world state| E
```

The product primitive is a graph you can walk: **fork reality, walk the branches,
fork again.** Every outcome node stores the world state it produced, so expanding
it reasons from *that* world — the children of "Accept the offer" are generated in
a world where the offer was accepted, not in the original reality.

## Architecture

### Orchestration: LangGraph with a bounded revise loop

```mermaid
flowchart LR
    A[detect_forks] --> B[generate_candidates]
    B --> C[generate_consequences]
    C --> D[verify_constraints]
    D --> E[critique]
    E --> F{partition}
    F -->|failures remain<br/>budget unspent| G[revise]
    G --> C
    F -->|accept| H[rank]
    H --> I[build_graph]
```

The revise edge is the part a linear pipeline could not express: critic verdicts
and constraint violations feed back into a targeted regeneration of **only the
failing branches** — passing branches keep their consequences and reviews, so a
repair pass costs one LLM call per broken branch, not a full resample.
Constraint violations route to revision and are only rejected once the iteration
budget is spent; a hard constraint is never negotiable.

Forks detected but not expanded are persisted as unexpanded decision nodes, so
the alternatives the engine already found are one click away rather than thrown
away.

### Architecture invariants

| Invariant | What it means |
|---|---|
| **LLM proposes, code disposes** | Every stage returns schema-validated JSON (Pydantic), with bounded retries; malformed output never reaches the DB |
| **Evidence classes** | `grounded / inferred / assumed / speculative / unknown` on facts; branches carry assumptions with dependency keys |
| **Deterministic engines** | Constraint checking, value-aware dedup, weighted scoring, beam-width pruning, acyclic-graph validation. Same inputs → same graph |
| **Domain modules** | 9 domains, each declaring causal variables, dimensions, canonical forks, seed strategies, hard rules and determinism level |
| **Observability** | Every stage call recorded to `llm_executions` (model, prompt version, latency, tokens, retries, success) |

Scoring weights: `relevance .25 · plausibility .25 · impact .20 · novelty .15 ·
reversibility .05 − redundancy .10 − critic penalties`.

Domain modules cover career, relationship, business, software, purchase, finance,
habit, reflection and general — with hard rules like *relationship: never claim
another person's mental state* and determinism levels (`llm_led | hybrid | calc_led`).

### API

```text
POST /api/v1/scenarios                             create scenario from raw text
POST /api/v1/scenarios/{id}/extract                NL → validated RealityState
GET  /api/v1/scenarios/{id}/reality                latest extracted state
POST /api/v1/scenarios/{id}/generate               run the generation graph
POST /api/v1/scenarios/{id}/generate/stream        same, as SSE stage events
GET  /api/v1/scenarios/{id}/graph                  PossibilityGraph
GET  /api/v1/scenarios/{id}/nodes/{node_id}        node detail + children
POST /api/v1/scenarios/{id}/nodes/{node_id}/expand generate this node's children
POST /api/v1/scenarios/{id}/compare                deterministic 2-branch diff
```

### Expansion and comparison

`expand` is idempotent — a node that already has children returns them without an
LLM call — and is depth-guarded by `ENGINE_MAX_DEPTH` (default 4). `compare` runs
no LLM at all: it diffs two branches' effects and world states deterministically
and returns per-dimension direction and magnitude, explicitly labelled *relative,
not objective*.

## Reliability & failover

### Transient upstream failures

`429 / 502 / 503 / 504` and network errors back off exponentially
(2s, 4s, 8s… capped at 30s) with 25% jitter, so the per-branch consequence calls
do not retry in lockstep and rate-limit themselves again. A server-sent
`Retry-After` overrides our schedule up to a 120s ceiling — past that the request
fails rather than parking the caller.

> [!IMPORTANT]
> **OpenRouter fronts other providers**, so an upstream failure can arrive as
> **HTTP 200 with the real status nested in the body** (`{"error": {"code": 429}}`).
> Retry logic that only reads `response.status_code` misses these entirely and
> fails on the first attempt. That case is detected and retried through the same
> ladder rather than being misread as a malformed payload.

| Failure mode | Response |
|---|---|
| HTTP `429/502/503/504` | Exponential backoff + 25% jitter, capped 30s |
| HTTP 200 with nested error code | Same ladder — body is inspected, not just the status line |
| `Retry-After` header | Honoured, up to a 120s ceiling; beyond that, fail fast |
| Network error / timeout | Retried on the same ladder |
| Malformed JSON | Repaired by feeding the validation error back to the model — **no sleep**, a schema error is the model's fault, not the server's |
| Unknown provider configured | Refused with `503` rather than silently serving fixtures |
| Any error path | Persists its `llm_executions` row *before* raising, so a failure always leaves a trace |

Attempts are `LLM_MAX_RETRIES + 1` (default 3) and every retry is counted in
`llm_executions`.

### Mock mode is loud

`LLM_PROVIDER=mock` is what a fresh clone boots with, so the stack runs before
you have signed up for anything — but it answers *every* scenario from the same
canned Bengaluru fixture, whatever you type. The API logs a startup warning and
every affected response carries `"mock": true`, which the UI renders as a banner,
so a deploy that forgets to set a live `LLM_PROVIDER` cannot quietly serve demo
data at HTTP 200. Set `openrouter` before judging the reasoning.

## LLM providers

Set `LLM_PROVIDER` to one of four values. **`openrouter` is the recommended
choice** — it reaches models from every vendor through one key and offers `:free`
models, so it costs nothing to evaluate. `mock` is the built-in fallback used
when no provider is configured, so the app always boots.

| Provider | Endpoint | Model id (`LLM_MODEL`) | Key |
|---|---|---|---|
| `openrouter` **(recommended)** | `https://openrouter.ai/api/v1/chat/completions` | `deepseek/deepseek-chat-v3-0324:free` | `OPENROUTER_API_KEY` |
| `openai` | `https://api.openai.com/v1/chat/completions` | `gpt-4o` | `OPENAI_API_KEY` |
| `anthropic` | `https://api.anthropic.com/v1/messages` | `claude-opus-5` | `ANTHROPIC_API_KEY` |
| `mock` | — (in-process fixture) | — | none |

Only the selected provider's key is read; the others can stay blank.

```bash
# --- OpenRouter (recommended) ------------------------------------------------
# Key: https://openrouter.ai/keys - free tier available, no card required.
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
LLM_MODEL=deepseek/deepseek-chat-v3-0324:free   # list current free models:
                                                # python scripts/list_openrouter_models.py

# --- OpenAI -------------------------------------------------------------------
# Key: https://platform.openai.com/api-keys - paid, requires billing set up.
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o
# OPENAI_ORGANIZATION / OPENAI_PROJECT - optional scoping headers, sent only if set.

# --- Anthropic ----------------------------------------------------------------
# Key: https://console.anthropic.com/settings/keys - paid, requires credits.
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
LLM_MODEL=claude-opus-5
# ANTHROPIC_MAX_TOKENS=8192 - the Messages API requires max_tokens; a reply
# truncated by too low a value fails schema validation rather than half-parsing.
```

A key that is missing or names an unknown provider is refused with `503` at
request time — the app never silently falls back to fixtures to hide a
misconfiguration.

All three live providers share one HTTP adapter
(`apps/api/app/llm/http_provider.py`), so the retry ladder, `Retry-After`
handling, jitter, in-body error detection and schema repair below apply
identically to each — only the wire format differs per provider. Adding a
provider is a subclass plus a registry entry, not a new copy of the failover
logic.

Per-provider handling worth knowing: OpenAI is asked for
`response_format: json_object` and has `temperature` omitted for reasoning
models (o-series, `gpt-5`) that reject it; Anthropic sends the system prompt
top-level, requires `max_tokens` (`ANTHROPIC_MAX_TOKENS`, default 8192), pins
`anthropic-version`, and concatenates text blocks so a `thinking` block never
masks the answer.

Prompt templates are versioned files in `apps/api/app/llm/prompts/`
(`reality_extraction.v1`, `fork_detection.v1`, `candidate_generation.v1`,
`candidate_revision.v1`, `consequence_generation.v1`, `critic_review.v1`) and
every execution logs the template version used.

## Evaluation

`evals/` holds 21 fixtures (at least one per domain) and a harness scoring
extraction completeness, grounding, hallucination resistance, schema validity,
branch coverage, branch diversity, constraint violations, domain routing, and
stability under rewording.

```bash
# measures the engine - needs a live provider and spends tokens
LLM_PROVIDER=openrouter uv run --project apps/api python evals/harness/run.py

# smoke-tests the harness itself, no key needed
uv run --project apps/api python evals/harness/run.py --provider mock
```

This is the only place reasoning quality is measured — tests running against
`MockProvider` can prove the plumbing works but only ever re-read their own
fixture. See [`evals/README.md`](evals/README.md).

## Exploration UI (`apps/web`)

- **dagre layout** at arbitrary depth (the old layout hardcoded three columns and
  clamped everything past depth 2 into the same one).
- **Fork again from here** on every unexpanded outcome node; expansion merges into
  the graph in place, with independent per-node loading state.
- **Detail side sheet** for *every* node type — outcome, fork, and reality —
  surfacing the score breakdown, the before → after state delta, constraint
  violations, assumptions, critic verdict, and the path taken to reach the branch.
- **Compare mode**: shift-click a second branch for the relative dimension table.
- **Honest progress**: the generation indicator is driven by SSE stage events from
  LangGraph, including revise iterations — not a timer cycling canned copy.
- **Runtime-validated API boundary**: every response is parsed against a Zod
  schema in `apps/web/lib/schemas.ts`, so a backend shape change fails loudly at
  the fetch, naming the field, instead of surfacing as `undefined` mid-render.

State is split by ownership: TanStack Query for server state, Zustand for
graph/selection/expansion — which is what lets the UI represent "viewing the graph
**and** expanding node 7", a state the old linear phase union could not express.

## Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Repository + infrastructure | ✅ |
| 1 | Reality engine + possibility pipeline | ✅ |
| 2 | LangGraph orchestration + bounded revise loop | ✅ |
| 3 | Lazy expansion API, node detail, deterministic compare | ✅ |
| 4 | Exploration UI: dagre graph, expand-on-click, compare, SSE progress | ✅ |
| 5 | Eval fixtures + scoring harness | ✅ |
| 6+ | More domains, richer causal modelling, larger fixture corpus | planned |

<details>
<summary><b>Deferred by design</b></summary>

- **Redis** — no consumer exists yet. Expansion is persisted in Postgres and
  idempotent, so nothing currently needs a cache. Reserved slot in compose/env.
- **`packages/shared`** — schemas live in `apps/web/lib/schemas.ts` until a second
  consumer exists; this repo is not an npm workspace, so a package there cannot
  resolve `zod`.

</details>

See [`docs/architecture.md`](docs/architecture.md) for the engineering thesis and
invariants, or the [documentation site](https://ansarafsar.github.io/what-if/) for
the illustrated version.

## Security notes

- `.env` is never committed; API keys stay server-side only.
- All LLM calls happen in the backend behind a provider interface.
- User scenarios are never logged in full by default.
