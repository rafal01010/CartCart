import asyncio
from dataclasses import dataclass
import os
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import (
    LiveTechnologyDomainAnalystAgent,
    MockTechnologyDomainAnalystModelRunner,
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
class RecordingTechnologyDomainAnalystRunner:
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


def _technology_input(
    category: str,
    *,
    weak_evidence: bool = False,
) -> ProductAnalysisAgentInput:
    source_id = new_id()
    review_source_id = new_id()
    product = CanonicalProduct(
        name=f"Fixture {category.title()}",
        brand="Fixture",
        model=f"{category.title()} 1",
        category=category,
        source_ids=(source_id,) if weak_evidence else (source_id, review_source_id),
    )
    listing = ProductListing(
        product_id=product.product_id,
        title=f"Fixture {category.title()} - Official Store",
        url=f"https://example.com/{category}/fixture-1",
        seller=SellerProfile(
            seller_name="Fixture Official Store",
            is_marketplace_seller=False,
        ),
        price=Money(amount="249", currency="USD"),
        source_ids=(source_id,),
        source_quality=SourceQuality(level=SourceQualityLevel.ADEQUATE, score=0.7),
    )
    product = product.model_copy(update={"listing_ids": (listing.listing_id,)})
    primary_quality = SourceQuality(
        level=SourceQualityLevel.WEAK if weak_evidence else SourceQualityLevel.ADEQUATE,
        score=0.25 if weak_evidence else 0.7,
        rationale="Synthetic technology analyst test evidence.",
    )
    evidence = (
        SourceEvidence(
            source_id=source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.PRODUCT,
                product_id=product.product_id,
            ),
            evidence_type=EvidenceType.PRODUCT_SPEC,
            claim=f"The listing describes a {category} candidate.",
            confidence=_confidence(0.35 if weak_evidence else 0.72),
            source_quality=primary_quality,
        ),
    )
    if not weak_evidence:
        evidence = (
            *evidence,
            SourceEvidence(
                source_id=review_source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=product.product_id,
                ),
                evidence_type=EvidenceType.REVIEW_CLAIM,
                claim=(
                    "A review source mentions practical fit, compatibility, "
                    "and durability tradeoffs."
                ),
                confidence=_confidence(0.66),
                source_quality=SourceQuality(
                    level=SourceQualityLevel.ADEQUATE,
                    score=0.65,
                    rationale="Synthetic review source evidence.",
                ),
            ),
        )

    return ProductAnalysisAgentInput(
        run_id=new_id(),
        brief=ShoppingBrief(
            original_query=f"Need help choosing a {category} for a desk setup.",
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
            preferences=(
                PreferenceConstraint(
                    text="Good everyday value.",
                    mode=PreferenceMode.SOFT,
                    source=FieldSource.USER_PROVIDED,
                ),
            ),
        ),
        product=product,
        listings=(listing,),
        evidence=evidence,
    )


def _valid_analysis(input_data: ProductAnalysisAgentInput) -> CategoryAnalysis:
    return CategoryAnalysis(
        product_id=input_data.product.product_id,
        listing_ids=tuple(listing.listing_id for listing in input_data.listings),
        category=input_data.product.category or input_data.brief.category or "technology",
        fit_summary=(
            "The candidate is a plausible technology fit, with compatibility "
            "and support details still worth checking."
        ),
        strengths=("Source evidence gives a starting point for technology fit.",),
        weaknesses=(
            "Compatibility, durability, support, and regional model caveats remain tradeoffs.",
        ),
        warnings=("Seller and listing trust should still be checked separately.",),
        confidence=_confidence(0.64),
        evidence_ids=tuple(item.evidence_id for item in input_data.evidence),
        source_ids=tuple(item.source_id for item in input_data.evidence),
    )


@pytest.mark.asyncio
async def test_live_technology_domain_accepts_valid_monitor_output_and_route() -> None:
    input_data = _technology_input("monitor")
    runner = RecordingTechnologyDomainAnalystRunner(output=_valid_analysis(input_data))
    agent = LiveTechnologyDomainAnalystAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.product_id == input_data.product.product_id
    assert result.category == "monitor"
    assert result.evidence_ids == tuple(item.evidence_id for item in input_data.evidence)
    assert result.source_ids == tuple(item.source_id for item in input_data.evidence)
    activity = agent.workbench_activity[0]
    assert activity["status"] == "model_technology_analysis_completed"
    assert activity["input"]["allowed_tools"] == []
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    ]
    assert activity["input"]["specialist_agent_name"] == "MonitorSpecialistAgent"


