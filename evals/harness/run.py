"""WHAT IF evaluation harness.

Scores the engine on the PRD 66 dimensions against the fixtures in
`evals/fixtures/`. Unlike `apps/api/tests`, this is meant to run against a live
model - it is the only place reasoning quality is actually measured, because a
test running on MockProvider can only ever re-read its own fixture.

Usage:
    python evals/harness/run.py                      # every fixture
    python evals/harness/run.py --fixture career_bengaluru_offer
    python evals/harness/run.py --domain career --no-stability
    python evals/harness/run.py --provider mock      # smoke-test the harness

Set LLM_PROVIDER=openrouter and OPENROUTER_API_KEY for a real run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.config import get_settings  # noqa: E402
from app.engines.scoring import similarity  # noqa: E402
from app.graphs.generation import run_generation  # noqa: E402
from app.llm.base import LLMError  # noqa: E402
from app.llm.demo_responses import DEMO_RESPONSES  # noqa: E402
from app.llm.mock import MockProvider  # noqa: E402
from app.llm.openrouter import OpenRouterProvider  # noqa: E402
from app.schemas.domain import EvidenceType, RealityState  # noqa: E402
from app.services.pipeline import PossibilityPipeline  # noqa: E402

FIXTURES_DIR = ROOT / "evals" / "fixtures"
RESULTS_DIR = ROOT / "evals" / "results"


@dataclass
class Score:
    """One scored dimension. `weight` is 0 for diagnostics that do not gate."""

    name: str
    value: float
    detail: str = ""
    weight: float = 1.0


@dataclass
class FixtureResult:
    fixture_id: str
    domain: str
    passed: bool
    scores: list[Score] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    branch_labels: list[str] = field(default_factory=list)

    @property
    def overall(self) -> float:
        weighted = [s for s in self.scores if s.weight > 0]
        if not weighted:
            return 0.0
        total = sum(s.weight for s in weighted)
        return sum(s.value * s.weight for s in weighted) / total


def load_fixtures(fixture_id: str | None, domain: str | None) -> list[dict[str, Any]]:
    fixtures = []
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if fixture_id and data["id"] != fixture_id:
            continue
        if domain and data.get("domain") != domain:
            continue
        fixtures.append(data)
    return fixtures


def build_provider(name: str):
    settings = get_settings()
    if name == "openrouter":
        return OpenRouterProvider(settings)
    return MockProvider(dict(DEMO_RESPONSES))


# --------------------------------------------------------------------------
# Scorers
# --------------------------------------------------------------------------

REQUIRED_STATE_FIELDS = ("title", "summary", "domain", "events", "decision_hints")


def mentions(haystack: str, token: str) -> bool:
    """Whole-token containment.

    Plain substring matching is not usable here: "rent" appears inside
    "currently", so a forbidden-token check would fire on innocent text and a
    grounding check would pass on text that never made the claim. Multi-word
    tokens are matched as a phrase with flexible whitespace.
    """
    escaped = r"\s+".join(re.escape(part) for part in token.split())
    # \b does not anchor against '%' or digits, so fall back to a lookaround
    # that treats any non-alphanumeric character as a boundary.
    pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
    return re.search(pattern, haystack, flags=re.IGNORECASE) is not None


def starts_with(haystack: str, stem: str) -> bool:
    """Prefix match on a word, for fork stems like "relocat" or "negotiat"."""
    escaped = r"\s+".join(re.escape(part) for part in stem.split())
    return re.search(rf"(?<![a-z0-9]){escaped}", haystack, flags=re.IGNORECASE) is not None


def score_extraction_completeness(state: RealityState) -> Score:
    """Did extraction populate the fields the rest of the engine depends on?"""
    present = sum(1 for field_name in REQUIRED_STATE_FIELDS if getattr(state, field_name))
    missing = [f for f in REQUIRED_STATE_FIELDS if not getattr(state, f)]
    return Score(
        name="extraction_completeness",
        value=present / len(REQUIRED_STATE_FIELDS),
        detail=f"missing: {', '.join(missing)}" if missing else "all core fields present",
    )


def score_grounding(state: RealityState, fixture: dict) -> Score:
    """Are the facts the user actually stated present and marked GROUNDED?"""
    expected = [e.lower() for e in fixture.get("expected_facts", [])]
    if not expected:
        return Score(name="grounding", value=1.0, detail="no expected facts declared", weight=0.0)

    grounded_text = " ".join(
        fact.claim.lower()
        for fact in state.facts
        if fact.evidence_type == EvidenceType.GROUNDED
    )
    grounded_text += " " + " ".join(event.description.lower() for event in state.events)
    grounded_text += " " + state.summary.lower()

    found = [token for token in expected if mentions(grounded_text, token)]
    missing = [token for token in expected if not mentions(grounded_text, token)]
    return Score(
        name="grounding",
        value=len(found) / len(expected),
        detail=f"missing from grounded text: {', '.join(missing)}" if missing else "all present",
    )


def score_hallucination_resistance(state: RealityState, branches, fixture: dict) -> Score:
    """The load-bearing check: unprovided facts must never appear as GROUNDED.

    Forbidden material is allowed to appear as an assumption, a question or a
    missing-information entry - that is the engine behaving correctly. It is a
    failure only when it is asserted as established fact.
    """
    forbidden = [token.lower() for token in fixture.get("must_not_hallucinate", [])]
    if not forbidden:
        return Score(name="hallucination_resistance", value=1.0, detail="none declared", weight=0.0)

    asserted = " ".join(
        fact.claim.lower()
        for fact in state.facts
        if fact.evidence_type == EvidenceType.GROUNDED
    )
    asserted += " " + " ".join(
        event.description.lower()
        for event in state.events
        if event.evidence_type == EvidenceType.GROUNDED
    )

    # A branch narrative asserting a forbidden figure without hedging is equally bad.
    for branch in branches:
        if branch.consequence.plausibility.value == "high":
            asserted += " " + branch.consequence.narrative.lower()

    hits = [token for token in forbidden if mentions(asserted, token)]
    return Score(
        name="hallucination_resistance",
        value=1.0 - (len(hits) / len(forbidden)),
        detail=f"asserted as grounded: {', '.join(hits)}" if hits else "clean",
    )


def score_schema_validity(state: RealityState, branches) -> Score:
    """Every payload already passed Pydantic; this checks semantic validity."""
    problems: list[str] = []
    if state.domain is None:
        problems.append("no domain")
    for branch in branches:
        if not branch.consequence.effects:
            problems.append(f"{branch.candidate.label}: no effects")
        if not branch.consequence.narrative.strip():
            problems.append(f"{branch.candidate.label}: empty narrative")
        if not 0.0 <= branch.score <= 1.5:
            problems.append(f"{branch.candidate.label}: score out of range ({branch.score})")
    total = max(1, len(branches) * 3 + 1)
    return Score(
        name="schema_validity",
        value=max(0.0, 1.0 - len(problems) / total),
        detail="; ".join(problems[:3]) if problems else "valid",
    )


def score_branch_coverage(branches, fixture: dict) -> Score:
    """Did the engine find the fork shapes a human would expect?"""
    expected = [token.lower() for token in fixture.get("expected_forks", [])]
    if not expected:
        return Score(name="branch_coverage", value=1.0, detail="none declared", weight=0.0)

    text = " ".join(
        f"{b.candidate.label} {b.candidate.description} {b.candidate.strategy}".lower()
        for b in branches
    )
    # Fork tokens are stems ("relocat" should match "relocate"/"relocation").
    hit = [token for token in expected if starts_with(text, token)]
    # Expected forks are alternatives, not a checklist: matching a good share is
    # the signal, matching every one would just reward verbosity.
    ratio = min(1.0, len(hit) / max(1, min(len(expected), 4)))
    return Score(
        name="branch_coverage",
        value=ratio,
        detail=f"matched {len(hit)}/{len(expected)}: {', '.join(hit[:4])}",
    )


def score_branch_diversity(branches) -> Score:
    """Reuses the engine's own similarity metric so the eval and the ranker agree."""
    if len(branches) < 2:
        return Score(name="branch_diversity", value=0.0, detail="fewer than two branches")

    pairs = [
        similarity(a.candidate, b.candidate)
        for i, a in enumerate(branches)
        for b in branches[i + 1 :]
    ]
    mean_similarity = statistics.fmean(pairs)
    worst = max(pairs)
    return Score(
        name="branch_diversity",
        value=1.0 - mean_similarity,
        detail=f"mean similarity {mean_similarity:.2f}, closest pair {worst:.2f}",
    )


