import asyncio
from dataclasses import dataclass
import os
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import (
    LiveSmartwatchSpecialistAgent,
    MockSmartwatchSpecialistModelRunner,
    ProductAnalysisAgentInput,
)
from app.core.settings import Settings
from app.schemas.analysis import CategoryAnalysis
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
class RecordingSmartwatchSpecialistRunner:
    output: CategoryAnalysis | dict[str, Any] | None = None
    error: BaseException | None = None
    delay_seconds: float = 0
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del agent, model_input, run_config, max_turns
        self.calls += 1
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


def _analysis_input(
    category: str,
    *,
    weak_evidence: bool = False,
) -> ProductAnalysisAgentInput:
    source_id = new_id()
    review_source_id = new_id()
    spec_source_id = new_id()
    product = CanonicalProduct(
        name=f"Fixture {category.title()}",
        brand="Fixture",
        model=f"{category.title()} 1",
        category=category,
        source_ids=(source_id, review_source_id, spec_source_id),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title=f"Fixture {category.title()} - Official Store",
        url=f"https://example.com/{category}/fixture-1",
        seller=SellerProfile(
            seller_name="Fixture Official Store",
            is_marketplace_seller=False,
        ),
        price=Money(amount="799", currency="USD"),
        source_ids=(source_id,),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    quality = SourceQuality(
        level=SourceQualityLevel.WEAK if weak_evidence else SourceQualityLevel.ADEQUATE,
        score=0.25 if weak_evidence else 0.72,
        rationale="Synthetic smartwatch specialist test evidence.",
    )
    evidence = (
        SourceEvidence(
            source_id=source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=f"The listing describes a {category} candidate with core specs.",
            confidence=_confidence(0.35 if weak_evidence else 0.72),
            source_quality=quality,
        ),
        SourceEvidence(
            source_id=review_source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.REVIEW_CLAIM,
            claim="A review mentions practical fit and tradeoffs.",
            confidence=_confidence(0.34 if weak_evidence else 0.66),
            source_quality=quality,
        ),
    )
    if category in {"smartwatch", "smart watch"} and not weak_evidence:
        evidence = (
            evidence[0].model_copy(
                update={
                    "claim": (
                        "Listing states the watch runs Wear OS, pairs with "
                        "Android phones, supports notifications and calls, "
                        "and uses a phone companion app."
                    )
                }
            ),
            SourceEvidence(
                source_id=spec_source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=product.product_id,
                ),
                evidence_type=EvidenceType.PRODUCT_SPEC,
                claim=(
                    "Spec sheet lists heart-rate, GPS, SpO2, sleep tracking, "
                    "48-hour battery life, fast charging, IP68 durability, "
                    "and 5ATM water resistance."
                ),
                confidence=_confidence(0.7),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.ADEQUATE,
                    score=0.7,
                    rationale="Synthetic smartwatch spec evidence.",
                ),
            ),
            evidence[1].model_copy(
                update={
                    "claim": (
                        "Review says Android compatibility is stronger than "
                        "iPhone support, health sensors are consistent for "
                        "runs, battery lasts about two days, and Wear OS "
                        "third-party apps are useful."
                    )
                }
            ),
        )

    return ProductAnalysisAgentInput(
        run_id=new_id(),
        brief=ShoppingBrief(
            original_query=(
                f"Need help choosing a {category} for fitness with my Android phone."
            ),
            category=category,
            category_source=FieldSource.INFERRED,
            region=RegionPreference(
                region=Region(country_code="US", currency="USD"),
                source=FieldSource.USER_PROVIDED,
            ),
            budget=BudgetConstraint(
                amount=Money(amount="300", currency="USD"),
                mode=BudgetMode.PREFERRED,
                source=FieldSource.USER_PROVIDED,
            ),
            constraints=(
                PreferenceConstraint(
                    text="Works well with Android if this is a smartwatch",
                    mode=PreferenceMode.HARD,
                    source=FieldSource.USER_PROVIDED,
                ),
                PreferenceConstraint(
                    text="Reliable fitness and health tracking",
                    mode=PreferenceMode.HARD,
                    source=FieldSource.USER_PROVIDED,
                ),
            ),
            preferences=(
                PreferenceConstraint(
                    text="Long battery, water resistance, and useful apps",
                    mode=PreferenceMode.SOFT,
                    source=FieldSource.USER_PROVIDED,
                ),
            ),
        ),
        product=product,
        listings=(listing,),
        evidence=evidence,
    )


def _valid_smartwatch_analysis(
    input_data: ProductAnalysisAgentInput,
) -> CategoryAnalysis:
    return CategoryAnalysis(
        product_id=input_data.product.product_id,
        listing_ids=tuple(listing.listing_id for listing in input_data.listings),
        category="smartwatch",
        fit_summary=(
            "This smartwatch is plausible for an Android fitness buyer because "
            "supplied evidence covers phone compatibility, health sensors, "
            "battery life, durability, water resistance, and app ecosystem."
        ),
        strengths=(
            "Phone compatibility evidence confirms the strongest fit is with "
            "Android and Wear OS.",
            "Health sensor evidence covers heart-rate, GPS, sleep, SpO2, and "
            "fitness tracking.",
            "Battery, charging, durability, water resistance, and third-party app "
            "ecosystem details are documented.",
        ),
        weaknesses=(
            "The main tradeoffs are iPhone compatibility, sensor accuracy, "
            "battery runtime, case durability, water resistance, and app ecosystem.",
        ),
        warnings=("Seller and listing trust should still be checked separately.",),
        confidence=_confidence(0.68),
        evidence_ids=tuple(item.evidence_id for item in input_data.evidence),
        source_ids=tuple(item.source_id for item in input_data.evidence),
    )