@pytest.mark.asyncio
async def test_live_technology_domain_analyzes_non_specialist_technology() -> None:
    runner = MockTechnologyDomainAnalystModelRunner()
    agent = LiveTechnologyDomainAnalystAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_technology_input("keyboard", weak_evidence=True))

    assert runner.calls == 1
    assert result.category == "keyboard"
    assert result.confidence.level == ConfidenceLevel.LOW
    combined_text = " ".join(
        (
            result.fit_summary,
            *result.strengths,
            *result.weaknesses,
            *result.warnings,
        )
    ).casefold()
    assert "evidence" in combined_text
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text
    activity = agent.workbench_activity[0]
    assert activity["status"] == "model_technology_analysis_completed"
    assert activity["input"]["declared_route"]["agent_path"] == [
        "TechnologyDomainAnalystAgent"
    ]
    assert activity["input"]["specialist_agent_name"] is None


@pytest.mark.asyncio
async def test_live_technology_domain_sends_non_technology_to_generic_fallback() -> None:
    runner = RecordingTechnologyDomainAnalystRunner()
    agent = LiveTechnologyDomainAnalystAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_technology_input("office chair"))

    assert runner.calls == 0
    assert result.category == "office chair"
    assert result.weaknesses
    assert agent.workbench_activity[0]["status"] == "generic_fallback_non_technology"
    assert agent.workbench_activity[0]["input"]["declared_route"]["agent_path"] == [
        "GenericProductAnalystAgent"
    ]


@pytest.mark.asyncio
async def test_live_technology_domain_falls_back_on_blocking_output() -> None:
    input_data = _technology_input("keyboard")
    runner = RecordingTechnologyDomainAnalystRunner(
        output={
            "product_id": str(input_data.product.product_id),
            "listing_ids": [str(input_data.listings[0].listing_id)],
            "category": "unsupported category no specialist",
            "fit_summary": "No specialist exists for this technology product.",
            "strengths": ["No specialist fit signal."],
            "weaknesses": ["No specialist is available."],
            "confidence": _confidence(0.4).model_dump(mode="json"),
            "evidence_ids": [str(new_id())],
        }
    )
    agent = LiveTechnologyDomainAnalystAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.category == "keyboard"
    assert result.evidence_ids == tuple(item.evidence_id for item in input_data.evidence)
    assert agent.workbench_activity[0]["status"] == "schema_invalid_generic_fallback"
    combined_text = " ".join(
        (result.fit_summary, *result.strengths, *result.weaknesses, *result.warnings)
    ).casefold()
    assert "unsupported" not in combined_text
    assert "no specialist" not in combined_text


@pytest.mark.asyncio
async def test_live_technology_domain_falls_back_on_timeout() -> None:
    runner = RecordingTechnologyDomainAnalystRunner(delay_seconds=0.02)
    agent = LiveTechnologyDomainAnalystAgent(
        settings=_settings(openai_agent_timeout_seconds=0.001),
        model_runner=runner,
    )

    result = await agent.run(_technology_input("keyboard"))

    assert runner.calls == 1
    assert result.category == "keyboard"
    assert result.weaknesses
    assert agent.workbench_activity[0]["status"] == "timeout_generic_fallback"


@pytest.mark.asyncio
async def test_live_technology_domain_falls_back_on_model_error() -> None:
    runner = RecordingTechnologyDomainAnalystRunner(error=RuntimeError("mock failed"))
    agent = LiveTechnologyDomainAnalystAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_technology_input("keyboard"))

    assert runner.calls == 1
    assert result.category == "keyboard"
    assert result.weaknesses
    assert agent.workbench_activity[0]["status"] == "error_generic_fallback"


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_technology_domain_analyst_agent_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings(_env_file=None, live_agents_enabled=True)  # type: ignore[call-arg]
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured.")

    result = await LiveTechnologyDomainAnalystAgent(settings=settings).run(
        _technology_input("keyboard")
    )

    assert result.category


def _confidence(score: float) -> Confidence:
    if score < 0.5:
        level = ConfidenceLevel.LOW
    elif score < 0.75:
        level = ConfidenceLevel.MEDIUM
    else:
        level = ConfidenceLevel.HIGH
    return Confidence(score=score, level=level, rationale="Synthetic confidence.")
