"""Offline Task 99 cases and production-contract adapters; no live calls."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue, model_validator
from pydantic_evals import Case, Dataset

from app.agents.contracts import (
    ComparisonDecisionAgentInput,
    SellerListingTrustAgentInput,
    ShoppingScopeGuardrailInput,
    VerificationAgentInput,
    VerificationReport,
)
from app.agents.live_comparison_decision import (
    LiveComparisonDecisionAgent,
    MockComparisonDecisionModelRunner,
)
from app.agents.live_guardrails import (
    LiveShoppingScopeGuardrail,
    MockShoppingGuardrailModelRunner,
)
from app.agents.live_seller_listing_trust import (
    LiveSellerListingTrustAgent,
    MockSellerListingTrustModelRunner,
)
from app.agents.live_verifier_critic import (
    LiveVerifierCriticAgent,
    MockVerifierCriticModelRunner,
)
from app.core.settings import Settings
from app.evals.schemas import EvalMetadata, LocalEvalCase
from app.schemas.analysis import ListingTrustAssessment, RecommendationBundle
from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.guided_intake import ShoppingGuardrailResult
from app.schemas.products import ProductListing
from app.services.listing_trust import (
    ListingTrustRuleContext,
    PricePlausibilityFinding,
    assess_listing_trust,
    compare_price_plausibility,
    price_plausibility_contexts,
)
from app.services.recommendation_trust import (
    integrate_trust_analysis_into_recommendation,
)

CORPUS_PATH = Path(__file__).parent / "fixtures" / "trust_recommendation.json"
Failure = Literal["timeout", "invalid"]


class GuardrailFixture(CartCartBaseModel):
    request: ShoppingScopeGuardrailInput
    model_output: ShoppingGuardrailResult | None = None
    failure: Failure | None = None


class TrustFixture(CartCartBaseModel):
    request: SellerListingTrustAgentInput
    context: ListingTrustRuleContext = Field(default_factory=ListingTrustRuleContext)
    price_peers: tuple[ProductListing, ...] = ()
    model_output: ListingTrustAssessment | None = None
    failure: Failure | None = None

    @model_validator(mode="after")
    def _validate_context(self) -> "TrustFixture":
        if self.request.rule_based_assessment is not None:
            raise ValueError(
                "Compute the rule baseline from the listing/context, not a recorded answer."
            )
        listings = (self.request.listing, *self.price_peers)
        if len({v.listing_id for v in listings}) != len(listings):
            raise ValueError("Price peers must have unique listing IDs.")
        if any(v.product_id != listings[0].product_id for v in self.price_peers):
            raise ValueError("This lane compares offers of the same canonical product.")
        known = {s for v in listings for s in v.source_ids}
        known.update(e.evidence_id for e in self.request.evidence)
        known.update(e.source_id for e in self.request.evidence)
        if not set((*self.context.evidence_ids, *self.context.source_ids)).issubset(
            known
        ):
            raise ValueError("Trust context cites unknown fixture evidence/sources.")
        return self


class RecommendationFixture(CartCartBaseModel):
    request: ComparisonDecisionAgentInput
    failure: Failure | None = None


class VerificationFixture(CartCartBaseModel):
    request: VerificationAgentInput
    failure: Failure | None = None


class TrustRecommendationInput(VersionedSchema):
    stage: Literal["guardrail", "trust", "recommendation", "verification"]
    guardrail: GuardrailFixture | None = None
    trust: TrustFixture | None = None
    recommendation: RecommendationFixture | None = None
    verification: VerificationFixture | None = None

    @model_validator(mode="after")
    def _selected_stage_only(self) -> "TrustRecommendationInput":
        if tuple(getattr(self, name) is not None for name in STAGES) != tuple(
            self.stage == name for name in STAGES
        ):
            raise ValueError("Exactly the selected stage's fixture is required.")
        fixture = getattr(self, self.stage)
        if getattr(fixture, "failure", None) and getattr(fixture, "model_output", None):
            raise ValueError("Choose a response or a failure, not both.")
        if self.stage in {"recommendation", "verification"}:
            _validate_candidate_references(fixture.request)
        return self


STAGES = ("guardrail", "trust", "recommendation", "verification")


def _validate_candidate_references(
    request: ComparisonDecisionAgentInput | VerificationAgentInput,
) -> None:
    products = {p.product_id for p in request.products}
    listings = {v.listing_id: v for v in request.listings}
    evidence = {e.evidence_id for e in request.evidence}
    sources = {e.source_id for e in request.evidence}
    if (
        len(products) != len(request.products)
        or len(listings) != len(request.listings)
        or len(evidence) != len(request.evidence)
    ):
        raise ValueError("Candidate, listing and evidence IDs must be unique.")
    for product in request.products:
        if not set(product.source_ids).issubset(sources) or set(
            product.listing_ids
        ) != {
            v.listing_id
            for v in listings.values()
            if v.product_id == product.product_id
        }:
            raise ValueError(
                "Products must retain their supplied sources and exact listing membership."
            )
    for listing in request.listings:
        if listing.product_id not in products or not set(
            (*listing.source_ids, *listing.seller.source_ids)
        ).issubset(sources):
            raise ValueError("Listing references unknown fixture product/source.")
    for item in request.evidence:
        if item.target.product_id and item.target.product_id not in products:
            raise ValueError("Evidence targets an unknown product.")
        if item.target.listing_id and item.target.listing_id not in listings:
            raise ValueError("Evidence targets an unknown listing.")
        if (
            item.target.product_id
            and item.target.listing_id
            and listings[item.target.listing_id].product_id != item.target.product_id
        ):
            raise ValueError("Evidence product/listing identity differs.")
    for analysis in request.category_analyses:
        if (
            analysis.product_id not in products
            or not set(analysis.evidence_ids).issubset(evidence)
            or not set(analysis.source_ids).issubset(sources)
            or any(
                i not in listings or listings[i].product_id != analysis.product_id
                for i in analysis.listing_ids
            )
        ):
            raise ValueError(
                "Analysis references unknown or mismatched fixture entities/evidence."
            )
    for assessment in request.trust_assessments:
        if (
            assessment.listing_id not in listings
            or not set(assessment.evidence_ids).issubset(evidence)
            or not set(assessment.source_ids).issubset(sources)
        ):
            raise ValueError("Assessment references unknown fixture listing/evidence.")


class TrustRecommendationRule(CartCartBaseModel):
    field: str = Field(
        pattern=r"^(guardrail|trust|price_findings|recommendation|verification|runtime_status|model_calls)(\.(\w+|\*))*$"
    )
    operator: Literal["equals", "set_equals", "contains_text", "count"] = "equals"
    value: JsonValue
    requirement: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _operand(self) -> "TrustRecommendationRule":
        if self.operator == "set_equals" and (
            not isinstance(self.value, list)
            or any(isinstance(v, (list, dict)) for v in self.value)
        ):
            raise ValueError("set_equals needs scalar list values.")
        if self.operator == "contains_text" and (
            not isinstance(self.value, str) or not self.value.strip()
        ):
            raise ValueError("contains_text needs nonempty text.")
        if self.operator == "count" and (type(self.value) is not int or self.value < 0):
            raise ValueError("count needs a nonnegative integer.")
        return self


class TrustRecommendationExpectation(CartCartBaseModel):
    fields: tuple[TrustRecommendationRule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_rules(self) -> "TrustRecommendationExpectation":
        keys = [(r.field, r.operator, str(r.value)) for r in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate expectation rule.")
        return self


class TrustRecommendationOutput(VersionedSchema):
    guardrail: ShoppingGuardrailResult | None = None
    trust: ListingTrustAssessment | None = None
    price_findings: tuple[PricePlausibilityFinding, ...] = ()
    recommendation: RecommendationBundle | None = None
    verification: VerificationReport | None = None
    runtime_status: str
    model_calls: int = Field(ge=0)


TrustRecommendationResult = TrustRecommendationOutput | TrustRecommendationExpectation


class TrustRecommendationCorpus(VersionedSchema):
    provenance: Literal["synthetic"]
    cases: tuple[
        LocalEvalCase[TrustRecommendationInput, TrustRecommendationExpectation], ...
    ] = Field(min_length=1)


def _fixed_fixture(raw: object, value: object) -> None:
    if isinstance(value, BaseModel) and isinstance(raw, dict):
        if isinstance(value, VersionedSchema) and value.schema_version != 1:
            raise ValueError("Unsupported fixture schema version.")
        for name in type(value).model_fields:
            child = getattr(value, name)
            if (
                name
                in {
                    "run_id",
                    "source_id",
                    "evidence_id",
                    "product_id",
                    "listing_id",
                    "candidate_id",
                    "decision_id",
                    "bundle_id",
                    "captured_at",
                    "created_at",
                    "assessed_at",
                }
                and child is not None
                and raw.get(name) is None
            ):
                raise ValueError(f"Fixture {name} must be fixed explicitly.")
            if name in raw:
                _fixed_fixture(raw[name], child)
    elif isinstance(value, (tuple, list)) and isinstance(raw, list):
        for r, v in zip(raw, value, strict=True):
            _fixed_fixture(r, v)


def trust_recommendation_cases(
    path: Path = CORPUS_PATH,
) -> tuple[
    LocalEvalCase[TrustRecommendationInput, TrustRecommendationExpectation], ...
]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    corpus = TrustRecommendationCorpus.model_validate(raw)
    _fixed_fixture(raw, corpus)
    if len({c.name for c in corpus.cases}) != len(corpus.cases):
        raise ValueError("Case names must be unique.")
    for case in corpus.cases:
        roots = {case.inputs.stage, "runtime_status", "model_calls"}
        if case.inputs.stage == "trust":
            roots.add("price_findings")
        if any(r.field.split(".")[0] not in roots for r in case.expected_output.fields):
            raise ValueError("Criteria must address the selected stage.")
        if not any(
            r.field.split(".")[0] == case.inputs.stage
            for r in case.expected_output.fields
        ):
            raise ValueError(
                "Cases need behavioral criteria, not only execution metadata."
            )
    return corpus.cases


def trust_recommendation_dataset() -> Dataset[
    TrustRecommendationInput, TrustRecommendationResult, EvalMetadata
]:
    from app.evals.trust_recommendation_scoring import TrustRecommendationEvaluator

    return Dataset(
        name="cartcart-trust-recommendation",
        cases=[
            Case[TrustRecommendationInput, TrustRecommendationResult, EvalMetadata](
                name=c.name,
                inputs=c.inputs,
                expected_output=c.expected_output,
                metadata=c.metadata,
            )
            for c in trust_recommendation_cases()
        ],
        evaluators=[TrustRecommendationEvaluator()],
    )


def _runner_kwargs(fixture: object) -> dict[str, Any]:
    failure = getattr(fixture, "failure", None)
    if failure == "timeout":
        return {"error": TimeoutError("Synthetic eval timeout.")}
    if failure == "invalid":
        return {"output": {"invalid_fixture_output": True}}
    return {"output": getattr(fixture, "model_output", None)}


@dataclass
class TrustRecommendationTask:
    settings: Settings

    async def __call__(
        self, inputs: TrustRecommendationInput
    ) -> TrustRecommendationOutput:
        inputs = inputs.model_copy(deep=True)
        fixture = getattr(inputs, inputs.stage)
        kwargs = _runner_kwargs(fixture)
        if inputs.guardrail is not None:
            guardrail_runner = MockShoppingGuardrailModelRunner(**kwargs)
            guardrail_agent = LiveShoppingScopeGuardrail(
                self.settings, model_runner=guardrail_runner
            )
            guardrail_result = await guardrail_agent.run(fixture.request)
            return TrustRecommendationOutput(
                guardrail=guardrail_result,
                runtime_status=guardrail_agent.workbench_activity[0]["status"],
                model_calls=guardrail_runner.calls,
            )
        if inputs.trust is not None:
            listings = (fixture.request.listing, *fixture.price_peers)
            contexts = price_plausibility_contexts(
                (listings,), {listings[0].listing_id: fixture.context}
            )
            baseline = assess_listing_trust(
                listings[0], contexts.get(listings[0].listing_id)
            )
            request = fixture.request.model_copy(
                update={"rule_based_assessment": baseline}
            )
            trust_runner = MockSellerListingTrustModelRunner(**kwargs)
            trust_agent = LiveSellerListingTrustAgent(
                self.settings, model_runner=trust_runner
            )
            trust_result = await trust_agent.run(request)
            return TrustRecommendationOutput(
                trust=trust_result,
                price_findings=compare_price_plausibility((listings,)),
                runtime_status=trust_agent.workbench_activity[0]["status"],
                model_calls=trust_runner.calls,
            )
        if inputs.recommendation is not None:
            decision_runner = MockComparisonDecisionModelRunner(**kwargs)
            decision_agent = LiveComparisonDecisionAgent(
                self.settings, model_runner=decision_runner
            )
            decision_result = await decision_agent.run(fixture.request)
            decision_result = integrate_trust_analysis_into_recommendation(
                decision_result, fixture.request.trust_assessments
            )
            return TrustRecommendationOutput(
                recommendation=decision_result,
                runtime_status=decision_agent.workbench_activity[0]["status"],
                model_calls=decision_runner.calls,
            )
        verification_runner = MockVerifierCriticModelRunner(**kwargs)
        verification_agent = LiveVerifierCriticAgent(
            self.settings, model_runner=verification_runner
        )
        verification_result = await verification_agent.run(fixture.request)
        return TrustRecommendationOutput(
            verification=verification_result,
            runtime_status=verification_agent.workbench_activity[0]["status"],
            model_calls=verification_runner.calls,
        )


def offline_trust_recommendation_task() -> TrustRecommendationTask:
    settings = Settings(
        _env_file=None,
        environment="test",
        live_agents_enabled=False,
        openai_api_key=None,
        openai_model="eval-mock-model",
        openai_run_profiles={},
        openai_agent_overrides={},
        openai_agent_tracing_enabled=False,
    )  # type: ignore[call-arg]
    return TrustRecommendationTask(settings)
