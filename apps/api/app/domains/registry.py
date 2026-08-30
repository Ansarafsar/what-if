from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.domain import ConstraintItem, DomainType, ForkPoint


class DomainModule(BaseModel):
    """Per-domain reasoning contract injected into the generic pipeline."""

    domain: DomainType
    variables: list[str]
    dimensions: list[str]
    canonical_forks: list[ForkPoint] = Field(default_factory=list)
    seed_strategies: list[str] = Field(default_factory=list)
    constraints: list[ConstraintItem] = Field(default_factory=list)
    determinism: Literal["llm_led", "hybrid", "calc_led"] = "llm_led"
    hard_rules: list[str] = Field(default_factory=list)
    prompt_addendum: str = ""


def _fork(id_: str, question: str, options: list[str], importance: float) -> ForkPoint:
    return ForkPoint(id=id_, description=question, question=question, options_hint=options, importance=importance)


GENERAL = DomainModule(
    domain=DomainType.GENERAL,
    variables=["situation", "resources", "time_horizon", "key_relationships", "risk_tolerance"],
    dimensions=["time", "money", "stress", "opportunity", "relationships"],
    canonical_forks=[_fork("primary_decision", "What is the central decision or event to fork on?", [], 0.7)],
    seed_strategies=["conventional", "reversible", "blind_spot"],
    determinism="llm_led",
    hard_rules=["Never present speculation as fact.", "Mark missing information as UNKNOWN."],
)

CAREER = DomainModule(
    domain=DomainType.CAREER,
    variables=[
        "role", "skills", "experience", "salary", "location", "network",
        "free_time", "stress", "family_proximity", "career_trajectory",
        "startup_time_per_week", "savings_capacity",
    ],
    dimensions=["career", "money", "freedom", "learning", "family_proximity", "network", "stress", "startup_capacity"],
    canonical_forks=[
        _fork("job_offer", "Accept, reject, negotiate, or delay the offer?", ["accept", "reject", "negotiate", "delay", "remote/hybrid"], 0.9),
        _fork("trajectory_shift", "Change role, employer, or specialization?", [], 0.6),
    ],
    seed_strategies=["conventional", "conservative", "opportunistic", "reversible", "hybrid", "blind_spot"],
    determinism="llm_led",
    prompt_addendum=(
        "Career reasoning weighs trajectory (skill/role compounding), opportunity "
        "(network, market), and resource allocation (time and money across job vs side projects)."
    ),
)

RELATIONSHIP = DomainModule(
    domain=DomainType.RELATIONSHIP,
    variables=[
        "communication_quality", "trust", "conflict_level", "distance",
        "contact_frequency", "shared_goals", "boundaries", "timing",
    ],
    dimensions=["trust", "closeness", "communication", "personal_growth", "stability"],
    canonical_forks=[
        _fork("repair_or_distance", "Repair, create distance, or accept separation?", ["repair", "distance", "separation", "pause"], 0.8),
    ],
    seed_strategies=["conventional", "conservative", "contrarian", "blind_spot"],
    determinism="llm_led",
    hard_rules=[
        "Never claim to know another person's thoughts, feelings, or intentions.",
        "Represent other people's reactions as scenarios, never as facts.",
        "Do not optimize every path toward reconciliation; growth-without-reunion paths are valid.",
        "Never guarantee romantic outcomes.",
    ],
    prompt_addendum="Model reciprocity explicitly: every branch should acknowledge the other person's agency.",
)

BUSINESS = DomainModule(
    domain=DomainType.BUSINESS,
    variables=[
        "price", "conversion_rate", "cac", "churn", "margin", "runway_months",
        "cash", "headcount", "distribution_channel", "customers", "ltv",
    ],
    dimensions=["revenue", "runway", "growth", "learning", "complexity", "risk", "optionality"],
    canonical_forks=[
        _fork("launch_timing", "Launch now, wait, or pivot?", ["launch", "wait", "pivot"], 0.85),
        _fork("gtm_model", "B2B, B2C, bootstrap, or raise?", ["b2b", "b2c", "bootstrap", "raise"], 0.7),
    ],
    seed_strategies=["conventional", "conservative", "opportunistic", "contrarian", "hybrid"],
    constraints=[ConstraintItem(description="Runway must stay above 6 months", kind="financial", key="runway_months", operator=">=", value=6)],
    determinism="hybrid",
    hard_rules=[
        "The LLM must not invent numeric calculations; propose hypotheses only.",
        "Any arithmetic belongs to deterministic code, not generated text.",
    ],
    prompt_addendum="Business reasoning combines unit economics (price/conversion/churn/margin/runway) with market hypotheses.",
)