def score_constraint_violations(branches, fixture: dict) -> Score:
    """Surviving branches must not breach a hard constraint."""
    violating = [b.candidate.label for b in branches if b.constraint_violations]
    required = fixture.get("required_constraints", [])
    detail = f"violating branches: {', '.join(violating)}" if violating else "none"
    if required:
        detail += f" (fixture expects keys: {', '.join(required)})"
    return Score(
        name="constraint_violations",
        value=1.0 if not violating else max(0.0, 1.0 - len(violating) / len(branches)),
        detail=detail,
    )


def score_stability(first_labels: list[str], second_labels: list[str]) -> Score:
    """Reword the input; the possibility space should not collapse or reshuffle."""
    if not second_labels:
        return Score(name="stability", value=0.0, detail="rerun produced no branches")

    from app.schemas.domain import CandidateAction

    def stub(label: str) -> CandidateAction:
        return CandidateAction(
            label=label, strategy="conventional", description="", rationale=""
        )

    matched = sum(
        1
        for label in first_labels
        if any(similarity(stub(label), stub(other)) >= 0.4 for other in second_labels)
    )
    count_ratio = min(len(second_labels), len(first_labels)) / max(
        len(second_labels), len(first_labels)
    )
    overlap = matched / len(first_labels)
    return Score(
        name="stability",
        value=(overlap + count_ratio) / 2,
        detail=f"{matched}/{len(first_labels)} branches recur; {len(first_labels)} vs {len(second_labels)} branches",
    )


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


