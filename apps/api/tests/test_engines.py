from uuid import uuid4

import pytest

from app.domains.registry import get_domain_module
from app.engines.constraint_engine import evaluate_constraints
from app.engines.graph_builder import build_graph
from app.engines.scoring import rank_and_prune, similarity
from app.engines.state_transition import apply_delta, is_usable_value, resulting_state
from app.schemas.domain import (
    BranchReview,
    CandidateAction,
    ConsequenceResult,
    ConstraintItem,
    Effect,
    EvidenceType,
    Plausibility,
    RealityState,
    ScoredBranch,
)


def make_consequence(plausibility=Plausibility.HIGH, n_effects=3):
    effects = [
        Effect(dimension="money", direction="up", magnitude="medium", order=1, explanation=f"effect {i}")
        for i in range(n_effects)
    ]
    return ConsequenceResult(
        narrative="A plausible narrative.",
        effects=effects,
        plausibility=plausibility,
        plausibility_reasons=["consistent with facts"],
    )


def make_candidate(label="Work remotely", strategy="conventional", delta=None, reversible=True):
    return CandidateAction(
        label=label,
        strategy=strategy,
        description="desc",
        rationale="why",
        reversible=reversible,
        state_delta=delta or {},
    )


class TestConstraintEngine:
    def _state(self, constraints):
        return RealityState(
            title="t",
            summary="s" * 20,
            domain="career",
            constraints=constraints,
        )

    def test_budget_violation_rejected(self):
        state = self._state([
            ConstraintItem(description="Monthly budget cap", kind="financial", key="monthly_cost", operator="<=", value=30000)
        ])
        candidate = make_candidate(delta={"monthly_cost": 50000})
        violations = evaluate_constraints(state, candidate)
        assert len(violations) == 1
        assert "50000" in violations[0]

    def test_within_budget_passes(self):
        state = self._state([
            ConstraintItem(description="Budget", kind="financial", key="monthly_cost", operator="<=", value=30000)
        ])
        assert evaluate_constraints(state, make_candidate(delta={"monthly_cost": 28000})) == []

    def test_unmapped_textual_constraint_ignored(self):
        state = self._state([ConstraintItem(description="Family proximity matters")])
        assert evaluate_constraints(state, make_candidate(delta={"anything": 1})) == []

    def test_domain_invariant_is_enforced_without_being_restated(self):
        """BUSINESS declares runway >= 6. A branch burning runway to 2 months
        used to pass unchallenged because only extracted constraints were read."""
        domain = get_domain_module("business")
        state = RealityState(title="t", summary="s" * 20, domain="business", constraints=[])
        candidate = make_candidate("Burn runway", delta={"runway_months": 2})

        assert evaluate_constraints(state, candidate) == []  # no domain passed
        violations = evaluate_constraints(state, candidate, domain)
        assert len(violations) == 1
        assert "runway_months" in violations[0]

    def test_domain_invariant_allows_a_compliant_branch(self):
        domain = get_domain_module("business")
        state = RealityState(title="t", summary="s" * 20, domain="business", constraints=[])
        assert evaluate_constraints(state, make_candidate(delta={"runway_months": 9}), domain) == []

    def test_domain_invariant_is_not_double_counted(self):
        """A user who restates the domain rule must not get two violations."""
        domain = get_domain_module("business")
        state = RealityState(
            title="t", summary="s" * 20, domain="business",
            constraints=[ConstraintItem(description="Runway floor", kind="financial",
                                        key="runway_months", operator=">=", value=6)],
        )
        violations = evaluate_constraints(state, make_candidate(delta={"runway_months": 2}), domain)
        assert len(violations) == 1

    def test_scenario_constraint_still_wins_for_other_keys(self):
        domain = get_domain_module("business")
        state = RealityState(
            title="t", summary="s" * 20, domain="business",
            constraints=[ConstraintItem(description="Cap", kind="financial",
                                        key="monthly_cost", operator="<=", value=1000)],
        )
        violations = evaluate_constraints(
            state, make_candidate(delta={"monthly_cost": 5000, "runway_months": 2}), domain
        )
        assert len(violations) == 2

    def _runway_equality(self):
        """The shape a live model produced from 'no savings buffer beyond four
        months': a stated quantity recorded as an equality."""
        return self._state([
            ConstraintItem(
                description="Only four months of savings buffer",
                kind="financial",
                key="savings_runway_months",
                operator="==",
                value=4,
            )
        ])

    def test_equality_does_not_reject_a_branch_that_improves_runway(self):
        """Taken literally, `== 4` rejects every branch that extends runway -
        the opposite of what the user meant."""
        state = self._runway_equality()
        assert evaluate_constraints(state, make_candidate(delta={"savings_runway_months": 8})) == []
        assert evaluate_constraints(state, make_candidate(delta={"savings_runway_months": 24})) == []

    def test_equality_still_rejects_a_branch_that_worsens_runway(self):
        state = self._runway_equality()
        violations = evaluate_constraints(state, make_candidate(delta={"savings_runway_months": 1}))
        assert len(violations) == 1
        assert "savings_runway_months" in violations[0]

    def test_equality_on_a_genuinely_fixed_term_is_still_enforced(self):
        """A contract length is not a resource; both directions are breaches."""
        state = self._state([
            ConstraintItem(
                description="Guarantee lasts two years",
                kind="time",
                key="employment_guarantee_years",
                operator="==",
                value=2,
            )
        ])
        assert evaluate_constraints(state, make_candidate(delta={"employment_guarantee_years": 5}))
        assert evaluate_constraints(state, make_candidate(delta={"employment_guarantee_years": 1}))

    def test_explicit_floor_and_ceiling_are_unaffected(self):
        floor = self._state([
            ConstraintItem(description="Keep runway above 6 months", kind="financial",
                           key="runway_months", operator=">=", value=6)
        ])
        assert evaluate_constraints(floor, make_candidate(delta={"runway_months": 9})) == []
        assert evaluate_constraints(floor, make_candidate(delta={"runway_months": 3}))

        ceiling = self._state([
            ConstraintItem(description="Budget cap", kind="financial",
                           key="monthly_cost", operator="<=", value=30000)
        ])
        assert evaluate_constraints(ceiling, make_candidate(delta={"monthly_cost": 20000})) == []
        assert evaluate_constraints(ceiling, make_candidate(delta={"monthly_cost": 50000}))