SOFTWARE = DomainModule(
    domain=DomainType.SOFTWARE,
    variables=[
        "architecture", "dependencies", "tech_stack", "release_cycle",
        "technical_debt", "team_velocity", "test_coverage",
    ],
    dimensions=["architecture_health", "velocity", "risk", "maintainability", "operational_complexity"],
    canonical_forks=[
        _fork("merge_point", "Merge, revert, or rework this change?", ["merge", "reject", "rework"], 0.8),
        _fork("architecture_choice", "Keep current architecture or refactor?", ["keep", "incremental_refactor", "rewrite"], 0.75),
    ],
    seed_strategies=["conventional", "conservative", "contrarian", "blind_spot"],
    determinism="hybrid",
    hard_rules=[
        "Historical repository facts are GROUNDED; future architecture is SPECULATIVE.",
        "Do not invent commit contents, file changes, or dependency versions.",
    ],
    prompt_addendum="Software counterfactuals must preserve everything before the fork point exactly as history recorded it.",
)

PURCHASE = DomainModule(
    domain=DomainType.PURCHASE,
    variables=["price", "usage_hours_per_week", "maintenance_cost", "resale_value", "replacement_years", "budget_remaining"],
    dimensions=["cost", "utility", "flexibility", "opportunity_cost"],
    canonical_forks=[_fork("buy_decision", "Buy now, wait, buy used, or repair existing?", ["buy_now", "wait", "buy_used", "repair", "buy_cheaper", "buy_premium"], 0.6)],
    seed_strategies=["conventional", "conservative", "contrarian", "blind_spot"],
    determinism="calc_led",
    hard_rules=["Never invent product specifications or prices; use supplied data or mark UNKNOWN."],
    prompt_addendum="Frame purchases as ownership cost over time plus opportunity cost of capital.",
)

FINANCE = DomainModule(
    domain=DomainType.FINANCE,
    variables=["monthly_income", "monthly_expenses", "savings", "investments", "debt", "tax_regime"],
    dimensions=["savings_capacity", "risk_exposure", "liquidity", "long_term_wealth"],
    canonical_forks=[_fork("allocation", "Invest, save, pay down debt, or spend?", ["invest", "save", "pay_debt", "spend"], 0.65)],
    seed_strategies=["conventional", "conservative", "contrarian"],
    determinism="calc_led",
    hard_rules=[
        "The system does not provide professional financial or tax advice.",
        "All arithmetic must be presented as reproducible calculations with visible inputs.",
    ],
)

HABIT = DomainModule(
    domain=DomainType.HABIT,
    variables=["behavior", "consistency", "time_invested_weekly", "energy", "environment"],
    dimensions=["skill_accumulation", "wellbeing", "freedom", "identity", "consistency_risk"],
    canonical_forks=[_fork("commitment", "Adopt the principle fully, partially, or not at all?", ["full", "partial", "trial_period", "skip"], 0.55)],
    seed_strategies=["conventional", "conservative", "reversible", "blind_spot"],
    determinism="llm_led",
    hard_rules=["Never claim a self-help principle guarantees specific outcomes."],
    prompt_addendum='Always answer two questions: what does this principle optimize for, and what does it trade away?',
)

REFLECTION = DomainModule(
    domain=DomainType.REFLECTION,
    variables=["observed_elements", "emotional_tone", "recurrence"],
    dimensions=["self_understanding", "emotional_salience"],
    canonical_forks=[_fork("interpretation", "Which interpretation resonates with your current reality?", [], 0.4)],
    seed_strategies=["blind_spot"],
    determinism="llm_led",
    hard_rules=[
        'Never state "your dream means X"; interpretations are possibilities.',
        "Always include the possibility that there is no meaningful interpretation.",
    ],
)


REGISTRY: dict[DomainType, DomainModule] = {
    DomainType.GENERAL: GENERAL,
    DomainType.CAREER: CAREER,
    DomainType.RELATIONSHIP: RELATIONSHIP,
    DomainType.BUSINESS: BUSINESS,
    DomainType.SOFTWARE: SOFTWARE,
    DomainType.PURCHASE: PURCHASE,
    DomainType.FINANCE: FINANCE,
    DomainType.HABIT: HABIT,
    DomainType.REFLECTION: REFLECTION,
}


def get_domain_module(domain: DomainType | str) -> DomainModule:
    if isinstance(domain, str):
        try:
            domain = DomainType(domain)
        except ValueError:
            return GENERAL
    return REGISTRY.get(domain, GENERAL)
