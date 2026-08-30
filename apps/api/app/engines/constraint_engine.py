import logging

from app.schemas.domain import CandidateAction, RealityState

logger = logging.getLogger(__name__)

# Directions in which a numeric constraint is "improved". An extracted `==` on a
# resource-style variable is almost always an over-strict reading of a stated
# quantity ("no buffer beyond four months" is a fact, not an equality), and it
# would reject every branch that makes the situation better.
_MORE_IS_BETTER = ("runway", "savings", "buffer", "cash", "income", "revenue")


def _is_improvement(key: str, proposed: float, limit: float) -> bool:
    """True when an `==` breach actually moves the variable the good way."""
    lowered = key.lower()
    if any(token in lowered for token in _MORE_IS_BETTER):
        return proposed > limit
    return False


def _all_constraints(state: RealityState, domain=None):
    """The scenario's own constraints plus the domain's standing rules.

    A domain declares invariants that hold whether or not the user mentioned
    them (business: runway must stay above 6 months). Evaluating only the
    extracted constraints let a branch burn runway to 2 months unchallenged.
    """
    constraints = list(state.constraints)
    if domain is not None:
        seen = {(c.key, c.operator, c.value) for c in constraints if c.key}
        for constraint in domain.constraints:
            if constraint.key and (constraint.key, constraint.operator, constraint.value) not in seen:
                constraints.append(constraint)
    return constraints


def evaluate_constraints(state: RealityState, candidate: CandidateAction, domain=None) -> list[str]:
    """Deterministic constraint checking. The LLM cannot override this.

    Only evaluates constraints that carry a machine-readable key/operator/value
    AND whose key is present in the candidate's state_delta (the value the branch
    would produce). Textual constraints are surfaced as warnings by callers.

    Pass `domain` to also enforce that domain's standing invariants.
    """
    violations: list[str] = []
    delta = candidate.state_delta or {}

    for constraint in _all_constraints(state, domain):
        if constraint.key is None or constraint.operator is None or constraint.value is None:
            continue
        if constraint.key not in delta:
            continue

        proposed = delta[constraint.key]
        if not isinstance(proposed, (int, float)) or isinstance(proposed, bool):
            continue

        op = constraint.operator
        limit = constraint.value
        breached = (
            (op == "<=" and proposed > limit)
            or (op == ">=" and proposed < limit)
            or (op == "==" and proposed != limit)
            or (op == "<" and proposed >= limit)
            or (op == ">" and proposed <= limit)
        )
        if breached and op == "==" and _is_improvement(constraint.key, proposed, limit):
            # Extraction sometimes records a stated quantity as an equality
            # ("only four months of runway"). Taken literally that rejects every
            # branch that improves the situation, which is the opposite of what
            # the user meant, so the breach is ignored and surfaced instead.
            logger.info(
                "ignoring '==' constraint on %s: proposed %s improves on %s",
                constraint.key, proposed, limit,
            )
            continue

        if breached:
            violations.append(
                f"'{constraint.key}' would become {proposed}, violating "
                f"{constraint.key} {op} {limit} ({constraint.description})"
            )

    return violations