class TestScoringAndDedup:
    def test_similarity_merges_paraphrases(self):
        a = make_candidate("Work remotely", delta={"remote_ratio": 0.85, "salary": 106000})
        b = make_candidate("Request remote arrangement", delta={"remote_ratio": 0.8, "salary": 105000})
        c = make_candidate("Relocate to Bengaluru", delta={"location": "Bengaluru"})
        assert similarity(a, b) >= 0.5
        assert similarity(a, c) < 0.3

    def test_same_keys_different_values_are_not_duplicates(self):
        permanent = make_candidate("Accept and relocate", delta={"location": "Bengaluru", "salary": 112000, "family_proximity": -0.7})
        trial = make_candidate("Six-month relocation trial", delta={"location": "Bengaluru (trial)", "salary": 112000, "family_proximity": -0.5})
        assert similarity(permanent, trial) < 0.72

    def test_rank_prune_enforces_beam_and_dedup(self):
        branches = [
            ScoredBranch(candidate=make_candidate("Accept job", delta={"salary": 112000}), consequence=make_consequence()),
            ScoredBranch(candidate=make_candidate("Take the job offer", strategy="opportunistic", delta={"salary": 110000}), consequence=make_consequence()),
            ScoredBranch(candidate=make_candidate("Reject and build startup", strategy="contrarian"), consequence=make_consequence(Plausibility.MEDIUM)),
            ScoredBranch(candidate=make_candidate("Negotiate hybrid role", strategy="hybrid"), consequence=make_consequence(Plausibility.SPECULATIVE)),
        ]
        domain = get_domain_module("career")
        surviving = rank_and_prune(branches, domain, beam_width=4, dedup_threshold=0.72)
        labels = [b.candidate.label for b in surviving]
        assert len(surviving) == 3
        assert "Take the job offer" not in labels

    def test_scoring_is_deterministic(self):
        branches = [
            ScoredBranch(candidate=make_candidate(f"Path {i}", delta={"k": i}), consequence=make_consequence())
            for i in range(3)
        ]
        first = rank_and_prune(list(branches), get_domain_module("career"), beam_width=2, dedup_threshold=0.99)
        second = rank_and_prune(
            [ScoredBranch(**b.model_dump()) for b in branches], get_domain_module("career"), beam_width=2, dedup_threshold=0.99
        )
        assert [b.candidate.label for b in first] == [b.candidate.label for b in second]
        assert [b.score for b in first] == [b.score for b in second]

    def test_redundant_branch_scores_below_novel_one(self):
        novel = ScoredBranch(
            candidate=make_candidate("Accept and relocate", delta={"location": "Bengaluru"}),
            consequence=make_consequence(),
        )
        redundant = ScoredBranch(
            candidate=make_candidate("Accept the relocation", delta={"location": "Bengaluru"}),
            consequence=make_consequence(),
        )
        # dedup off, so the redundant branch survives and can be compared
        ranked = rank_and_prune(
            [novel, redundant], get_domain_module("career"), beam_width=5, dedup_threshold=1.01
        )
        scores = {b.candidate.label: b.score for b in ranked}
        assert scores["Accept the relocation"] < scores["Accept and relocate"]

    def test_score_breakdown_sums_to_total(self):
        branch = ScoredBranch(
            candidate=make_candidate("Only path", delta={"k": 1}), consequence=make_consequence()
        )
        rank_and_prune([branch], get_domain_module("career"), beam_width=5, dedup_threshold=0.72)
        assert round(sum(branch.score_breakdown.values()), 4) == branch.score

    def test_critic_penalty_lowers_score(self):
        clean = ScoredBranch(candidate=make_candidate("Clean path"), consequence=make_consequence(), review=None)
        flagged = ScoredBranch(
            candidate=make_candidate("Flagged path"),
            consequence=make_consequence(),
            review=BranchReview(label="Flagged path", verdict="revise", issues=["x"], unsupported_claims=["y"]),
        )
        ranked = rank_and_prune([clean, flagged], get_domain_module("general"), beam_width=5, dedup_threshold=0.99)
        scores = {b.candidate.label: b.score for b in ranked}
        assert scores["Clean path"] > scores["Flagged path"]


