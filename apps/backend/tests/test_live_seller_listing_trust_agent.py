import asyncio
from dataclasses import dataclass
import os
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import (
    LiveSellerListingTrustAgent,
    MockSellerListingTrustModelRunner,
    SellerListingTrustAgentInput,
)
from app.core.settings import Settings
from app.schemas.analysis import (
    ListingTrustAssessment,
    ListingTrustLevel,
    ListingTrustSignal,
    ListingTrustSignalKind,
    ListingTrustSignalPolarity,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.schemas.money import Money
from app.schemas.products import (
    ProductListing,
    RegionAvailability,
    SellerProfile,
    SellerTrustSignal,
)
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    SourceEvidence,
    SourceQuality,
    SourceQualityLevel,
)
from app.services.listing_trust import ListingTrustRuleContext, assess_listing_trust


@dataclass
class RecordingSellerListingTrustRunner:
    output: ListingTrustAssessment | dict[str, Any] | None = None
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


def _established_input() -> SellerListingTrustAgentInput:
    source_id = new_id()
    listing = ProductListing(
        product_id=new_id(),
        title="Acme Monitor - Established Retailer",
        url="https://www.bestbuy.com/site/acme-monitor/fixture",
        seller=SellerProfile(
            seller_name="Best Buy",
            is_marketplace_seller=False,
            trust_signal=SellerTrustSignal.STRONG,
            source_ids=(source_id,),
        ),
        price=Money(amount="299", currency="USD"),
        retailer_id="BESTBUY-ACME-MON",
        region_availability=(
            RegionAvailability(region_code="US", source_ids=(source_id,)),
        ),
        source_quality=SourceQuality(level=SourceQualityLevel.STRONG, score=0.86),
        source_ids=(source_id,),
    )
    evidence = SourceEvidence(
        source_id=source_id,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.LISTING,
            listing_id=listing.listing_id,
        ),
        evidence_type=EvidenceType.SELLER_TRUST,
        claim="The retailer listing has clear seller identity, returns, and warranty.",
        confidence=_confidence(0.82),
        source_quality=SourceQuality(level=SourceQualityLevel.STRONG, score=0.86),
    )
    rule_based = assess_listing_trust(
        listing,
        ListingTrustRuleContext(
            review_count=120,
            return_policy_present=True,
            warranty_present=True,
            evidence_ids=(evidence.evidence_id,),
            source_ids=(source_id,),
        ),
    )
    return SellerListingTrustAgentInput(
        run_id=new_id(),
        listing=listing,
        evidence=(evidence,),
        rule_based_assessment=rule_based,
    )


def _cheap_marketplace_input() -> SellerListingTrustAgentInput:
    source_id = new_id()
    listing = ProductListing(
        product_id=new_id(),
        title="Acme Monitor - Marketplace Deal",
        url="https://deals.example-market.test/acme-monitor-cheap",
        seller=SellerProfile(
            seller_name="DealHub Seller 442",
            marketplace_name="DealHub",
            is_marketplace_seller=True,
            trust_signal=SellerTrustSignal.UNKNOWN,
            source_ids=(source_id,),
        ),
        price=Money(amount="89", currency="USD"),
        retailer_id=None,
        source_quality=SourceQuality(level=SourceQualityLevel.UNKNOWN, score=0.32),
        source_ids=(source_id,),
    )
    evidence = (
        SourceEvidence(
            source_id=source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.LISTING,
                listing_id=listing.listing_id,
            ),
            evidence_type=EvidenceType.PRICE,
            claim="The listing price is far below comparable same-product listings.",
            confidence=_confidence(0.78),
            source_quality=SourceQuality(level=SourceQualityLevel.MIXED, score=0.42),
        ),
        SourceEvidence(
            source_id=source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.SELLER,
                seller_name=listing.seller.seller_name,
            ),
            evidence_type=EvidenceType.WARRANTY,
            claim="Return and warranty coverage are unclear for this seller.",
            confidence=_confidence(0.62),
            source_quality=SourceQuality(level=SourceQualityLevel.MIXED, score=0.42),
        ),
    )
    rule_based = assess_listing_trust(
        listing,
        ListingTrustRuleContext(
            review_count=0,
            return_policy_present=False,
            warranty_present=False,
            suspicious_price=True,
            suspicious_price_reasons=(
                "The listing price is only about 28% of comparable same-product "
                "listings, which is too low to treat as a normal discount "
                "without stronger seller evidence.",
            ),
            evidence_ids=tuple(item.evidence_id for item in evidence),
            source_ids=(source_id,),
        ),
    )
    return SellerListingTrustAgentInput(
        run_id=new_id(),
        listing=listing,
        evidence=evidence,
        rule_based_assessment=rule_based,
    )


