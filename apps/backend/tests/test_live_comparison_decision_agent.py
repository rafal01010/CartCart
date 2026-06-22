import asyncio
from dataclasses import dataclass
import os
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import (
    ComparisonDecisionAgentInput,
    LiveComparisonDecisionAgent,
    MockComparisonDecisionModelRunner,
)
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
    PreferenceConstraint,
    PreferenceMode,
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
class RecordingComparisonDecisionRunner:
    output: RecommendationBundle | dict[str, Any] | None = None
    error: BaseException | None = None
    delay_seconds: float = 0
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
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
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


def _monitor_shortlist_input(
    *,
    budget_mode: BudgetMode = BudgetMode.PREFERRED,
) -> ComparisonDecisionAgentInput:
    brief = _brief(budget_mode=budget_mode)
    dell = _candidate(
        name="Dell UltraSharp U2724DE",
        brand="Dell",
        model="U2724DE",
        price="289.99",
        fit_score=0.82,
    )
    asus = _candidate(
        name="ASUS ProArt PA278CV",
        brand="ASUS",
        model="PA278CV",
        price="219.99",
        fit_score=0.74,
    )
    lg = _candidate(
        name="LG 27UP850-W",
        brand="LG",
        model="27UP850-W",
        price="379.99",
        fit_score=0.76,
    )
    candidates = (dell, asus, lg)
    return ComparisonDecisionAgentInput(
        run_id=new_id(),
        brief=brief,
        products=tuple(item[0] for item in candidates),
        listings=tuple(item[1] for item in candidates),
        category_analyses=tuple(item[3] for item in candidates),
        trust_assessments=tuple(item[4] for item in candidates),
        evidence=tuple(item[2] for item in candidates),
    )


def _weak_shortlist_input() -> ComparisonDecisionAgentInput:
    brief = _brief(budget_mode=BudgetMode.HARD_CAP)
    suspicious = _candidate(
        name="ViewPro VP27Q Marketplace",
        brand="ViewPro",
        model="VP27Q",
        price="119.99",
        fit_score=0.42,
        trust_level=ListingTrustLevel.SUSPICIOUS,
        quality=SourceQualityLevel.MIXED,
    )
    weak = _candidate(
        name="BudgetPix BP270",
        brand="BudgetPix",
        model="BP270",
        price="279.99",
        fit_score=0.38,
        trust_level=ListingTrustLevel.WEAK,
        quality=SourceQualityLevel.WEAK,
    )
    candidates = (suspicious, weak)
    return ComparisonDecisionAgentInput(
        run_id=new_id(),
        brief=brief,
        products=tuple(item[0] for item in candidates),
        listings=tuple(item[1] for item in candidates),
        category_analyses=tuple(item[3] for item in candidates),
        trust_assessments=tuple(item[4] for item in candidates),
        evidence=tuple(item[2] for item in candidates),
    )


def _preferred_budget_all_stretch_input() -> ComparisonDecisionAgentInput:
    brief = _brief(budget_mode=BudgetMode.PREFERRED)
    dell = _candidate(
        name="Dell UltraSharp U2724DE",
        brand="Dell",
        model="U2724DE",
        price="329.99",
        fit_score=0.82,
    )
    lg = _candidate(
        name="LG 27UP850-W",
        brand="LG",
        model="27UP850-W",
        price="379.99",
        fit_score=0.78,
    )
    candidates = (dell, lg)
    return ComparisonDecisionAgentInput(
        run_id=new_id(),
        brief=brief,
        products=tuple(item[0] for item in candidates),
        listings=tuple(item[1] for item in candidates),
        category_analyses=tuple(item[3] for item in candidates),
        trust_assessments=tuple(item[4] for item in candidates),
        evidence=tuple(item[2] for item in candidates),
    )


