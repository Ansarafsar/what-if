# evals

Scenario fixtures and the evaluation harness for the WHAT IF engine.

This is the only place reasoning quality is actually measured. The tests under
`apps/api/tests` run against `MockProvider`, so they can prove the plumbing works
but never that the model reasoned well — an assertion there just re-reads the
fixture it was seeded with.

## Layout

- `fixtures/*.json` — 21 scenarios, at least one per domain in the registry.
- `harness/run.py` — the runner and scorers.
- `results/` — timestamped JSON + Markdown reports (gitignored).

## Running

```bash
# measure the engine (costs tokens)
LLM_PROVIDER=openrouter OPENROUTER_API_KEY=... python evals/harness/run.py

# one fixture, or one domain
python evals/harness/run.py --fixture career_bengaluru_offer
python evals/harness/run.py --domain relationship

# halve the token cost by skipping the reworded rerun
python evals/harness/run.py --no-stability

# check the harness itself runs (scores are NOT meaningful)
python evals/harness/run.py --provider mock
```

`--provider mock` replays the canned Bengaluru career response for every input,
so every non-career fixture is answered with the wrong situation. That run exits
0 and its report says so; only an `openrouter` run returns a pass/fail verdict.

## Scored dimensions (PRD §66)

| dimension | question it answers |
|---|---|
| `extraction_completeness` | Did extraction fill the fields the engine depends on? |
| `grounding` | Are the facts the user stated present and marked GROUNDED? |
| `hallucination_resistance` | Does unprovided information ever get **asserted** as fact? |
| `schema_validity` | Are payloads semantically valid, not just Pydantic-valid? |
| `branch_coverage` | Did it find the fork shapes a human would expect? |
| `branch_diversity` | Are branches genuinely different? (reuses `scoring.similarity`) |
| `constraint_violations` | Did a branch breaching a hard constraint survive? |
| `domain_routing` | Was the scenario routed to the right domain module? |
| `stability` | Reworded input — does the possibility space hold its shape? |

A fixture passes at an overall score ≥ 0.70 with no hard errors.

`hallucination_resistance` is the load-bearing one. A forbidden token is only a
failure when it is asserted — as GROUNDED evidence, or inside a `high`
plausibility narrative. The same token appearing as an assumption, an open
question, or in `missing_information` is the engine behaving correctly and is
not penalised.

## Fixture format

```jsonc
{
  "id": "career_bengaluru_offer",
  "domain": "career",
  "input": "…the user's situation, at least 20 characters…",
  "expected_forks": ["accept", "negotiat"],   // stems; prefix-matched
  "expected_domain": "career",
  "required_constraints": ["runway_months"],  // machine-readable keys
  "expected_facts": ["40%", "parents"],       // must appear as grounded
  "must_not_hallucinate": ["rent", "salary"], // must never be asserted
  "min_branches": 3,
  "reworded_input": "…the same situation in different words…",
  "notes": "why this fixture exists"
}
```

Tokens in `expected_facts` and `must_not_hallucinate` are matched on word
boundaries, so `rent` does not match `currently`. `expected_forks` entries are
prefix-matched, so `relocat` covers both *relocate* and *relocation*.

The scorers themselves are unit-tested in
[`apps/api/tests/test_eval_harness.py`](../apps/api/tests/test_eval_harness.py) —
a silently wrong scorer is worse than a failing one.

Target: 100+ fixtures long-term. 21 with a working harness beats 100 with a stub.
