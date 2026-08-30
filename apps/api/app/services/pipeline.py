import json
import time
from dataclasses import dataclass, field
from uuid import UUID

from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.domains.registry import DomainModule, get_domain_module
from app.engines.constraint_engine import evaluate_constraints
from app.engines.graph_builder import build_graph
from app.engines.scoring import rank_and_prune
from app.llm.base import LLMProvider
from app.llm.prompt_registry import PromptRegistry, get_prompt_registry
from app.schemas.domain import (
    BranchReview,
    CandidateAction,
    ConsequenceResult,
    DomainType,
    Evidence,
    EvidenceType,
    ForkPoint,
    Plausibility,
    RealityState,
)
from app.schemas.possibility import (
    ForkPoint,
    PossibilityGraph,
    RealityExtractionOutput,
)


@dataclass
class ExecutionRecord:
    stage: str
    provider: str
    model: str
    prompt_name: str = ""
    prompt_version: str = ""
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    retry_count: int = 0
    success: bool = True
    error: str | None = None


@dataclass
class PipelineOutcome:
    graph: PossibilityGraph
    branches: list  # list[ScoredBranch]
    fork: ForkPoint
    executions: list[ExecutionRecord] = field(default_factory=list)


class PossibilityPipeline:
    """Orchestrates the generate -> verify -> critique -> prune loop.

    Every LLM call goes through _run_stage so prompt version and token usage
    are captured for observability regardless of provider.
    """

    def __init__(
        self,
        provider: LLMProvider,
        prompts: PromptRegistry | None = None,
        settings: Settings | None = None,
    ):
        self.provider = provider
        self.prompts = prompts or get_prompt_registry()
        self.settings = settings or get_settings()
        self.executions: list[ExecutionRecord] = []

    def _record(self, record: ExecutionRecord) -> None:
        self.executions.append(record)

    async def _run_stage(
        self,
        stage: str,
        prompt_name: str,
        schema: type[BaseModel],
        temperature: float,
        **variables: str,
    ) -> BaseModel:
        system_prompt, pname, pversion = self.prompts.render(prompt_name, **variables)
        try:
            result = await self.provider.generate_structured(
                system_prompt=system_prompt,
                user_prompt="Produce the required JSON now.",
                schema=schema,
                stage=stage,
                temperature=temperature,
            )
        except Exception as exc:
            self._record(
                ExecutionRecord(
                    stage=stage,
                    provider=type(self.provider).__name__,
                    model=getattr(self.provider, "model", "unknown"),
                    prompt_name=pname,
                    prompt_version=pversion,
                    success=False,
                    error=str(exc)[:500],
                )
            )
            raise

        usage = result.usage
        self._record(
            ExecutionRecord(
                stage=stage,
                provider=type(self.provider).__name__,
                model=result.model,
                prompt_name=pname,
                prompt_version=pversion,
                latency_ms=result.latency_ms,
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                retry_count=result.retries,
            )
        )
        return result.data

    async def extract_reality(
        self, raw_input: str, domain_hint: "DomainType | None" = None
    ) -> RealityState:
        if domain_hint is not None:
            hint = (
                f"The user pre-selected the domain '{domain_hint.value}'. Use this "
                "domain unless the situation clearly does not match it."
            )
        else:
            hint = "No domain preference given; classify from the situation."
        output: RealityExtractionOutput = await self._run_stage(
            stage="reality_extraction",
            prompt_name="reality_extraction",
            schema=RealityExtractionOutput,
            temperature=self.settings.llm_temperature_extraction,
            input=raw_input,
            domain_hint=hint,
        )
        state = RealityState(**output.model_dump())
        if domain_hint is not None:
            state.domain = domain_hint
        state.facts = [
            Evidence(
                claim=event.description,
                evidence_type=event.evidence_type,
                source="user_input",
                confidence=1.0 if event.evidence_type == EvidenceType.GROUNDED else 0.7,
            )
            for event in state.events
        ]
        return state

    async def detect_forks(self, state: RealityState) -> list[ForkPoint]:
        from app.schemas.domain import ForkPoint as ForkModel

        class ForkDetection(BaseModel):
            forks: list[ForkModel]

        detection: ForkDetection = await self._run_stage(
            stage="fork_detection",
            prompt_name="fork_detection",
            schema=ForkDetection,
            temperature=self.settings.llm_temperature_generation,
            reality=state.to_prompt_context(),
        )

        module = get_domain_module(state.domain)
        seen_questions = {f.question.strip().lower() for f in detection.forks}
        merged = list(detection.forks)
        for canonical in module.canonical_forks:
            if canonical.question.strip().lower() not in seen_questions and len(merged) < 5:
                merged.append(canonical)
        return merged

    async def generate_candidates(
        self,
        state: RealityState,
        fork: ForkPoint,
        domain: DomainModule,
    ) -> list[CandidateAction]:
        from app.schemas.domain import CandidateAction as Candidate

        class CandidateSet(BaseModel):
            candidates: list[Candidate]

        hard_rules = "\n".join(f"- {rule}" for rule in domain.hard_rules) or "- none"
        candidate_set: CandidateSet = await self._run_stage(
            stage="candidate_generation",
            prompt_name="candidate_generation",
            schema=CandidateSet,
            temperature=self.settings.llm_temperature_generation,
            reality=state.to_prompt_context(),
            fork_json=fork.model_dump_json(indent=2),
            allowed_variables=", ".join(domain.variables),
            hard_rules=hard_rules,
            domain_guidance=domain.prompt_addendum or "No domain-specific guidance.",
        )
        if len(candidate_set.candidates) < self.settings.engine_min_candidates:
            raise ValueError(
                f"candidate generation produced {len(candidate_set.candidates)} branches, "
                f"minimum is {self.settings.engine_min_candidates}"
            )
        return candidate_set.candidates

    async def generate_consequence(
        self,
        state: RealityState,
        fork: ForkPoint,
        candidate: CandidateAction,
        domain: DomainModule,
    ) -> ConsequenceResult:
        dimensions = ", ".join(domain.dimensions)
        hard_rules = "\n".join(f"- {rule}" for rule in domain.hard_rules) or "- none"
        return await self._run_stage(  # type: ignore[return-value]
            stage="consequence_generation",
            prompt_name="consequence_generation",
            schema=ConsequenceResult,
            temperature=self.settings.llm_temperature_generation,
            reality=state.to_prompt_context(),
            fork_json=fork.model_dump_json(),
            candidate_json=candidate.model_dump_json(indent=2),
            dimensions=dimensions,
            hard_rules=hard_rules,
            max_causal_depth=str(self.settings.engine_max_causal_depth),
            domain_guidance=domain.prompt_addendum or "No domain-specific guidance.",
        )

    async def revise_candidates(
        self,
        state: RealityState,
        fork: ForkPoint,
        domain: DomainModule,
        failing: list[dict],
        passing_labels: list[str],
    ) -> list[CandidateAction]:
        """Regenerate only the branches that failed review or validation.

        `failing` entries carry the candidate plus the reasons it failed, so the
        model repairs a specific defect instead of resampling blindly.
        """
        from app.schemas.domain import CandidateAction as Candidate

        class CandidateSet(BaseModel):
            candidates: list[Candidate]

        hard_rules = "\n".join(f"- {rule}" for rule in domain.hard_rules) or "- none"
        revised: CandidateSet = await self._run_stage(
            stage="candidate_revision",
            prompt_name="candidate_revision",
            schema=CandidateSet,
            temperature=self.settings.llm_temperature_generation,
            reality=state.to_prompt_context(),
            fork_json=fork.model_dump_json(indent=2),
            allowed_variables=", ".join(domain.variables),
            hard_rules=hard_rules,
            failing_json=json.dumps(failing, indent=2, default=str),
            passing_labels="\n".join(f"- {label}" for label in passing_labels) or "- none",
        )
        return revised.candidates

    async def critique_branches(
        self,
        state: RealityState,
        candidates: list[CandidateAction],
    ) -> dict[str, BranchReview]:
        from app.schemas.domain import BranchReview as Review

        class CriticResult(BaseModel):
            reviews: list[Review]

        branches_payload = json.dumps(
            [{"label": c.label, "description": c.description, "rationale": c.rationale} for c in candidates],
            indent=2,
        )
        critic: CriticResult = await self._run_stage(
            stage="critic_review",
            prompt_name="critic_review",
            schema=CriticResult,
            temperature=self.settings.llm_temperature_extraction,
            reality=state.to_prompt_context(),
            branches_json=branches_payload,
        )
        return {review.label: review for review in critic.reviews}

    async def run(self, scenario_id: UUID, state: RealityState) -> PipelineOutcome:
        started = time.perf_counter()
        domain = get_domain_module(state.domain)

        forks = await self.detect_forks(state)
        if not forks:
            raise ValueError("no fork points identified")
        primary_fork = max(forks, key=lambda f: f.importance)

        candidates = await self.generate_candidates(state, primary_fork, domain)

        consequences: dict[str, ConsequenceResult] = {}
        for candidate in candidates:
            consequences[candidate.label] = await self.generate_consequence(
                state, primary_fork, candidate, domain
            )

        reviews = await self.critique_branches(state, candidates)

        scored = []
        for candidate in candidates:
            consequence = consequences[candidate.label]
            review = reviews.get(candidate.label)
            violations = evaluate_constraints(state, candidate)

            verdict = review.verdict if review else "pass"
            if verdict == "reject" or violations:
                continue

            from app.schemas.domain import ScoredBranch

            scored.append(
                ScoredBranch(
                    candidate=candidate,
                    consequence=consequence,
                    review=review,
                    constraint_violations=violations,
                )
            )

        surviving = rank_and_prune(
            scored,
            domain,
            beam_width=self.settings.engine_beam_width,
            dedup_threshold=self.settings.engine_dedup_threshold,
        )
        if not surviving:
            raise ValueError("all candidate branches were rejected by validation")

        graph = build_graph(
            scenario_id=scenario_id,
            reality_summary=state.summary,
            fork_question=primary_fork.question,
            fork_description=primary_fork.description,
            branches=surviving,
            reality_state=state,
            secondary_forks=[f for f in forks if f.id != primary_fork.id],
        )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self.executions.append(
            ExecutionRecord(
                stage="graph_assembly",
                provider="engine",
                model="deterministic",
                latency_ms=elapsed_ms,
            )
        )
        return PipelineOutcome(graph=graph, branches=surviving, fork=primary_fork, executions=self.executions)
