"""Canned stage responses for the flagship Bengaluru scenario.

Single source of truth for the MockProvider used in tests and in
LLM_PROVIDER=mock mode. These are DEMO data, not application logic.
"""

DEMO_RESPONSES: dict[str, dict] = {
    "reality_extraction": {
        "title": "Bengaluru job offer vs current life",
        "domain": "career",
        "summary": (
            "User has a Bengaluru job offer paying 40% more while living comfortably "
            "with parents, in a relationship, and holding a startup ambition."
        ),
        "actors": ["user", "partner", "current employer", "offering company"],
        "entities": ["bengaluru_job_offer", "current_job", "startup_project"],
        "events": [
            {
                "description": "Received a job offer in Bengaluru paying 40% more",
                "timestamp": None,
                "evidence_type": "grounded",
            },
            {
                "description": "Currently lives with parents",
                "timestamp": None,
                "evidence_type": "grounded",
            },
            {
                "description": "In an active relationship in the current city",
                "timestamp": None,
                "evidence_type": "grounded",
            },
            {
                "description": "Comfortable and stable in current job",
                "timestamp": None,
                "evidence_type": "grounded",
            },
        ],
        "decision_hints": [
            {
                "question": "Accept, reject, negotiate, or delay the Bengaluru offer?",
                "options_hint": ["accept", "reject", "negotiate", "delay", "remote"],
                "importance": 0.9,
            }
        ],
        "constraints": [
            {"description": "Family proximity is important to the user", "kind": "relationship", "key": None, "operator": None, "value": None},
            {"description": "Limited time available for startup work", "kind": "time", "key": "startup_time_per_week", "operator": ">=", "value": 8},
            {"description": "Monthly discretionary budget of about ₹30k", "kind": "financial", "key": "monthly_discretionary_budget", "operator": "<=", "value": 30000},
        ],
        "goals": ["Build a startup eventually", "Grow career without losing family proximity"],
        "relationships": ["Active romantic relationship in current city"],
        "resources": ["Stable salary", "Low living costs with parents"],
        "beliefs": ["Startup ambition matters for long-term identity"],
        "uncertainties": ["Whether remote work is negotiable", "Relocation costs in Bengaluru"],
        "missing_information": ["Bengaluru rent levels", "Partner's willingness to relocate", "Offer role details"],
    },
    "fork_detection": {
        "forks": [
            {
                "id": "offer_decision",
                "description": "The Bengaluru offer requires a yes/no/negotiate/delay decision",
                "question": "What to do with the Bengaluru offer?",
                "options_hint": ["accept", "reject", "negotiate", "delay", "remote trial"],
                "importance": 0.95,
            }
        ]
    },
    "candidate_generation": {
        "candidates": [
            {
                "label": "Accept and relocate",
                "strategy": "conventional",
                "description": "Take the Bengaluru job and move; partner relationship becomes long-distance.",
                "rationale": "Directly captures the +40% salary and new network.",
                "reversible": False,
                "state_delta": {"location": "Bengaluru", "salary": 112000, "family_proximity": -0.7},
            },
            {
                "label": "Reject and build startup",
                "strategy": "contrarian",
                "description": "Stay put, keep current comfort, invest evenings/weekends fully in the startup.",
                "rationale": "Preserves family proximity and startup time at the cost of income growth.",
                "reversible": True,
                "state_delta": {"startup_time_per_week": 20, "salary": 80000},
            },
            {
                "label": "Negotiate hybrid arrangement",
                "strategy": "hybrid",
                "description": "Ask for 2 days/week in Bengaluru before accepting.",
                "rationale": "Captures most of the raise while keeping family proximity partially.",
                "reversible": True,
                "state_delta": {"remote_ratio": 0.6, "salary": 106000},
            },
            {
                "label": "Delay decision one month",
                "strategy": "conservative",
                "description": "Ask for four weeks to decide while testing the market.",
                "rationale": "Buys information at low cost; risk that the offer expires.",
                "reversible": True,
                "state_delta": {},
            },
            {
                "label": "Six-month relocation trial",
                "strategy": "blind_spot",
                "description": "Accept with an explicit internal agreement to reassess after six months.",
                "rationale": "Reversible acceptance: real information about Bengaluru life before permanent commitment.",
                "reversible": True,
                "state_delta": {"location": "Bengaluru (trial)", "salary": 112000, "family_proximity": -0.5},
            },
            {
                "label": "Accept, protect startup hours",
                "strategy": "opportunistic",
                "description": "Move but contractually guard two evenings plus weekends for the startup.",
                "rationale": "Attempts both income upside and startup progress; high energy cost.",
                "reversible": True,
                "state_delta": {"location": "Bengaluru", "salary": 112000, "startup_time_per_week": 10, "free_time": -0.6},
            },
        ]
    },
    "consequence_generation": {
        "narrative": (
            "Month 1: relocation and onboarding absorb most energy. Month 3: new "
            "professional network begins forming. Month 6: savings rate improves; "
            "weekend startup hours shrink under workload. Year 1: stronger career "
            "trajectory; startup progress slower; relationship survives only with "
            "deliberate contact rhythms."
        ),
        "effects": [
            {"dimension": "career", "direction": "up", "magnitude": "high", "order": 1, "explanation": "New market and role compound the existing trajectory."},
            {"dimension": "money", "direction": "up", "magnitude": "medium", "order": 1, "explanation": "+40% salary partly offset by Bengaluru living costs."},
            {"dimension": "family_proximity", "direction": "down", "magnitude": "high", "order": 1, "explanation": "Distance from parents and partner increases sharply."},
            {"dimension": "startup_capacity", "direction": "down", "magnitude": "medium", "order": 2, "explanation": "Commute and onboarding reduce weekly startup hours, slowing momentum built earlier."},
        ],
        "assumptions": [
            {"claim": "Job remains stable for at least a year", "depends_on": ["offering_company_performance"]},
            {"claim": "Long-distance relationship withstands reduced contact", "depends_on": ["partner_commitment"]},
            {"claim": "Relocation costs fit within budget", "depends_on": ["bengaluru_rent"]},
        ],
        "plausibility": "high",
        "plausibility_reasons": [
            "Consistent with stated constraints",
            "Requires no major external event",
            "Follows from existing trajectory",
        ],
        "risks": ["Offer role may demand more than standard hours", "Relationship strain if visits are infrequent"],
    },
    "critic_review": {
        "reviews": [
            {"label": "Accept and relocate", "verdict": "pass", "issues": [], "unsupported_claims": []},
            {
                "label": "Reject and build startup",
                "verdict": "revise",
                "issues": ["Assumes startup progress converts to income within the horizon"],
                "unsupported_claims": ["Implied startup revenue timeline"],
            },
            {"label": "Negotiate hybrid arrangement", "verdict": "pass", "issues": [], "unsupported_claims": []},
            {"label": "Delay decision one month", "verdict": "pass", "issues": [], "unsupported_claims": []},
            {"label": "Six-month relocation trial", "verdict": "pass", "issues": [], "unsupported_claims": []},
            {"label": "Accept, protect startup hours", "verdict": "pass", "issues": [], "unsupported_claims": []},
        ]
    },
    # The critic flags "Reject and build startup" for an unsupported revenue
    # timeline, so the demo exercises one real revise iteration. The replacement
    # keeps the same strategic move with the income claim removed.
    "candidate_revision": {
        "candidates": [
            {
                "label": "Reject, fund startup runway",
                "strategy": "contrarian",
                "description": (
                    "Stay in the current role and treat it as the funding source for "
                    "startup hours, with no assumption about when the startup earns."
                ),
                "rationale": (
                    "Preserves family proximity and startup time. Makes no claim about "
                    "startup revenue; the current salary is the only stated income."
                ),
                "reversible": True,
                "state_delta": {"startup_time_per_week": 20, "savings_capacity": 0.15},
            }
        ]
    },
}