def _valid_bundle(input_data: ComparisonDecisionAgentInput) -> RecommendationBundle:
    first, second, third = input_data.products
    first_listing, second_listing, third_listing = input_data.listings
    evidence_ids = tuple(item.evidence_id for item in input_data.evidence)
    source_ids = tuple(item.source_id for item in input_data.evidence)
    matrix = ComparisonMatrix(
        criteria=(
            ComparisonCriterion(name="fit", weight=0.35),
            ComparisonCriterion(name="value", weight=0.25),
            ComparisonCriterion(name="listing_trust", weight=0.25),
            ComparisonCriterion(name="evidence", weight=0.15),
        ),
        rows=(
            ComparisonRow(
                product_id=first.product_id,
                listing_id=first_listing.listing_id,
                scores={
                    "fit": 0.9,
                    "value": 0.7,
                    "listing_trust": 0.8,
                    "evidence": 0.8,
                },
                evidence_ids=(evidence_ids[0],),
                summary="Best overall fit.",
            ),
            ComparisonRow(
                product_id=second.product_id,
                listing_id=second_listing.listing_id,
                scores={
                    "fit": 0.75,
                    "value": 0.92,
                    "listing_trust": 0.8,
                    "evidence": 0.72,
                },
                evidence_ids=(evidence_ids[1],),
                summary="Best value.",
            ),
            ComparisonRow(
                product_id=third.product_id,
                listing_id=third_listing.listing_id,
                scores={
                    "fit": 0.78,
                    "value": 0.44,
                    "listing_trust": 0.8,
                    "evidence": 0.74,
                },
                evidence_ids=(evidence_ids[2],),
                summary="Stretch option.",
            ),
        ),
    )
    return RecommendationBundle(
        final_product_id=first.product_id,
        final_listing_id=first_listing.listing_id,
        final_rationale="Best balance of fit, value, trust, and evidence.",
        runner_up_product_ids=(second.product_id, third.product_id),
        mode_results=(
            _mode_result(
                RecommendationMode.BEST_OVERALL,
                first.product_id,
                first_listing.listing_id,
                "Best overall",
                evidence_ids[0],
                source_ids[0],
            ),
            _mode_result(
                RecommendationMode.BEST_VALUE,
                second.product_id,
                second_listing.listing_id,
                "Best value",
                evidence_ids[1],
                source_ids[1],
            ),
            _mode_result(
                RecommendationMode.WITHIN_BUDGET,
                second.product_id,
                second_listing.listing_id,
                "Within budget",
                evidence_ids[1],
                source_ids[1],
            ),
            _mode_result(
                RecommendationMode.STRETCH_PICK,
                third.product_id,
                third_listing.listing_id,
                "Stretch pick",
                evidence_ids[2],
                source_ids[2],
                rationale=(
                    "Worth considering only if the preferred budget is flexible "
                    "because it costs more but improves the tradeoff."
                ),
            ),
            _mode_result(
                RecommendationMode.RUNNER_UP,
                second.product_id,
                second_listing.listing_id,
                "Runner-up",
                evidence_ids[1],
                source_ids[1],
            ),
        ),
        comparison_matrix=matrix,
        evidence_ids=evidence_ids,
        source_ids=source_ids,
    )


@pytest.mark.asyncio
async def test_live_comparison_decision_accepts_valid_monitor_bundle() -> None:
    input_data = _monitor_shortlist_input()
    runner = RecordingComparisonDecisionRunner(output=_valid_bundle(input_data))
    agent = LiveComparisonDecisionAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert runner.observed_tool_count == 0
    assert result.final_product_id == input_data.products[0].product_id
    assert result.final_listing_id == input_data.listings[0].listing_id
    assert result.no_strong_buy is False
    assert {mode.mode for mode in result.mode_results} >= {
        RecommendationMode.BEST_OVERALL,
        RecommendationMode.BEST_VALUE,
        RecommendationMode.WITHIN_BUDGET,
        RecommendationMode.STRETCH_PICK,
        RecommendationMode.RUNNER_UP,
    }
    assert result.runner_up_product_ids == (
        input_data.products[1].product_id,
        input_data.products[2].product_id,
    )
    assert result.rejected_items == ()
    assert agent.workbench_activity[0]["status"] == "model_comparison_decision_completed"
    assert agent.workbench_activity[0]["input"]["allowed_tools"] == []


@pytest.mark.asyncio
async def test_live_comparison_decision_mock_generates_modes_without_forced_rejections() -> None:
    input_data = _monitor_shortlist_input()
    runner = MockComparisonDecisionModelRunner()
    agent = LiveComparisonDecisionAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.final_product_id is not None
    assert result.no_strong_buy is False
    assert {mode.mode for mode in result.mode_results} >= {
        RecommendationMode.BEST_OVERALL,
        RecommendationMode.BEST_VALUE,
        RecommendationMode.WITHIN_BUDGET,
        RecommendationMode.STRETCH_PICK,
    }
    assert result.runner_up_product_ids
    assert result.rejected_items == ()
    assert agent.workbench_activity[0]["status"] == "model_comparison_decision_completed"


