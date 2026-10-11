from dataclasses import dataclass
from typing import Any

import pytest
from agents import Agent, RunConfig

from app.agents import (
    LiveVerifierCriticAgent,
    MockVerifierCriticModelRunner,
    VerificationAgentInput,
    VerificationReport,
)
from app.agents.context_management import ContextBudgetExceeded
from app.core.settings import Settings
from app.schemas.analysis import (
    CategoryAnalysis,
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    ListingTrustAssessment,
    ListingTrustLevel,
    RecommendationBundle,
    RecommendationMode,
    RecommendationModeResult,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.schemas.intake import (
    BudgetConstraint,
    BudgetMode,
    FieldSource,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.money import Money
from app.schemas.products import CanonicalProduct, ProductListing, SellerProfile
from app.schemas.regions import Region
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    SourceEvidence,
    SourceQuality,
    SourceQualityLevel,
)


@dataclass
class RecordingVerifierRunner:
    output: VerificationReport | dict[str, Any]
    calls: int = 0
    observed_tool_count: int | None = None

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del model_input, run_config, max_turns
        self.calls += 1
        self.observed_tool_count = len(getattr(agent, "tools", ()))
        return _RunResult(final_output=self.output)


@dataclass
class _RunResult:
    final_output: Any


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        **overrides,
    )


def _verification_input(
    *,
    budget_mode: BudgetMode = BudgetMode.PREFERRED,
    budget_amount: str = "300",
    listing_price: str = "249.99",
    final_rationale: str = "Fixture evidence describes the monitor candidate.",
) -> VerificationAgentInput:
    source_id = new_id()
    product = CanonicalProduct(
        name="Fixture Monitor",
        brand="Fixture",
        model="Monitor 1",
        category="monitor",
        source_ids=(source_id,),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title="Fixture Monitor - Official Store",
        url="https://example.com/monitor/fixture-1",
        seller=SellerProfile(
            seller_name="Fixture Official Store",
            is_marketplace_seller=False,
            source_ids=(source_id,),
        ),
        price=Money(amount=listing_price, currency="USD"),
        source_ids=(source_id,),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = SourceEvidence(
        source_id=source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product.product_id,
        ),
        evidence_type=EvidenceType.PRODUCT_SPEC,
        claim="Fixture evidence describes the monitor candidate.",
        confidence=_confidence(),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )
    bundle = _bundle(product, listing, evidence, final_rationale=final_rationale)
    return VerificationAgentInput(
        run_id=new_id(),
        brief=_brief(budget_mode=budget_mode, budget_amount=budget_amount),
        recommendation_bundle=bundle,
        products=(product,),
        listings=(listing,),
        evidence=(evidence,),
        trust_assessments=(_trust_assessment(listing, evidence),),
        category_analyses=(_category_analysis(product, listing, evidence),),
    )


def _brief(*, budget_mode: BudgetMode, budget_amount: str) -> ShoppingBrief:
    return ShoppingBrief(
        original_query="Need help choosing a monitor.",
        category="monitor",
        category_source=FieldSource.INFERRED,
        region=RegionPreference(
            region=Region(country_code="US", currency="USD"),
            source=FieldSource.USER_PROVIDED,
        ),
        budget=BudgetConstraint(
            amount=Money(amount=budget_amount, currency="USD"),
            mode=budget_mode,
            source=FieldSource.USER_PROVIDED,
        ),
    )


def _bundle(
    product: CanonicalProduct,
    listing: ProductListing,
    evidence: SourceEvidence,
    *,
    final_rationale: str,
) -> RecommendationBundle:
    matrix = ComparisonMatrix(
        criteria=(ComparisonCriterion(name="fit", weight=1.0),),
        rows=(
            ComparisonRow(
                product_id=product.product_id,
                listing_id=listing.listing_id,
                scores={"fit": 0.8},
                evidence_ids=(evidence.evidence_id,),
                summary="Fixture evidence describes the monitor candidate.",
            ),
        ),
    )
    return RecommendationBundle(
        final_product_id=product.product_id,
        final_listing_id=listing.listing_id,
        final_rationale=final_rationale,
        mode_results=(
            RecommendationModeResult(
                mode=RecommendationMode.BEST_OVERALL,
                product_id=product.product_id,
                listing_id=listing.listing_id,
                title="Best overall",
                rationale="Fixture evidence describes the monitor candidate.",
                confidence=_confidence(),
                evidence_ids=(evidence.evidence_id,),
                source_ids=(evidence.source_id,),
            ),
        ),
        comparison_matrix=matrix,
        evidence_ids=(evidence.evidence_id,),
        source_ids=(evidence.source_id,),
    )