@pytest.mark.asyncio
async def test_smartwatch_specialist_accepts_source_backed_output() -> None:
    input_data = _analysis_input("smartwatch")
    runner = RecordingSmartwatchSpecialistRunner(
        output=_valid_smartwatch_analysis(input_data)
    )
    agent = LiveSmartwatchSpecialistAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.product_id == input_data.product.product_id
    assert result.category == "smartwatch"
    assert result.evidence_ids == tuple(
        item.evidence_id for item in input_data.evidence
    )
    assert result.source_ids == tuple(item.source_id for item in input_data.evidence)
    combined_text = _combined_text(result)
    for marker in (
        "phone compatibility",
        "android",
        "health sensor",
        "battery",
        "durability",
        "water resistance",
        "app ecosystem",
    ):
        assert marker in combined_text
    activity = agent.workbench_activity[0]
    assert activity["status"] == "model_smartwatch_analysis_completed"
    assert activity["input"]["allowed_tools"] == []
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "SmartwatchSpecialistAgent",
    ]


@pytest.mark.asyncio
async def test_smartwatch_specialist_mock_limits_weak_evidence() -> None:
    input_data = _analysis_input("smartwatch", weak_evidence=True)
    runner = MockSmartwatchSpecialistModelRunner()
    agent = LiveSmartwatchSpecialistAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.category == "smartwatch"
    assert result.confidence.level == ConfidenceLevel.LOW
    assert result.confidence.score <= 0.5
    combined_text = _combined_text(result)
    assert "evidence" in combined_text
    assert "missing" in combined_text or "limited" in combined_text
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text


@pytest.mark.asyncio
async def test_smartwatch_specialist_routes_non_watch_tech_to_fallback() -> None:
    runner = RecordingSmartwatchSpecialistRunner(output=None)
    agent = LiveSmartwatchSpecialistAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_analysis_input("laptop"))

    assert runner.calls == 0
    assert result.category == "laptop"
    assert result.weaknesses
    activity = agent.workbench_activity[0]
    assert activity["status"] == "technology_domain_fallback_non_smartwatch"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "LaptopSpecialistAgent",
    ]


@pytest.mark.asyncio
async def test_live_smartwatch_specialist_routes_non_tech_to_generic_fallback() -> None:
    runner = RecordingSmartwatchSpecialistRunner(output=None)
    agent = LiveSmartwatchSpecialistAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_analysis_input("office chair"))

    assert runner.calls == 0
    assert result.category == "office chair"
    assert result.weaknesses
    activity = agent.workbench_activity[0]
    assert activity["status"] == "generic_fallback_non_smartwatch"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "GenericProductAnalystAgent"
    ]


@pytest.mark.asyncio
async def test_live_smartwatch_specialist_falls_back_on_schema_invalid_output() -> None:
    input_data = _analysis_input("smartwatch")
    runner = RecordingSmartwatchSpecialistRunner(
        output={
            "product_id": str(input_data.product.product_id),
            "listing_ids": [str(input_data.listings[0].listing_id)],
            "category": "smartwatch",
            "fit_summary": "This omits required smartwatch coverage.",
            "strengths": ["It has some evidence."],
            "weaknesses": ["Some tradeoffs remain."],
            "confidence": _confidence(0.58).model_dump(mode="json"),
            "evidence_ids": [str(new_id())],
        }
    )
    agent = LiveSmartwatchSpecialistAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.category == "smartwatch"
    assert result.evidence_ids == tuple(
        item.evidence_id for item in input_data.evidence
    )
    assert agent.workbench_activity[0]["status"] == (
        "schema_invalid_technology_domain_fallback"
    )
    combined_text = _combined_text(result)
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text


@pytest.mark.asyncio
async def test_live_smartwatch_specialist_falls_back_on_timeout() -> None:
    runner = RecordingSmartwatchSpecialistRunner(delay_seconds=0.02)
    agent = LiveSmartwatchSpecialistAgent(
        settings=_settings(openai_agent_timeout_seconds=0.001),
        model_runner=runner,
    )

    result = await agent.run(_analysis_input("smartwatch"))

    assert runner.calls == 1
    assert result.category == "smartwatch"
    assert result.weaknesses
    assert agent.workbench_activity[0]["status"] == (
        "timeout_technology_domain_fallback"
    )


@pytest.mark.asyncio
async def test_live_smartwatch_specialist_falls_back_on_model_error() -> None:
    runner = RecordingSmartwatchSpecialistRunner(error=RuntimeError("mock failed"))
    agent = LiveSmartwatchSpecialistAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_analysis_input("smartwatch"))

    assert runner.calls == 1
    assert result.category == "smartwatch"
    assert result.weaknesses
    assert agent.workbench_activity[0]["status"] == "error_technology_domain_fallback"


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_smartwatch_specialist_agent_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        live_agents_enabled=True,
    )
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured.")

    result = await LiveSmartwatchSpecialistAgent(settings=settings).run(
        _analysis_input("smartwatch")
    )

    assert result.category


def _combined_text(analysis: CategoryAnalysis) -> str:
    return " ".join(
        (
            analysis.fit_summary,
            *analysis.strengths,
            *analysis.weaknesses,
            *analysis.warnings,
        )
    ).casefold()


def _confidence(score: float) -> Confidence:
    if score < 0.5:
        level = ConfidenceLevel.LOW
    elif score < 0.75:
        level = ConfidenceLevel.MEDIUM
    else:
        level = ConfidenceLevel.HIGH
    return Confidence(score=score, level=level, rationale="Synthetic confidence.")