class TestStateTransition:
    def test_preserves_pre_fork_state(self):
        base = {"location": "Salem", "salary": 80000, "pet": "dog"}
        new_state = apply_delta(base, {"salary": 112000})
        assert new_state["pet"] == "dog"
        assert new_state["location"] == "Salem"
        assert new_state["salary"] == 112000
        assert base["salary"] == 80000

    def test_old_new_pair_kept_verbatim(self):
        new_state = apply_delta({}, {"salary": [80000, 112000]})
        assert new_state["salary"] == [80000, 112000]

    def _parent(self):
        return RealityState(
            title="Offer in Bengaluru",
            summary="Lives in Salem, has an offer." + " " * 5,
            domain="career",
            state_variables={"location": "Salem", "salary": 80000},
        )

    def test_resulting_state_projects_variables_forward(self):
        child = resulting_state(
            self._parent(),
            {"location": "Bengaluru", "salary": 112000},
            branch_label="Accept and relocate",
            branch_narrative="You move and start in six weeks.",
        )
        assert isinstance(child, RealityState)
        assert child.state_variables == {"location": "Bengaluru", "salary": 112000}
        assert child.title == "Accept and relocate"
        assert child.summary == "You move and start in six weeks."

    def test_resulting_state_does_not_mutate_parent(self):
        parent = self._parent()
        resulting_state(parent, {"salary": 112000}, "Accept")
        assert parent.state_variables["salary"] == 80000

    def test_delta_keys_become_speculative_evidence(self):
        child = resulting_state(self._parent(), {"salary": 112000}, "Accept")
        speculative = [f for f in child.facts if f.evidence_type == EvidenceType.SPECULATIVE]
        assert len(speculative) == 1
        assert "salary" in speculative[0].claim

    # Values a live model actually returned for the design-studio scenario.
    PROSE_VALUES = [
        "depends on signing bonus outcome (unknown)",
        "retained via continued branding (assumed)",
        "modest increase if deal pauses",
        "no immediate change; near-term client revenue continues (assumed)",
        "potentially improved via better compensation",
    ]

    @pytest.mark.parametrize("value", PROSE_VALUES)
    def test_prose_values_are_not_usable(self, value):
        assert not is_usable_value(value)

    @pytest.mark.parametrize(
        "value", [24, 0, -3.5, True, False, "Bengaluru", "hybrid", [80000, 112000]]
    )
    def test_scalar_values_are_usable(self, value):
        assert is_usable_value(value)

    def test_prose_value_never_reaches_the_world_state(self):
        """Storing the sentence would corrupt the world every descendant of
        this branch reasons from."""
        result = apply_delta(
            {"runway_months": 4},
            {"runway_months": 24, "cash": "depends on signing bonus outcome (unknown)"},
        )
        assert result == {"runway_months": 24}
        assert "cash" not in result

    def test_dropped_value_is_recorded_as_unknown_not_lost(self):
        child = resulting_state(
            self._parent(),
            {"salary": 112000, "cash": "depends on the outcome (unknown)"},
            branch_label="Accept",
        )
        assert child.state_variables == {"location": "Salem", "salary": 112000}

        bands = {f.evidence_type: f.claim for f in child.facts if f.source == "branch:Accept"}
        assert EvidenceType.SPECULATIVE in bands
        assert EvidenceType.UNKNOWN in bands
        assert "cash" in bands[EvidenceType.UNKNOWN]

    def test_pair_with_a_prose_half_is_rejected_whole(self):
        assert not is_usable_value([80000, "unknown after the raise"])
        assert apply_delta({}, {"salary": [80000, "unknown after the raise"]}) == {}

    def test_prompt_context_renders_world_variables(self):
        child = resulting_state(self._parent(), {"salary": [80000, 112000]}, "Accept")
        context = child.to_prompt_context()
        assert "WORLD VARIABLES" in context
        assert "salary: 80000 -> 112000" in context