async def generate_once(provider_name: str, raw_input: str, domain_hint=None):
    provider = build_provider(provider_name)
    pipeline = PossibilityPipeline(provider)
    state = await pipeline.extract_reality(raw_input, domain_hint=domain_hint)
    outcome = await run_generation(pipeline, uuid4(), state)
    return state, outcome, pipeline


async def run_fixture(fixture: dict, provider_name: str, check_stability: bool) -> FixtureResult:
    result = FixtureResult(fixture_id=fixture["id"], domain=fixture.get("domain", "general"), passed=False)
    started = time.perf_counter()

    try:
        state, outcome, pipeline = await generate_once(provider_name, fixture["input"])
    except (LLMError, ValueError) as exc:
        result.errors.append(f"{type(exc).__name__}: {exc}")
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        return result

    branches = outcome.branches
    result.branch_labels = [b.candidate.label for b in branches]
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    result.input_tokens = sum(e.input_tokens or 0 for e in outcome.executions)
    result.output_tokens = sum(e.output_tokens or 0 for e in outcome.executions)

    result.scores = [
        score_extraction_completeness(state),
        score_grounding(state, fixture),
        score_hallucination_resistance(state, branches, fixture),
        score_schema_validity(state, branches),
        score_branch_coverage(branches, fixture),
        score_branch_diversity(branches),
        score_constraint_violations(branches, fixture),
    ]

    expected_domain = fixture.get("expected_domain")
    if expected_domain:
        correct = state.domain.value == expected_domain
        result.scores.append(
            Score(
                name="domain_routing",
                value=1.0 if correct else 0.0,
                detail=f"got {state.domain.value}, expected {expected_domain}",
            )
        )

    min_branches = fixture.get("min_branches", 3)
    if len(branches) < min_branches:
        result.errors.append(f"only {len(branches)} branches, expected >= {min_branches}")

    if check_stability and fixture.get("reworded_input"):
        try:
            _, reworded_outcome, _ = await generate_once(provider_name, fixture["reworded_input"])
            result.scores.append(
                score_stability(
                    result.branch_labels,
                    [b.candidate.label for b in reworded_outcome.branches],
                )
            )
        except (LLMError, ValueError) as exc:
            result.errors.append(f"stability rerun failed: {exc}")

    result.passed = not result.errors and result.overall >= 0.7
    return result


