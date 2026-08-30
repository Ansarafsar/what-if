import re

from app.domains.registry import DomainModule
from app.schemas.domain import PLAUSIBILITY_SCORE, CandidateAction, ConsequenceResult, ScoredBranch

_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "with", "for", "on",
    "keep", "while", "continue", "this", "that",
}

_MAGNITUDE_WEIGHT = {"high": 0.3, "medium": 0.2, "low": 0.1}

WEIGHTS = {
    "relevance": 0.25,
    "plausibility": 0.25,
    "downstream_impact": 0.20,
    "novelty": 0.15,
    "reversibility": 0.05,
    "redundancy": -0.10,
}


def _normalize_label(label: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", label.lower())
    return {w for w in words if w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _values_agree(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        scale = max(abs(a), abs(b), 1e-9)
        return abs(a - b) / scale <= 0.10
    return str(a).strip().lower() == str(b).strip().lower()


def _delta_agreement(keys_a: set[str], keys_b: set[str], a: dict, b: dict) -> float:
    """Fraction of shared keys whose proposed VALUES also agree."""
    shared = keys_a & keys_b
    if not shared:
        return 0.0
    agreeing = sum(1 for k in shared if _values_agree(a.get(k), b.get(k)))
    return agreeing / len(shared)


def similarity(a: CandidateAction, b: CandidateAction) -> float:
    """Semantic-ish similarity: label overlap plus VALUE-AWARE delta structure.

    Same delta keys alone do not imply duplication - 'relocate permanently' and
    'relocate for a 6-month trial' share keys but propose different lives.
    """
    label_sim = _jaccard(_normalize_label(a.label), _normalize_label(b.label))
    delta_a, delta_b = a.state_delta or {}, b.state_delta or {}
    keys_a, keys_b = set(delta_a.keys()), set(delta_b.keys())

    key_component = 0.0
    if keys_a and keys_b:
        key_jaccard = _jaccard(keys_a, keys_b)
        agreement = _delta_agreement(keys_a, keys_b, delta_a, delta_b)
        key_component = key_jaccard * (0.4 + 0.6 * agreement)

    return max(label_sim, key_component)


def _impact_score(consequence: ConsequenceResult) -> float:
    if not consequence.effects:
        return 0.0
    raw = sum(
        _MAGNITUDE_WEIGHT.get(effect.magnitude, 0.1) * (1.5 if effect.order == 1 else 1.0)
        for effect in consequence.effects
    )
    return min(1.0, raw / 2.0)


def score_branch(
    branch: ScoredBranch,
    existing: list[ScoredBranch],
    domain: DomainModule,
) -> tuple[float, dict[str, float], float]:
    """Returns (total_score, breakdown, redundancy)."""
    candidate = branch.candidate

    relevance = 0.7 if candidate.strategy in domain.seed_strategies else 0.4
    plausibility = PLAUSIBILITY_SCORE[branch.consequence.plausibility]
    impact = _impact_score(branch.consequence)

    redundancy = max(
        (similarity(candidate, other.candidate) for other in existing),
        default=0.0,
    )
    novelty = max(0.0, 1.0 - redundancy)

    reversibility = 1.0 if candidate.reversible else 0.3

    penalty = 0.0
    if branch.review is not None:
        if branch.review.verdict == "revise":
            penalty += 0.15
        penalty += min(0.2, len(branch.review.unsupported_claims) * 0.05)
        penalty += min(0.2, len(branch.constraint_violations) * 0.1)

    breakdown = {
        "relevance": relevance * WEIGHTS["relevance"],
        "plausibility": plausibility * WEIGHTS["plausibility"],
        "downstream_impact": impact * WEIGHTS["downstream_impact"],
        "novelty": novelty * WEIGHTS["novelty"],
        "reversibility": reversibility * WEIGHTS["reversibility"],
        # WEIGHTS["redundancy"] is already negative; add it so the breakdown
        # entry and the total carry the same sign.
        "redundancy": WEIGHTS["redundancy"] * redundancy,
        "penalty": -penalty,
    }
    total = (
        relevance * WEIGHTS["relevance"]
        + plausibility * WEIGHTS["plausibility"]
        + impact * WEIGHTS["downstream_impact"]
        + novelty * WEIGHTS["novelty"]
        + reversibility * WEIGHTS["reversibility"]
        + WEIGHTS["redundancy"] * redundancy
        - penalty
    )
    return round(total, 4), breakdown, round(redundancy, 3)


def rank_and_prune(
    branches: list[ScoredBranch],
    domain: DomainModule,
    beam_width: int,
    dedup_threshold: float,
) -> list[ScoredBranch]:
    """Deterministic pipeline: score -> greedy dedup -> prune to beam width.

    Branches are processed in input order; a later branch that is too similar to
    an already-kept one is dropped regardless of score, mirroring how a reviewer
    would discard near-duplicates.
    """
    kept: list[ScoredBranch] = []
    results: list[ScoredBranch] = []

    for branch in branches:
        total, breakdown, _redundancy = score_branch(branch, kept, domain)
        branch.score = total
        branch.score_breakdown = breakdown

        is_duplicate = any(
            similarity(branch.candidate, keep.candidate) >= dedup_threshold for keep in kept
        )
        if not is_duplicate:
            kept.append(branch)
            results.append(branch)

    results.sort(key=lambda b: (-b.score, b.candidate.label))
    return results[:beam_width]
