from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DomainType(str, Enum):
    GENERAL = "general"
    CAREER = "career"
    RELATIONSHIP = "relationship"
    BUSINESS = "business"
    SOFTWARE = "software"
    PURCHASE = "purchase"
    FINANCE = "finance"
    HABIT = "habit"
    REFLECTION = "reflection"


class EvidenceType(str, Enum):
    GROUNDED = "grounded"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    SPECULATIVE = "speculative"
    UNKNOWN = "unknown"


class Plausibility(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SPECULATIVE = "speculative"


PLAUSIBILITY_SCORE = {
    Plausibility.HIGH: 0.9,
    Plausibility.MEDIUM: 0.6,
    Plausibility.LOW: 0.3,
    Plausibility.SPECULATIVE: 0.15,
}

EffectDirection = Literal["up", "down", "flat", "uncertain"]
EffectMagnitude = Literal["low", "medium", "high"]


class Evidence(BaseModel):
    claim: str
    evidence_type: EvidenceType
    source: str = "user_input"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Assumption(BaseModel):
    claim: str
    depends_on: list[str] = Field(default_factory=list)


class Effect(BaseModel):
    dimension: str
    direction: EffectDirection
    magnitude: EffectMagnitude
    order: int = Field(default=1, ge=1, le=3)
    explanation: str


class EventItem(BaseModel):
    description: str
    timestamp: str | None = None
    evidence_type: EvidenceType = EvidenceType.GROUNDED


class DecisionHint(BaseModel):
    question: str
    options_hint: list[str] = Field(default_factory=list)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


class ConstraintItem(BaseModel):
    description: str
    kind: Literal[
        "financial", "time", "relationship", "location",
        "technical", "legal", "health", "personal",
    ] = "personal"
    key: str | None = None
    operator: Literal[">=", "<=", "==", ">", "<"] | None = None
    value: float | None = None


class RealityState(BaseModel):
    scenario_id: UUID | None = None
    title: str
    summary: str
    domain: DomainType = DomainType.GENERAL

    actors: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    decision_hints: list[DecisionHint] = Field(default_factory=list)
    constraints: list[ConstraintItem] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    beliefs: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)

    facts: list[Evidence] = Field(default_factory=list)

    # Structured world variables carried across forks. Empty at the root; each
    # expansion applies its branch's state_delta on top of its parent's copy.
    state_variables: dict[str, Any] = Field(default_factory=dict)

    def to_prompt_context(self) -> str:
        """Compact deterministic rendering used as LLM input context."""
        parts = [
            f"TITLE: {self.title}",
            f"DOMAIN: {self.domain.value}",
            f"SUMMARY: {self.summary}",
            f"ACTORS: {', '.join(self.actors) or 'none'}",
            f"ENTITIES: {', '.join(self.entities) or 'none'}",
            "EVENTS:",
        ]
        for event in self.events:
            stamp = f" ({event.timestamp})" if event.timestamp else ""
            marker = {"grounded": "", "inferred": " [inferred]", "assumed": " [assumed]"}.get(
                event.evidence_type.value, " [speculative]"
            )
            parts.append(f"- {event.description}{stamp}{marker}")
        parts.append("DECISIONS UNDER CONSIDERATION:")
        for hint in self.decision_hints:
            opts = ", ".join(hint.options_hint) if hint.options_hint else "open"
            parts.append(f"- {hint.question} (options: {opts}; importance {hint.importance:.2f})")
        parts.append("CONSTRAINTS:")
        for constraint in self.constraints:
            if constraint.key and constraint.operator is not None and constraint.value is not None:
                parts.append(f"- [{constraint.kind}] {constraint.key} {constraint.operator} {constraint.value} ({constraint.description})")
            else:
                parts.append(f"- [{constraint.kind}] {constraint.description}")
        parts.append(f"GOALS: {'; '.join(self.goals) or 'none'}")
        parts.append(f"RELATIONSHIPS: {'; '.join(self.relationships) or 'none'}")
        parts.append(f"RESOURCES: {'; '.join(self.resources) or 'none'}")
        parts.append(f"BELIEFS: {'; '.join(self.beliefs) or 'none'}")
        parts.append(f"KNOWN UNCERTAINTIES: {'; '.join(self.uncertainties) or 'none'}")
        parts.append(f"MISSING INFORMATION (treat as UNKNOWN): {'; '.join(self.missing_information) or 'none'}")
        if self.state_variables:
            parts.append("WORLD VARIABLES (result of choices already made; treat as SPECULATIVE):")
            for key in sorted(self.state_variables):
                value = self.state_variables[key]
                if isinstance(value, list) and len(value) == 2:
                    parts.append(f"- {key}: {value[0]} -> {value[1]}")
                else:
                    parts.append(f"- {key}: {value}")
        return "\n".join(parts)


class CandidateAction(BaseModel):
    label: str
    strategy: Literal[
        "conventional", "conservative", "opportunistic",
        "contrarian", "reversible", "hybrid", "blind_spot",
    ]
    description: str
    rationale: str
    reversible: bool = False
    state_delta: dict[str, Any] = Field(default_factory=dict)


class ForkPoint(BaseModel):
    id: str
    description: str
    question: str
    options_hint: list[str] = Field(default_factory=list)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


class ConsequenceResult(BaseModel):
    narrative: str
    effects: list[Effect] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    plausibility: Plausibility = Plausibility.MEDIUM
    plausibility_reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class BranchReview(BaseModel):
    label: str
    verdict: Literal["pass", "revise", "reject"]
    issues: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)


class ScoredBranch(BaseModel):
    candidate: CandidateAction
    consequence: ConsequenceResult
    review: BranchReview | None = None
    constraint_violations: list[str] = Field(default_factory=list)
    score: float = 0.0
    score_breakdown: dict[str, float] = Field(default_factory=dict)