@pytest.mark.asyncio
async def test_live_comparison_decision_rejects_hard_cap_over_budget_pick() -> None:
    input_data = _monitor_shortlist_input(budget_mode=BudgetMode.HARD_CAP)
    invalid_output = _valid_bundle(input_data).model_dump(mode="json")
    invalid_output["final_product_id"] = str(input_data.products[2].product_id)
    invalid_output["final_listing_id"] = str(input_data.listings[2].listing_id)
    invalid_output["mode_results"] = [
        {
            **mode,
            "product_id": str(input_data.products[2].product_id),
            "listing_id": str(input_data.listings[2].listing_id),
        }
        if mode["mode"] == "best_overall"
        else mode
        for mode in invalid_output["mode_results"]
        if mode["mode"] != "stretch_pick"
    ]
    runner = RecordingComparisonDecisionRunner(output=invalid_output)
    agent = LiveComparisonDecisionAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"
    assert result.no_strong_buy is False
    assert result.final_listing_id != input_data.listings[2].listing_id
    assert RecommendationMode.STRETCH_PICK not in {
        mode.mode for mode in result.mode_results
    }
    assert all(
        mode.listing_id != input_data.listings[2].listing_id
        for mode in result.mode_results
    )
    assert any("hard budget" in item.reason.casefold() for item in result.rejected_items)


@pytest.mark.asyncio
async def test_live_comparison_decision_mock_treats_preferred_budget_as_soft_cap() -> None:
    input_data = _monitor_shortlist_input(budget_mode=BudgetMode.PREFERRED)
    runner = MockComparisonDecisionModelRunner()
    agent = LiveComparisonDecisionAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    stretch = next(
        mode
        for mode in result.mode_results
        if mode.mode == RecommendationMode.STRETCH_PICK
    )
    within_budget = next(
        mode
        for mode in result.mode_results
        if mode.mode == RecommendationMode.WITHIN_BUDGET
    )
    assert result.no_strong_buy is False
    assert stretch.listing_id == input_data.listings[2].listing_id
    assert within_budget.listing_id in {
        input_data.listings[0].listing_id,
        input_data.listings[1].listing_id,
    }
    assert not any(
        item.listing_id == input_data.listings[2].listing_id
        for item in result.rejected_items
    )


@pytest.mark.asyncio
async def test_live_comparison_decision_rejects_unjustified_soft_stretch() -> None:
    input_data = _monitor_shortlist_input(budget_mode=BudgetMode.PREFERRED)
    invalid_output = _valid_bundle(input_data).model_dump(mode="json")
    for mode in invalid_output["mode_results"]:
        if mode["mode"] == "stretch_pick":
            mode["rationale"] = "Most capable option in the shortlist."
    runner = RecordingComparisonDecisionRunner(output=invalid_output)
    agent = LiveComparisonDecisionAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"
    stretch = next(
        mode
        for mode in result.mode_results
        if mode.mode == RecommendationMode.STRETCH_PICK
    )
    assert "budget" in stretch.rationale.casefold()
    assert "tradeoff" in stretch.rationale.casefold()


@pytest.mark.asyncio
async def test_live_comparison_decision_soft_stretch_without_alternative_no_strong_buy() -> None:
    input_data = _preferred_budget_all_stretch_input()
    runner = MockComparisonDecisionModelRunner()
    agent = LiveComparisonDecisionAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.no_strong_buy is True
    assert result.final_product_id is None
    assert result.no_strong_buy_reason is not None
    assert "preferred budget" in result.no_strong_buy_reason.casefold()


@pytest.mark.asyncio
async def test_live_comparison_decision_mock_returns_explicit_no_strong_buy() -> None:
    input_data = _weak_shortlist_input()
    runner = MockComparisonDecisionModelRunner()
    agent = LiveComparisonDecisionAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.no_strong_buy is True
    assert result.final_product_id is None
    assert result.no_strong_buy_reason is not None
    assert "suspicious" in result.no_strong_buy_reason.casefold()
    assert any(item.severity == "blocking" for item in result.rejected_items)


@pytest.mark.asyncio
async def test_live_comparison_decision_falls_back_on_unknown_ids() -> None:
    input_data = _monitor_shortlist_input()
    invalid_output = _valid_bundle(input_data).model_dump(mode="json")
    invalid_output["final_product_id"] = str(new_id())
    runner = RecordingComparisonDecisionRunner(output=invalid_output)
    agent = LiveComparisonDecisionAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.final_product_id in {product.product_id for product in input_data.products}
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"


@pytest.mark.asyncio
async def test_live_comparison_decision_falls_back_on_timeout() -> None:
    runner = RecordingComparisonDecisionRunner(delay_seconds=0.02)
    agent = LiveComparisonDecisionAgent(
        settings=_settings(openai_agent_timeout_seconds=0.001),
        model_runner=runner,
    )

    result = await agent.run(_monitor_shortlist_input())

    assert runner.calls == 1
    assert result.final_product_id is not None
    assert agent.workbench_activity[0]["status"] == "timeout_fallback"