class TestGraphBuilder:
    def test_graph_structure_and_acyclicity(self):
        branches = [
            ScoredBranch(candidate=make_candidate(f"Branch {chr(65+i)}", delta={"k": i}), consequence=make_consequence())
            for i in range(4)
        ]
        graph = build_graph(uuid4(), "summary of reality", "What to do?", "fork desc", branches)
        types = {n.node_type for n in graph.nodes}
        assert types == {"reality", "decision", "state"}
        root = next(n for n in graph.nodes if n.node_type == "reality")
        decision = next(n for n in graph.nodes if n.node_type == "decision")
        assert decision.parent_id == root.id
        assert len(graph.edges) == 5
        graph.validate_acyclic()

    def test_branch_metadata_carries_evidence(self):
        branch = ScoredBranch(
            candidate=make_candidate("Trial run", delta={"location": "trial"}),
            consequence=make_consequence(),
        )
        graph = build_graph(uuid4(), "sum", "q", "d", [branch])
        node = next(n for n in graph.nodes if n.title == "Trial run")
        assert node.metadata["evidence"]["assumptions"] is not None
        assert node.plausibility in (Plausibility.HIGH, Plausibility.MEDIUM, Plausibility.LOW, Plausibility.SPECULATIVE)

    def test_branch_nodes_carry_resulting_state_and_depth(self):
        state = RealityState(
            title="Offer",
            summary="A situation worth forking on.",
            domain="career",
            state_variables={"location": "Salem"},
        )
        branch = ScoredBranch(
            candidate=make_candidate("Relocate", delta={"location": "Bengaluru"}),
            consequence=make_consequence(),
        )
        graph = build_graph(uuid4(), "sum", "q", "d", [branch], reality_state=state)
        node = next(n for n in graph.nodes if n.title == "Relocate")
        assert node.metadata["depth"] == 2
        assert node.metadata["path_labels"] == ["Relocate"]
        assert node.metadata["resulting_state"]["state_variables"] == {"location": "Bengaluru"}
        assert node.metadata["expanded"] is False

    def test_secondary_forks_appear_as_unexpanded_decisions(self):
        from app.schemas.domain import ForkPoint

        branch = ScoredBranch(candidate=make_candidate("A"), consequence=make_consequence())
        extra = ForkPoint(id="second", description="Another choice", question="Move or stay?", importance=0.4)
        graph = build_graph(uuid4(), "sum", "q", "d", [branch], secondary_forks=[extra])
        decisions = [n for n in graph.nodes if n.node_type == "decision"]
        assert len(decisions) == 2
        unexpanded = next(n for n in decisions if n.metadata["fork_id"] == "second")
        assert unexpanded.metadata["expanded"] is False
        graph.validate_acyclic()


def test_domain_registry_covers_domains():
    from app.schemas.domain import DomainType

    for domain in DomainType:
        module = get_domain_module(domain)
        assert module.variables and module.dimensions
    relationship = get_domain_module(DomainType.RELATIONSHIP)
    assert any("never claim" in rule.lower() for rule in relationship.hard_rules)
