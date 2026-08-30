"""Graph nodes shared by the generation and expansion graphs.

Each node is a thin async wrapper around an existing PossibilityPipeline method,
so the pipeline stays the single place an LLM call is made and _run_stage keeps
recording prompt version, latency, tokens and retries for every stage.
"""

from app.domains.registry import get_domain_module
from app.engines.constraint_engine import evaluate_constraints
from app.engines.scoring import rank_and_prune
from app.graphs.state import WhatIfState
from app.schemas.domain import ScoredBranch
from app.services.pipeline import PossibilityPipeline


def _domain(state: WhatIfState):
    return get_domain_module(state["reality_state"].domain)


async def detect_forks_node(state: WhatIfState, pipeline: PossibilityPipeline) -> dict:
    forks = await pipeline.detect_forks(state["reality_state"])
    if not forks:
        raise ValueError("no fork points identified")
    primary = max(forks, key=lambda f: f.importance)
    return {"forks": forks, "primary_fork": primary, "executions": list(pipeline.executions)}


async def generate_candidates_node(state: WhatIfState, pipeline: PossibilityPipeline) -> dict:
    candidates = await pipeline.generate_candidates(
        state["reality_state"], state["primary_fork"], _domain(state)
    )
    return {"candidate_branches": candidates, "executions": list(pipeline.executions)}


async def generate_consequences_node(state: WhatIfState, pipeline: PossibilityPipeline) -> dict:
    """Only branches without a consequence are projected.

    On a revise iteration the passing branches already have theirs, so this
    never pays twice for the same branch.
    """
    consequences = dict(state.get("consequences") or {})
    for candidate in state["candidate_branches"]:
        if candidate.label in consequences:
            continue
        consequences[candidate.label] = await pipeline.generate_consequence(
            state["reality_state"], state["primary_fork"], candidate, _domain(state)
        )
    return {"consequences": consequences, "executions": list(pipeline.executions)}


async def verify_constraints_node(state: WhatIfState, pipeline: PossibilityPipeline) -> dict:
    """Deterministic. Violations are recorded, not silently dropped - a violating
    branch gets a revise pass before it is allowed to die."""
    errors: dict[str, list[str]] = {}
    for candidate in state["candidate_branches"]:
        violations = evaluate_constraints(state["reality_state"], candidate, _domain(state))
        if violations:
            errors[candidate.label] = violations
    return {"validation_errors": errors}


async def critique_node(state: WhatIfState, pipeline: PossibilityPipeline) -> dict:
    to_review = [
        c for c in state["candidate_branches"]
        if c.label not in (state.get("critic_reviews") or {})
    ]
    reviews = dict(state.get("critic_reviews") or {})
    if to_review:
        reviews.update(await pipeline.critique_branches(state["reality_state"], to_review))
    return {"critic_reviews": reviews, "executions": list(pipeline.executions)}


def _failure_reasons(state: WhatIfState, label: str) -> list[str]:
    reasons: list[str] = []
    review = (state.get("critic_reviews") or {}).get(label)
    if review is not None and review.verdict != "pass":
        reasons.extend(review.issues or [f"critic verdict: {review.verdict}"])
        reasons.extend(f"unsupported claim: {c}" for c in review.unsupported_claims)
    reasons.extend((state.get("validation_errors") or {}).get(label, []))
    return reasons


def partition_node(state: WhatIfState, pipeline: PossibilityPipeline) -> dict:
    """Split candidates into branches that survive and branches that need work.

    A branch fails if the critic rejected it, asked for a revision, or a hard
    constraint was violated. Nothing is discarded here - failures move to
    revising_branches and only become rejections once the budget is spent.
    """
    surviving: list[ScoredBranch] = []
    failing = []

    for candidate in state["candidate_branches"]:
        review = (state.get("critic_reviews") or {}).get(candidate.label)
        violations = (state.get("validation_errors") or {}).get(candidate.label, [])
        verdict = review.verdict if review else "pass"

        if verdict in {"reject", "revise"} or violations:
            failing.append(candidate)
            continue

        surviving.append(
            ScoredBranch(
                candidate=candidate,
                consequence=state["consequences"][candidate.label],
                review=review,
                constraint_violations=violations,
            )
        )

    return {"verified_branches": surviving, "revising_branches": failing}


def should_revise(state: WhatIfState) -> str:
    """Conditional edge. Revise while there is something to fix and budget left."""
    if state["iteration"] >= state["max_iterations"]:
        return "accept"
    if state.get("revising_branches"):
        return "revise"
    if len(state.get("verified_branches") or []) < state.get("min_candidates", 0):
        return "revise"
    return "accept"


async def revise_node(state: WhatIfState, pipeline: PossibilityPipeline) -> dict:
    """Regenerate only failing branches and fold the replacements back in."""
    failing_payload = [
        {
            "label": c.label,
            "description": c.description,
            "state_delta": c.state_delta,
            "reasons": _failure_reasons(state, c.label) or ["did not meet the minimum branch count"],
        }
        for c in state["revising_branches"]
    ]
    passing_labels = [b.candidate.label for b in state.get("verified_branches") or []]

    replacements = await pipeline.revise_candidates(
        state["reality_state"],
        state["primary_fork"],
        _domain(state),
        failing_payload,
        passing_labels,
    )

    passing = [b.candidate for b in state.get("verified_branches") or []]
    # Consequences and reviews for passing branches carry forward; the replacements
    # have neither, so the downstream nodes recompute exactly those.
    kept_labels = {c.label for c in passing}
    consequences = {k: v for k, v in state["consequences"].items() if k in kept_labels}
    reviews = {k: v for k, v in (state.get("critic_reviews") or {}).items() if k in kept_labels}

    return {
        "candidate_branches": passing + replacements,
        "consequences": consequences,
        "critic_reviews": reviews,
        "validation_errors": {},
        "revising_branches": [],
        "iteration": state["iteration"] + 1,
        "executions": list(pipeline.executions),
    }


def force_accept_node(state: WhatIfState, pipeline: PossibilityPipeline) -> dict:
    """Budget spent. Admit branches that only the critic disliked, reject the
    ones that break a hard constraint - a constraint is not negotiable."""
    accepted = list(state.get("verified_branches") or [])
    rejected = list(state.get("rejected_branches") or [])
    accepted_labels = {b.candidate.label for b in accepted}

    for candidate in state.get("revising_branches") or []:
        if candidate.label in accepted_labels:
            continue
        violations = (state.get("validation_errors") or {}).get(candidate.label, [])
        review = (state.get("critic_reviews") or {}).get(candidate.label)
        consequence = state["consequences"].get(candidate.label)

        if violations or consequence is None or (review and review.verdict == "reject"):
            rejected.append(
                {
                    "label": candidate.label,
                    "reasons": _failure_reasons(state, candidate.label),
                }
            )
            continue

        accepted.append(
            ScoredBranch(
                candidate=candidate,
                consequence=consequence,
                review=review,
                constraint_violations=violations,
            )
        )

    return {"verified_branches": accepted, "rejected_branches": rejected, "revising_branches": []}


def rank_node(state: WhatIfState, pipeline: PossibilityPipeline) -> dict:
    settings = pipeline.settings
    surviving = rank_and_prune(
        list(state.get("verified_branches") or []),
        _domain(state),
        beam_width=settings.engine_beam_width,
        dedup_threshold=settings.engine_dedup_threshold,
    )
    if not surviving:
        raise ValueError("all candidate branches were rejected by validation")
    return {"verified_branches": surviving}