@pytest.mark.asyncio
async def test_live_comparison_decision_falls_back_on_model_error() -> None:
    runner = RecordingComparisonDecisionRunner(error=RuntimeError("mock failed"))
    agent = LiveComparisonDecisionAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_monitor_shortlist_input())

    assert runner.calls == 1
    assert result.final_product_id is not None
    assert agent.workbench_activity[0]["status"] == "error_fallback"


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_comparison_decision_agent_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings(_env_file=None, live_agents_enabled=True)  # type: ignore[call-arg]
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured.")

    result = await LiveComparisonDecisionAgent(settings=settings).run(
        _monitor_shortlist_input()
    )

    assert result.final_product_id is not None or result.no_strong_buy is True


def _brief(*, budget_mode: BudgetMode) -> ShoppingBrief:
    return ShoppingBrief(
        original_query="Need a 27-inch 1440p monitor for coding and movies under $300.",
        category="monitor",
        category_source=FieldSource.INFERRED,
        region=RegionPreference(
            region=Region(country_code="US", currency="USD"),
            source=FieldSource.USER_PROVIDED,
        ),
        budget=BudgetConstraint(
            amount=Money(amount="300", currency="USD"),
            mode=budget_mode,
            source=FieldSource.USER_PROVIDED,
        ),
        preferences=(
            PreferenceConstraint(
                text="Good for coding and movies",
                mode=PreferenceMode.SOFT,
            ),
        ),
    )


def _candidate(
    *,
    name: str,
    brand: str,
    model: str,
    price: str,
    fit_score: float,
    trust_level: ListingTrustLevel = ListingTrustLevel.REASONABLE,
    quality: SourceQualityLevel = SourceQualityLevel.ADEQUATE,
) -> tuple[
    CanonicalProduct,
    ProductListing,
    SourceEvidence,
    CategoryAnalysis,
    ListingTrustAssessment,
]:
    source_id = new_id()
    product = CanonicalProduct(
        name=name,
        brand=brand,
        model=model,
        category="monitor",
        source_ids=(source_id,),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title=f"{name} - Test Store",
        url=f"https://example.com/monitors/{model.casefold()}",
        seller=SellerProfile(
            seller_name="Test Store",
            is_marketplace_seller=trust_level != ListingTrustLevel.REASONABLE,
            source_ids=(source_id,),
        ),
        price=Money(amount=price, currency="USD"),
        source_ids=(source_id,),
        source_quality=SourceQuality(level=quality, score=fit_score),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    evidence = SourceEvidence(
        source_id=source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product.product_id,
        ),
        evidence_type=EvidenceType.PRODUCT_SPEC,
        claim=f"{name} has source-backed monitor facts for the shortlist.",
        confidence=_confidence(fit_score),
        source_quality=SourceQuality(level=quality, score=fit_score),
    )
    analysis = CategoryAnalysis(
        product_id=product.product_id,
        listing_ids=(listing.listing_id,),
        category="monitor",
        fit_summary=f"{name} was analyzed for the monitor brief.",
        strengths=("Source-backed monitor fit signals are available.",),
        weaknesses=("Tradeoffs remain around price, trust, or evidence depth.",),
        warnings=(
            ("Evidence is limited.",)
            if quality in {SourceQualityLevel.WEAK, SourceQualityLevel.MIXED}
            else ()
        ),
        confidence=_confidence(fit_score),
        evidence_ids=(evidence.evidence_id,),
        source_ids=(source_id,),
    )
    trust = ListingTrustAssessment(
        listing_id=listing.listing_id,
        level=trust_level,
        confidence=_confidence(0.75 if trust_level == ListingTrustLevel.REASONABLE else 0.45),
        summary=f"Listing trust is {trust_level.value}.",
        red_flags=("Seller/listing trust is unsafe.",)
        if trust_level == ListingTrustLevel.SUSPICIOUS
        else (),
        evidence_ids=(evidence.evidence_id,),
        source_ids=(source_id,),
    )
    return product, listing, evidence, analysis, trust


def _mode_result(
    mode: RecommendationMode,
    product_id: Any,
    listing_id: Any,
    title: str,
    evidence_id: Any,
    source_id: Any,
    *,
    rationale: str | None = None,
) -> RecommendationModeResult:
    return RecommendationModeResult(
        mode=mode,
        product_id=product_id,
        listing_id=listing_id,
        title=title,
        rationale=rationale or f"{title} rationale is source-backed.",
        confidence=_confidence(0.76),
        evidence_ids=(evidence_id,),
        source_ids=(source_id,),
    )


def _confidence(score: float) -> Confidence:
    if score < 0.5:
        level = ConfidenceLevel.LOW
    elif score < 0.75:
        level = ConfidenceLevel.MEDIUM
    else:
        level = ConfidenceLevel.HIGH
    return Confidence(score=score, level=level, rationale="Synthetic confidence.")