def _category_analysis(
    product: CanonicalProduct,
    listing: ProductListing,
    evidence: SourceEvidence,
) -> CategoryAnalysis:
    return CategoryAnalysis(
        product_id=product.product_id,
        listing_ids=(listing.listing_id,),
        category="monitor",
        fit_summary="Fixture evidence describes the monitor candidate.",
        strengths=("Fixture evidence describes the monitor candidate.",),
        confidence=_confidence(),
        evidence_ids=(evidence.evidence_id,),
        source_ids=(evidence.source_id,),
    )


def _trust_assessment(
    listing: ProductListing,
    evidence: SourceEvidence,
) -> ListingTrustAssessment:
    return ListingTrustAssessment(
        listing_id=listing.listing_id,
        level=ListingTrustLevel.REASONABLE,
        confidence=_confidence(),
        summary="Fixture evidence describes the monitor candidate.",
        evidence_ids=(evidence.evidence_id,),
        source_ids=(evidence.source_id,),
    )


def _confidence() -> Confidence:
    return Confidence(
        score=0.7,
        level=ConfidenceLevel.MEDIUM,
        rationale="Fixture evidence describes the monitor candidate.",
    )


@pytest.mark.asyncio
async def test_optional_editorial_pass_preserves_uncited_budgeted_advice() -> None:
    request = _verification_input(budget_mode=BudgetMode.HARD_CAP, budget_amount="100")
    request = request.model_copy(
        update={
            "recommendation_bundle": request.recommendation_bundle.model_copy(
                update={
                    "evidence_ids": (),
                    "mode_results": (),
                    "final_rationale": "Consider this model. Confirm warranty before buying.",
                }
            )
        }
    )
    runner = RecordingVerifierRunner(
        output={
            "approved": False,
            "blocking_issues": ["Optional editorial suggestion."],
        }
    )
    agent = LiveVerifierCriticAgent(settings=_settings(), model_runner=runner)
    result = await agent.run(request)
    assert result.approved is True
    assert result.recommendation_bundle == request.recommendation_bundle
    assert result.blocking_issues == ()
    assert result.notes == ("Optional editorial suggestion.",)
    assert runner.observed_tool_count == 0


@pytest.mark.asyncio
async def test_optional_editorial_failure_preserves_original_advice() -> None:
    request = _verification_input()
    agent = LiveVerifierCriticAgent(
        settings=_settings(),
        model_runner=MockVerifierCriticModelRunner(error=RuntimeError("unavailable")),
    )
    result = await agent.run(request)
    assert result.approved is True
    assert result.recommendation_bundle == request.recommendation_bundle
    assert agent.workbench_activity[0]["status"] == "optional_editorial_unavailable"


@pytest.mark.asyncio
async def test_optional_editorial_context_limit_preserves_advice_without_another_call() -> (
    None
):
    request = _verification_input()
    runner = MockVerifierCriticModelRunner(
        error=ContextBudgetExceeded("configured limit")
    )
    agent = LiveVerifierCriticAgent(settings=_settings(), model_runner=runner)
    result = await agent.run(request)
    assert runner.calls == 1
    assert result.approved is True
    assert result.recommendation_bundle == request.recommendation_bundle
    assert result.blocking_issues == ()
    assert result.notes == (
        "Optional wording review stopped at the configured context limit. The original advice is preserved.",
    )
    assert agent.workbench_activity[0]["status"] == "optional_editorial_budget_limited"
