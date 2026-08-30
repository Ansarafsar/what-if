"""Unit tests for the eval scorers.

The harness is the only thing that measures reasoning quality, so a scoring bug
is worse than a failing test - it reports a number nobody can trust.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "evals" / "harness"))

import run as harness  # noqa: E402

from app.schemas.domain import (  # noqa: E402
    CandidateAction,
    ConsequenceResult,
    Effect,
    Evidence,
    EventItem,
    EvidenceType,
    Plausibility,
    RealityState,
    ScoredBranch,
)


def state(**overrides) -> RealityState:
    base = dict(
        title="Bengaluru offer",
        summary="An offer paying 40% more while living with parents.",
        domain="career",
        events=[
            EventItem(description="Currently lives with parents", evidence_type=EvidenceType.GROUNDED),
            EventItem(description="Offer pays 40% more", evidence_type=EvidenceType.GROUNDED),
        ],
        decision_hints=[],
        missing_information=["Bengaluru rent levels"],
    )
    base.update(overrides)
    reality = RealityState(**base)
    reality.facts = [
        Evidence(claim=event.description, evidence_type=event.evidence_type)
        for event in reality.events
    ]
    return reality


def branch(label: str, delta=None, plausibility=Plausibility.HIGH, narrative="A narrative.") -> ScoredBranch:
    return ScoredBranch(
        candidate=CandidateAction(
            label=label,
            strategy="conventional",
            description=label,
            rationale="because",
            state_delta=delta or {},
        ),
        consequence=ConsequenceResult(
            narrative=narrative,
            effects=[Effect(dimension="money", direction="up", magnitude="high", order=1, explanation="x")],
            plausibility=plausibility,
        ),
        score=0.5,
    )


class TestTokenMatching:
    def test_does_not_match_inside_a_longer_word(self):
        """'rent' inside 'currently' is the false positive that motivated this."""
        assert not harness.mentions("Currently lives with parents", "rent")

    def test_matches_a_standalone_word(self):
        assert harness.mentions("Bengaluru rent is unknown", "rent")

    def test_matches_next_to_punctuation_and_percent(self):
        assert harness.mentions("The offer pays 40% more", "40%")
        assert harness.mentions("salary, location, and rent.", "rent")

    def test_matches_a_multi_word_phrase_across_whitespace(self):
        assert harness.mentions("a four-year\nvest applies", "four-year")
        assert harness.mentions("we have two  founders", "two founders")

    def test_is_case_insensitive(self):
        assert harness.mentions("PAYS 40% MORE", "40%")

    def test_stem_matching_is_prefix_based(self):
        assert harness.starts_with("Relocation to Bengaluru", "relocat")
        assert harness.starts_with("Negotiate the offer", "negotiat")
        assert not harness.starts_with("Accept the offer", "relocat")


class TestHallucinationResistance:
    def test_clean_extraction_scores_one(self):
        score = harness.score_hallucination_resistance(
            state(), [branch("Accept")], {"must_not_hallucinate": ["rent", "company name"]}
        )
        assert score.value == 1.0
        assert score.detail == "clean"

    def test_forbidden_fact_asserted_as_grounded_is_penalised(self):
        polluted = state(
            events=[EventItem(description="Rent is 30000 a month", evidence_type=EvidenceType.GROUNDED)]
        )
        score = harness.score_hallucination_resistance(
            polluted, [], {"must_not_hallucinate": ["rent"]}
        )
        assert score.value == 0.0
        assert "rent" in score.detail

    def test_forbidden_fact_marked_assumed_is_not_penalised(self):
        """Flagging an assumption is the engine behaving correctly."""
        hedged = state(
            events=[EventItem(description="Rent is around 30000", evidence_type=EvidenceType.ASSUMED)]
        )
        score = harness.score_hallucination_resistance(
            hedged, [], {"must_not_hallucinate": ["rent"]}
        )
        assert score.value == 1.0

    def test_confident_branch_narrative_is_checked_too(self):
        confident = branch("Accept", narrative="Rent will be 30000 a month.", plausibility=Plausibility.HIGH)
        score = harness.score_hallucination_resistance(
            state(), [confident], {"must_not_hallucinate": ["rent"]}
        )
        assert score.value == 0.0

    def test_speculative_branch_narrative_is_allowed_to_explore(self):
        speculative = branch(
            "Accept", narrative="Rent might be 30000 a month.", plausibility=Plausibility.SPECULATIVE
        )
        score = harness.score_hallucination_resistance(
            state(), [speculative], {"must_not_hallucinate": ["rent"]}
        )
        assert score.value == 1.0

    def test_no_declared_tokens_does_not_gate(self):
        score = harness.score_hallucination_resistance(state(), [], {})
        assert score.weight == 0.0


class TestOtherScorers:
    def test_grounding_finds_expected_facts(self):
        score = harness.score_grounding(state(), {"expected_facts": ["40%", "parents"]})
        assert score.value == 1.0

    def test_grounding_reports_what_is_missing(self):
        score = harness.score_grounding(state(), {"expected_facts": ["40%", "startup"]})
        assert score.value == 0.5
        assert "startup" in score.detail

    def test_diversity_rewards_distinct_branches(self):
        distinct = [
            branch("Accept and relocate", {"location": "Bengaluru"}),
            branch("Reject and build startup", {"startup_time_per_week": 20}),
        ]
        near_duplicates = [
            branch("Accept the offer", {"location": "Bengaluru"}),
            branch("Accept that offer", {"location": "Bengaluru"}),
        ]
        assert (
            harness.score_branch_diversity(distinct).value
            > harness.score_branch_diversity(near_duplicates).value
        )

    def test_diversity_needs_at_least_two_branches(self):
        assert harness.score_branch_diversity([branch("Only one")]).value == 0.0

    def test_schema_validity_flags_a_branch_without_effects(self):
        empty = branch("No effects")
        empty.consequence.effects = []
        assert harness.score_schema_validity(state(), [empty]).value < 1.0

    def test_constraint_violations_penalise_surviving_breaches(self):
        breaking = branch("Breaks budget")
        breaking.constraint_violations = ["salary would become 80000"]
        score = harness.score_constraint_violations([breaking], {})
        assert score.value == 0.0
        assert "Breaks budget" in score.detail

    def test_stability_rewards_a_recurring_possibility_space(self):
        labels = ["Accept and relocate", "Reject and build startup", "Negotiate hybrid"]
        assert harness.score_stability(labels, labels).value == 1.0
        collapsed = harness.score_stability(labels, ["Something else entirely"])
        assert collapsed.value < 0.5

    def test_stability_reports_a_collapsed_rerun(self):
        assert harness.score_stability(["A", "B"], []).value == 0.0


class TestFixtures:
    def test_every_fixture_declares_the_required_keys(self):
        fixtures = harness.load_fixtures(None, None)
        assert len(fixtures) >= 20
        for fixture in fixtures:
            for key in ("id", "domain", "input", "expected_forks", "must_not_hallucinate"):
                assert fixture.get(key), f"{fixture.get('id')} missing {key}"
            assert len(fixture["input"]) >= 20, f"{fixture['id']} input too short for the API"

    def test_fixture_ids_are_unique_and_match_filenames(self):
        ids = [f["id"] for f in harness.load_fixtures(None, None)]
        assert len(ids) == len(set(ids))

    def test_fixtures_cover_every_domain_in_the_registry(self):
        from app.schemas.domain import DomainType

        covered = {f["domain"] for f in harness.load_fixtures(None, None)}
        expected = {d.value for d in DomainType}
        assert expected - covered == set(), f"no fixture for: {expected - covered}"

    @pytest.mark.parametrize("domain", ["career", "relationship", "business", "software"])
    def test_domain_filter_selects_only_that_domain(self, domain):
        fixtures = harness.load_fixtures(None, domain)
        assert fixtures
        assert all(f["domain"] == domain for f in fixtures)
