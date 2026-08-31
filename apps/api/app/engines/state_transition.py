import logging
import re
from typing import Any

from app.schemas.domain import Evidence, EvidenceType, RealityState

logger = logging.getLogger(__name__)

# A state value is data the next fork reasons from and that `compare` diffs.
# Models sometimes answer with a hedge instead ("depends on the outcome
# (unknown)"), which would be written into the child's world verbatim.
_MAX_VALUE_CHARS = 48
# A value names a state ("Bengaluru", "b2b", "hybrid, 2 days remote"). Past a few
# words it is describing the state instead, which is what `rationale` is for.
_MAX_VALUE_WORDS = 3
_HEDGE_PATTERN = re.compile(
    r"\b(unknown|unclear|depends|assumed|estimated|uncertain|tbd|n/?a|varies|"
    r"potentially|possibly|if\s|may\b|might\b|"
    # Deferral phrasings a model reaches for when it has no value yet.
    r"to be (measured|determined|decided|confirmed)|pending)",
    re.IGNORECASE,
)


def is_usable_value(value: Any) -> bool:
    """True when a delta value is data rather than commentary.

    Numbers and booleans always qualify. A string qualifies only if it reads
    like a value ("Bengaluru", "hybrid") rather than a sentence about one.
    """
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        # [old, new] pairs are kept when both halves are themselves usable.
        return len(value) == 2 and all(is_usable_value(v) for v in value)
    if isinstance(value, str):
        text = value.strip()
        if not text or len(text) > _MAX_VALUE_CHARS:
            return False
        if len(text.split()) > _MAX_VALUE_WORDS:
            return False
        return _HEDGE_PATTERN.search(text) is None
    return False


def apply_delta(base: dict, delta: dict) -> dict:
    """Apply a state delta to a state snapshot.

    Values may be scalars (replace) or [old, new] pairs (kept as-is).
    Everything before the fork stays untouched - only listed keys change.

    Values that are prose rather than data are dropped: an omitted key honestly
    means "this branch does not change that variable", whereas storing the
    sentence would corrupt the world every descendant reasons from. The text is
    not lost - the branch's rationale and assumptions still carry it.
    """
    new_state = dict(base)
    for key, value in (delta or {}).items():
        if not is_usable_value(value):
            logger.info("dropping non-scalar state_delta value for %r: %r", key, value)
            continue
        new_state[key] = list(value) if isinstance(value, list) else value
    return new_state


def _describe(key: str, value: Any) -> str:
    """Render one delta entry as a human-readable claim."""
    if isinstance(value, list) and len(value) == 2:
        return f"{key} changes from {value[0]} to {value[1]}"
    return f"{key} becomes {value}"


def resulting_state(
    parent: RealityState,
    delta: dict[str, Any],
    branch_label: str,
    branch_narrative: str = "",
) -> RealityState:
    """Project a parent reality forward through one branch's state delta.

    The returned state is a full RealityState, not a bare dict, so an expanded
    node can be fed straight back into the pipeline as its own reality. Every
    applied delta key is appended to `facts` as SPECULATIVE evidence: nothing
    downstream of a fork is grounded, and the marker keeps that visible.
    """
    child = parent.model_copy(deep=True)

    variables = apply_delta(parent_variables(parent), delta)
    child.summary = branch_narrative.strip() or f"{parent.summary} Then: {branch_label}."
    child.title = branch_label or parent.title

    # A value that could not be applied is still worth recording - it says the
    # branch touches that variable without knowing how - but it is UNKNOWN
    # rather than SPECULATIVE, because no projected value exists at all.
    child.facts = list(parent.facts) + [
        Evidence(
            claim=(
                _describe(key, value)
                if is_usable_value(value)
                else f"{key} is affected, but no definite value was projected: {value}"
            ),
            evidence_type=(
                EvidenceType.SPECULATIVE if is_usable_value(value) else EvidenceType.UNKNOWN
            ),
            source=f"branch:{branch_label}",
            confidence=0.4 if is_usable_value(value) else 0.1,
        )
        for key, value in (delta or {}).items()
    ]

    # Decision hints belonged to the fork we just resolved; the expansion stage
    # detects the next fork from the projected world instead.
    child.decision_hints = []
    child.state_variables = variables
    return child


def parent_variables(state: RealityState) -> dict[str, Any]:
    """The structured variable snapshot a state carries, empty for a root."""
    return dict(getattr(state, "state_variables", None) or {})