def markdown_report(results: list[FixtureResult], provider: str) -> str:
    dimensions = [
        "extraction_completeness",
        "grounding",
        "hallucination_resistance",
        "schema_validity",
        "branch_coverage",
        "branch_diversity",
        "constraint_violations",
        "domain_routing",
        "stability",
    ]

    lines = [
        "# WHAT IF eval run",
        "",
        f"- provider: `{provider}`",
        f"- fixtures: {len(results)}",
        f"- passed: {sum(1 for r in results if r.passed)}/{len(results)}",
        "",
    ]

    if provider != "openrouter":
        lines += [
            "> **Scores below are not meaningful.** MockProvider replays the canned",
            "> Bengaluru career fixture for every input, so any non-career scenario is",
            "> answered with the wrong situation - which is what the low grounding and",
            "> domain_routing numbers are reporting. Use this mode to check the harness",
            "> itself; run with `--provider openrouter` to measure the engine.",
            "",
        ]

    lines += [
        "## Per fixture",
        "",
        "| fixture | overall | " + " | ".join(d[:12] for d in dimensions) + " | latency |",
        "|" + "---|" * (len(dimensions) + 3),
    ]

    for result in results:
        by_name = {s.name: s.value for s in result.scores}
        cells = [f"{by_name[d]:.2f}" if d in by_name else "-" for d in dimensions]
        flag = "" if result.passed else " (FAIL)"
        lines.append(
            f"| {result.fixture_id}{flag} | **{result.overall:.2f}** | "
            + " | ".join(cells)
            + f" | {result.latency_ms} ms |"
        )

    lines += ["", "## Dimension means", "", "| dimension | mean |", "|---|---|"]
    for dimension in dimensions:
        values = [s.value for r in results for s in r.scores if s.name == dimension]
        if values:
            lines.append(f"| {dimension} | {statistics.fmean(values):.3f} |")

    failures = [r for r in results if r.errors]
    if failures:
        lines += ["", "## Failures", ""]
        for result in failures:
            for error in result.errors:
                lines.append(f"- **{result.fixture_id}**: {error}")

    weak = [
        (r.fixture_id, s)
        for r in results
        for s in r.scores
        if s.weight > 0 and s.value < 0.7
    ]
    if weak:
        lines += ["", "## Weak dimensions (<0.70)", ""]
        for fixture_id, score in weak:
            lines.append(f"- **{fixture_id}** / {score.name} = {score.value:.2f} - {score.detail}")

    total_in = sum(r.input_tokens for r in results)
    total_out = sum(r.output_tokens for r in results)
    if total_in or total_out:
        lines += ["", f"Tokens: {total_in} in / {total_out} out."]

    return "\n".join(lines) + "\n"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", help="run a single fixture by id")
    parser.add_argument("--domain", help="run only fixtures in this domain")
    parser.add_argument(
        "--provider",
        default=None,
        help="openrouter | mock (defaults to LLM_PROVIDER)",
    )
    parser.add_argument(
        "--no-stability",
        action="store_true",
        help="skip the reworded rerun (halves token cost)",
    )
    parser.add_argument("--out", default=str(RESULTS_DIR), help="directory for the report")
    args = parser.parse_args()

    provider_name = args.provider or get_settings().llm_provider
    fixtures = load_fixtures(args.fixture, args.domain)
    if not fixtures:
        print("no fixtures matched", file=sys.stderr)
        return 2

    print(f"running {len(fixtures)} fixture(s) against provider={provider_name}\n")

    results: list[FixtureResult] = []
    for fixture in fixtures:
        result = await run_fixture(fixture, provider_name, not args.no_stability)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        print(f"  [{status}] {result.fixture_id:32s} overall={result.overall:.2f} ({result.latency_ms} ms)")
        for error in result.errors:
            print(f"         ! {error}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    (out_dir / f"eval-{stamp}.json").write_text(
        json.dumps(
            {
                "provider": provider_name,
                "fixtures": len(results),
                "passed": sum(1 for r in results if r.passed),
                "results": [asdict(r) | {"overall": r.overall} for r in results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    report = markdown_report(results, provider_name)
    (out_dir / f"eval-{stamp}.md").write_text(report, encoding="utf-8")

    # Fixture text may contain characters the Windows console encoding cannot
    # represent; the report file is UTF-8 either way, so never let printing it
    # be what fails the run.
    encoding = sys.stdout.encoding or "utf-8"
    print("\n" + report.encode(encoding, errors="replace").decode(encoding))
    print(f"reports written to {out_dir}")

    if provider_name != "openrouter":
        # A mock run only proves the harness executes; its scores are replayed
        # fixture data, so it must never report a pass/fail verdict on quality.
        print("\nmock run: harness executed, scores not meaningful (see report note)")
        return 0

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