def _reasonable_assessment(
    input_data: SellerListingTrustAgentInput,
    *,
    explain_price: bool = False,
) -> ListingTrustAssessment:
    red_flags = (
        "The price is too low to treat as safe without stronger seller evidence.",
    ) if explain_price else ()
    signals = (
        ListingTrustSignal(
            kind=ListingTrustSignalKind.SUSPICIOUS_PRICE,
            polarity=ListingTrustSignalPolarity.NEGATIVE,
            strength=0.9,
            summary="The price is too low versus comparable listings.",
            evidence_ids=tuple(item.evidence_id for item in input_data.evidence),
            source_ids=input_data.listing.source_ids,
        ),
    ) if explain_price else ()
    return ListingTrustAssessment(
        listing_id=input_data.listing.listing_id,
        level=ListingTrustLevel.REASONABLE,
        confidence=_confidence(0.66),
        summary=(
            "The seller might be acceptable."
            if not explain_price
            else "The seller might be acceptable, but the price is too low."
        ),
        trust_signals=signals,
        red_flags=red_flags,
        positive_signals=("Seller identity is visible.",),
        evidence_ids=tuple(item.evidence_id for item in input_data.evidence),
        source_ids=input_data.listing.source_ids,
    )


@pytest.mark.asyncio
async def test_live_seller_listing_trust_accepts_valid_established_output() -> None:
    input_data = _established_input()
    runner = RecordingSellerListingTrustRunner(
        output=_reasonable_assessment(input_data),
    )
    agent = LiveSellerListingTrustAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.listing_id == input_data.listing.listing_id
    assert result.level == ListingTrustLevel.REASONABLE
    assert set(result.evidence_ids) == {
        item.evidence_id for item in input_data.evidence
    }
    assert set(result.source_ids) == set(input_data.listing.source_ids)
    activity = agent.workbench_activity[0]
    assert activity["status"] == "model_listing_trust_completed"
    assert activity["input"]["allowed_tools"] == []


@pytest.mark.asyncio
async def test_live_seller_listing_trust_mock_flags_unknown_cheap_marketplace() -> None:
    input_data = _cheap_marketplace_input()
    runner = MockSellerListingTrustModelRunner()
    agent = LiveSellerListingTrustAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.level == ListingTrustLevel.SUSPICIOUS
    combined_text = _combined_text(result)
    assert "price" in combined_text
    assert "return" in combined_text or "warranty" in combined_text
    assert "unsupported" not in combined_text
    assert agent.workbench_activity[0]["status"] == "hard_suspicious_flag_preserved"


@pytest.mark.asyncio
async def test_live_seller_listing_trust_preserves_explained_hard_flags() -> None:
    input_data = _cheap_marketplace_input()
    runner = RecordingSellerListingTrustRunner(
        output=_reasonable_assessment(input_data, explain_price=True),
    )
    agent = LiveSellerListingTrustAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result.level == ListingTrustLevel.SUSPICIOUS
    assert any(
        signal.kind == ListingTrustSignalKind.SUSPICIOUS_PRICE
        for signal in result.trust_signals
    )
    assert "too low" in _combined_text(result)
    assert agent.workbench_activity[0]["status"] == "hard_suspicious_flag_preserved"


@pytest.mark.asyncio
async def test_live_seller_listing_trust_falls_back_when_hard_flags_are_silent() -> None:
    input_data = _cheap_marketplace_input()
    runner = RecordingSellerListingTrustRunner(
        output=_reasonable_assessment(input_data),
    )
    agent = LiveSellerListingTrustAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result == input_data.rule_based_assessment
    assert agent.workbench_activity[0]["status"] == (
        "schema_invalid_rule_based_fallback"
    )


@pytest.mark.asyncio
async def test_live_seller_listing_trust_falls_back_on_schema_invalid_output() -> None:
    input_data = _established_input()
    runner = RecordingSellerListingTrustRunner(
        output={
            "listing_id": str(new_id()),
            "level": "reasonable",
            "confidence": _confidence(0.66).model_dump(mode="json"),
            "summary": "Uses an unknown listing ID.",
            "evidence_ids": [str(input_data.evidence[0].evidence_id)],
            "source_ids": [str(input_data.listing.source_ids[0])],
        }
    )
    agent = LiveSellerListingTrustAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result == input_data.rule_based_assessment
    assert agent.workbench_activity[0]["status"] == (
        "schema_invalid_rule_based_fallback"
    )


@pytest.mark.asyncio
async def test_live_seller_listing_trust_falls_back_on_timeout() -> None:
    runner = RecordingSellerListingTrustRunner(delay_seconds=0.02)
    agent = LiveSellerListingTrustAgent(
        settings=_settings(openai_agent_timeout_seconds=0.001),
        model_runner=runner,
    )
    input_data = _established_input()

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result == input_data.rule_based_assessment
    assert agent.workbench_activity[0]["status"] == "timeout_rule_based_fallback"


@pytest.mark.asyncio
async def test_live_seller_listing_trust_falls_back_on_model_error() -> None:
    runner = RecordingSellerListingTrustRunner(error=RuntimeError("mock failed"))
    agent = LiveSellerListingTrustAgent(settings=_settings(), model_runner=runner)
    input_data = _established_input()

    result = await agent.run(input_data)

    assert runner.calls == 1
    assert result == input_data.rule_based_assessment
    assert agent.workbench_activity[0]["status"] == "error_rule_based_fallback"


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_seller_listing_trust_agent_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings(_env_file=None, live_agents_enabled=True)  # type: ignore[call-arg]
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured.")

    result = await LiveSellerListingTrustAgent(settings=settings).run(
        _established_input()
    )

    assert result.level in ListingTrustLevel


def _combined_text(assessment: ListingTrustAssessment) -> str:
    return " ".join(
        (
            assessment.summary,
            *assessment.red_flags,
            *assessment.positive_signals,
            *(signal.summary for signal in assessment.trust_signals),
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
