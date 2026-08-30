"""Deterministic two-node comparison. No LLM is involved.

PRD 50 asks for *relative* scenario dimensions: how do these two futures differ
from each other, not how good either one is in absolute terms. Both halves of
that come from data already stored on the nodes, so this is ordinary code.
"""

from typing import Any

_DIRECTION_RANK = {"down": -1, "flat": 0, "uncertain": 0, "up": 1}
_MAGNITUDE_RANK = {"low": 1, "medium": 2, "high": 3}


def _effect_value(effect: dict) -> float:
    """Signed strength of one effect, discounted by how far downstream it is."""
    direction = _DIRECTION_RANK.get(effect.get("direction", "flat"), 0)
    magnitude = _MAGNITUDE_RANK.get(effect.get("magnitude", "low"), 1)
    order = max(1, int(effect.get("order", 1) or 1))
    return direction * magnitude / order


def _dimension_scores(effects: list[dict]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for effect in effects or []:
        dimension = effect.get("dimension")
        if not dimension:
            continue
        scores[dimension] = scores.get(dimension, 0.0) + _effect_value(effect)
    return scores


def _arrows(delta: float) -> str:
    if delta == 0:
        return "="
    symbol = "↑" if delta > 0 else "↓"
    steps = min(3, max(1, round(abs(delta))))
    return symbol * steps


def compare_dimensions(left_effects: list[dict], right_effects: list[dict]) -> list[dict[str, Any]]:
    """Per-dimension difference between two branches, left relative to right."""
    left = _dimension_scores(left_effects)
    right = _dimension_scores(right_effects)

    rows = []
    for dimension in sorted(set(left) | set(right)):
        left_score = left.get(dimension, 0.0)
        right_score = right.get(dimension, 0.0)
        delta = round(left_score - right_score, 3)
        rows.append(
            {
                "dimension": dimension,
                "left": round(left_score, 3),
                "right": round(right_score, 3),
                "delta": delta,
                "direction": "left" if delta > 0 else ("right" if delta < 0 else "even"),
                "marker": _arrows(delta),
                "shared": dimension in left and dimension in right,
            }
        )
    return rows


def compare_state(left: dict | None, right: dict | None) -> list[dict[str, Any]]:
    """Key-by-key difference between two resulting world states."""
    left_vars = ((left or {}).get("state_variables")) or {}
    right_vars = ((right or {}).get("state_variables")) or {}

    rows = []
    for key in sorted(set(left_vars) | set(right_vars)):
        left_value = left_vars.get(key)
        right_value = right_vars.get(key)
        rows.append(
            {
                "key": key,
                "left": left_value,
                "right": right_value,
                "same": left_value == right_value,
                "only_in": None if key in left_vars and key in right_vars
                else ("left" if key in left_vars else "right"),
            }
        )
    return rows


def compare_nodes(left_node, right_node) -> dict[str, Any]:
    """Full comparison payload for two possibility nodes.

    `left_node` / `right_node` are PossibilityNode schemas (or anything exposing
    .title, .description, .plausibility, .score and .metadata).
    """
    left_meta = left_node.metadata or {}
    right_meta = right_node.metadata or {}

    return {
        "left": {
            "id": str(left_node.id),
            "title": left_node.title,
            "plausibility": getattr(left_node.plausibility, "value", left_node.plausibility),
            "score": left_node.score,
            "path_labels": left_meta.get("path_labels", []),
        },
        "right": {
            "id": str(right_node.id),
            "title": right_node.title,
            "plausibility": getattr(right_node.plausibility, "value", right_node.plausibility),
            "score": right_node.score,
            "path_labels": right_meta.get("path_labels", []),
        },
        "dimensions": compare_dimensions(
            left_meta.get("effects", []), right_meta.get("effects", [])
        ),
        "state": compare_state(
            left_meta.get("resulting_state"), right_meta.get("resulting_state")
        ),
        "relative": True,
        "note": "Differences are relative to each other, not objective quality judgements.",
    }
