import asyncio
from dataclasses import dataclass
import os
from typing import Any

import pytest

from agents import Agent, RunConfig
from agents import WebSearchTool
from pydantic import AnyHttpUrl
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents import (
    LiveSellerListingTrustAgent,
    MockSellerListingTrustModelRunner,
    SellerListingTrustAgentInput,
)
from app.agents.openai_config import OpenAIAgentConfigurationError
from app.agents.research_tools import HostedCitationStore
from app.agents.trust_hosted_search import trust_citation_matches_target
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory
from app.schemas.analysis import (
    ListingTrustAssessment,
    ListingTrustLevel,
    ListingTrustSignal,
    ListingTrustSignalKind,
    ListingTrustSignalPolarity,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
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
import app.db.models  # noqa: F401


@dataclass
class RecordingSellerListingTrustRunner:
    output: ListingTrustAssessment | dict[str, Any] | None = None
    error: BaseException | None = None
    delay_seconds: float = 0
    calls: int = 0
    raw_responses: list[Any] | None = None
    seen_agent: Agent[Any] | None = None

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del model_input, run_config, max_turns
        self.seen_agent = agent
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return _RunResult(
            final_output=self.output, raw_responses=self.raw_responses or []
        )


@dataclass
class _RunResult:
    final_output: Any
    raw_responses: list[Any]


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
        ("The price is too low to treat as safe without stronger seller evidence.",)
        if explain_price
        else ()
    )
    signals = (
        (
            ListingTrustSignal(
                kind=ListingTrustSignalKind.SUSPICIOUS_PRICE,
                polarity=ListingTrustSignalPolarity.NEGATIVE,
                strength=0.9,
                summary="The price is too low versus comparable listings.",
                evidence_ids=tuple(item.evidence_id for item in input_data.evidence),
                source_ids=input_data.listing.source_ids,
            ),
        )
        if explain_price
        else ()
    )
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


def _hosted_input() -> SellerListingTrustAgentInput:
    input_data = _cheap_marketplace_input()
    listing = input_data.listing.model_copy(
        update={
            "url": AnyHttpUrl("https://www.amazon.com/dp/B000000442"),
            "seller": input_data.listing.seller.model_copy(
                update={
                    "seller_url": AnyHttpUrl(
                        "https://www.amazon.com/stores/dealhub442"
                    ),
                    "marketplace_name": "Amazon",
                }
            ),
        }
    )
    return input_data.model_copy(
        update={"listing": listing, "target_region_code": "US"}
    )


def _hosted_response(url: str, *, status: str = "completed") -> list[Any]:
    return [
        {
            "output": [
                {
                    "type": "web_search_call",
                    "id": "ws_trust_1",
                    "status": status,
                    "action": {"type": "search", "sources": [{"url": url}]},
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "text": "Seller policy page",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": url,
                                    "title": "Seller policy page",
                                    "start_index": 0,
                                    "end_index": 18,
                                }
                            ],
                        }
                    ],
                },
            ]
        }
    ]


async def _hosted_database(input_data: SellerListingTrustAgentInput):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        brief = ShoppingBrief(original_query=input_data.listing.title)
        shopping_session = await SessionRepository(session).create(
            original_input=CreateSessionRequest(query=input_data.listing.title),
            current_brief=brief,
        )
        await RunRepository(session).create(
            shopping_session.session_id, run_id=input_data.run_id
        )
        await session.commit()
    return engine, factory


def _live_settings(**overrides: object) -> Settings:
    return _settings(
        live_agents_enabled=True,
        openai_api_key="mock-only-no-call",
        openai_model="gpt-6-luna",
        **overrides,
    )


def test_trust_hosted_region_path_rejects_other_country_policy_page() -> None:
    listing = _established_input().listing.model_copy(
        update={"url": AnyHttpUrl("https://www.ikea.com/ph/en/p/desk-123")}
    )
    assert trust_citation_matches_target(
        "https://www.ikea.com/ph/en/customer-service/returns", listing, "PH"
    )
    assert not trust_citation_matches_target(
        "https://www.ikea.com/us/en/customer-service/returns", listing, "PH"
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
async def test_live_seller_listing_trust_falls_back_when_hard_flags_are_silent() -> (
    None
):
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


@pytest.mark.asyncio
async def test_hosted_trust_call_persists_cited_lead_without_clearing_hard_flag() -> (
    None
):
    input_data = _hosted_input()
    url = str(input_data.listing.seller.seller_url)
    runner = RecordingSellerListingTrustRunner(
        output={
            "assessment": _reasonable_assessment(
                input_data, explain_price=True
            ).model_dump(mode="json"),
            "web_leads": [{"url": url, "question": "seller_identity"}],
        },
        raw_responses=_hosted_response(url),
    )
    engine, factory = await _hosted_database(input_data)
    try:
        agent = LiveSellerListingTrustAgent(
            settings=_live_settings(),
            citation_store_factory=lambda run_id: HostedCitationStore(
                run_id=run_id, session_factory=factory
            ),
            model_runner=runner,
        )
        assessment = await agent.run(input_data)
        assert runner.seen_agent is not None
        tool = next(
            tool for tool in runner.seen_agent.tools if isinstance(tool, WebSearchTool)
        )
        assert tool.user_location["country"] == "US"
        assert tool.filters["allowed_domains"] == ["amazon.com"]
        assert runner.seen_agent.model_settings.tool_choice == "auto"
        assert assessment.level == ListingTrustLevel.SUSPICIOUS
        lead = next(
            signal
            for signal in assessment.trust_signals
            if signal.polarity == ListingTrustSignalPolarity.NEUTRAL
            and signal.evidence_ids
            and signal.evidence_ids[0]
            not in {item.evidence_id for item in input_data.evidence}
        )
        assert lead.kind == ListingTrustSignalKind.SELLER_IDENTITY
        assert lead.strength == 0.2
        assert lead.evidence_ids[0] in assessment.evidence_ids
        assert lead.source_ids[0] in assessment.source_ids
        async with factory() as session:
            repo = SearchSourceRepository(session)
            sources = await repo.list_search_results(input_data.run_id)
            evidence = await repo.list_source_evidence(input_data.run_id)
        assert any(str(item.url) == url for item in sources)
        assert any(item.evidence_id == lead.evidence_ids[0] for item in evidence)
        assert any(
            item["tool_name"] == "web_search_citation"
            and item["status"] == "retained"
            and item["output"]["evidence_id"] == str(lead.evidence_ids[0])
            for item in agent.workbench_activity
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_hosted_trust_can_skip_search_when_supplied_evidence_suffices() -> None:
    input_data = _established_input()
    runner = RecordingSellerListingTrustRunner(
        output={
            "assessment": _reasonable_assessment(input_data).model_dump(mode="json"),
            "web_leads": [],
        },
        raw_responses=[],
    )
    engine, factory = await _hosted_database(input_data)
    try:
        agent = LiveSellerListingTrustAgent(
            settings=_live_settings(),
            citation_store_factory=lambda run_id: HostedCitationStore(
                run_id=run_id, session_factory=factory
            ),
            model_runner=runner,
        )
        assessment = await agent.run(input_data)
        assert assessment.level == ListingTrustLevel.REASONABLE
        assert runner.seen_agent is not None
        assert any(isinstance(tool, WebSearchTool) for tool in runner.seen_agent.tools)
        assert all(
            item["tool_name"] != "web_search" for item in agent.workbench_activity
        )
        async with factory() as session:
            assert not await SearchSourceRepository(session).list_search_results(
                input_data.run_id
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_hosted_trust_rejects_other_seller_url_and_uncited_assertion() -> None:
    input_data = _hosted_input()
    url = "https://www.amazon.com/stores/other-seller"
    runner = RecordingSellerListingTrustRunner(
        output={
            "assessment": _reasonable_assessment(
                input_data, explain_price=True
            ).model_dump(mode="json"),
            "web_leads": [{"url": url, "question": "return_warranty"}],
        },
        raw_responses=_hosted_response(url),
    )
    engine, factory = await _hosted_database(input_data)
    try:
        agent = LiveSellerListingTrustAgent(
            settings=_live_settings(),
            citation_store_factory=lambda run_id: HostedCitationStore(
                run_id=run_id, session_factory=factory
            ),
            model_runner=runner,
        )
        assessment = await agent.run(input_data)
        assert assessment.level == ListingTrustLevel.SUSPICIOUS
        assert not any(
            item["tool_name"] == "web_search_citation" and item["status"] == "retained"
            for item in agent.workbench_activity
        )
        assert any(
            item["tool_name"] == "web_search_gap" for item in agent.workbench_activity
        )
        async with factory() as session:
            assert not await SearchSourceRepository(session).list_search_results(
                input_data.run_id
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_hosted_rating_cannot_upgrade_unknown_seller_to_trusted() -> None:
    source_id = new_id()
    listing = ProductListing(
        product_id=new_id(),
        title="Unverified marketplace item",
        url="https://shop.example.com/listing/item-42",
        seller=SellerProfile(seller_name="Unknown Seller"),
        region_availability=(RegionAvailability(region_code="US"),),
        source_ids=(source_id,),
    )
    input_data = SellerListingTrustAgentInput(
        run_id=new_id(), listing=listing, target_region_code="US"
    )
    rule = assess_listing_trust(listing)
    assert rule.level == ListingTrustLevel.UNKNOWN
    url = str(listing.url)
    runner = RecordingSellerListingTrustRunner(
        output={
            "assessment": rule.model_copy(
                update={
                    "level": ListingTrustLevel.STRONG,
                    "summary": "A five-star rating proves this seller is trusted.",
                    "positive_signals": ("Five-star marketplace rating",),
                }
            ).model_dump(mode="json"),
            "web_leads": [{"url": url, "question": "seller_identity"}],
        },
        raw_responses=_hosted_response(url),
    )
    engine, factory = await _hosted_database(input_data)
    try:
        agent = LiveSellerListingTrustAgent(
            settings=_live_settings(),
            citation_store_factory=lambda run_id: HostedCitationStore(
                run_id=run_id, session_factory=factory
            ),
            model_runner=runner,
        )
        result = await agent.run(input_data)
        assert result.level == ListingTrustLevel.UNKNOWN
        assert "five-star" not in result.summary.lower()
        assert "Five-star marketplace rating" not in result.positive_signals
        assert any(
            signal.polarity == ListingTrustSignalPolarity.NEUTRAL
            and signal.evidence_ids
            for signal in result.trust_signals
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_hosted_trust_call_records_gap_and_no_new_evidence() -> None:
    input_data = _hosted_input()
    url = str(input_data.listing.seller.seller_url)
    runner = RecordingSellerListingTrustRunner(
        output={
            "assessment": _reasonable_assessment(
                input_data, explain_price=True
            ).model_dump(mode="json"),
            "web_leads": [{"url": url, "question": "seller_identity"}],
        },
        raw_responses=_hosted_response(url, status="failed"),
    )
    engine, factory = await _hosted_database(input_data)
    try:
        agent = LiveSellerListingTrustAgent(
            settings=_live_settings(),
            citation_store_factory=lambda run_id: HostedCitationStore(
                run_id=run_id, session_factory=factory
            ),
            model_runner=runner,
        )
        result = await agent.run(input_data)
        assert result.level == ListingTrustLevel.SUSPICIOUS
        assert any(
            item["tool_name"] == "web_search_gap" for item in agent.workbench_activity
        )
        async with factory() as session:
            assert not await SearchSourceRepository(session).list_search_results(
                input_data.run_id
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_hosted_trust_uncited_url_falls_back_and_unknown_model_fails_closed() -> (
    None
):
    input_data = _hosted_input()
    runner = RecordingSellerListingTrustRunner(
        output={
            "assessment": _reasonable_assessment(
                input_data, explain_price=True
            ).model_dump(mode="json"),
            "web_leads": [
                {
                    "url": "https://www.amazon.com/stores/dealhub442",
                    "question": "seller_identity",
                }
            ],
        },
        raw_responses=_hosted_response("https://www.amazon.com/dp/B000000442"),
    )
    engine, factory = await _hosted_database(input_data)
    try:

        def store_factory(run_id):
            return HostedCitationStore(run_id=run_id, session_factory=factory)

        agent = LiveSellerListingTrustAgent(
            settings=_live_settings(),
            citation_store_factory=store_factory,
            model_runner=runner,
        )
        assessment = await agent.run(input_data)
        assert assessment == input_data.rule_based_assessment
        assert (
            agent.workbench_activity[0]["status"]
            == "schema_invalid_rule_based_fallback"
        )
        incompatible = LiveSellerListingTrustAgent(
            settings=_live_settings(
                openai_agent_overrides={
                    "SellerListingTrustAgent": {"model": "unsupported-web-model"}
                }
            ),
            citation_store_factory=store_factory,
            model_runner=runner,
        )
        with pytest.raises(OpenAIAgentConfigurationError):
            await incompatible.run(input_data)
    finally:
        await engine.dispose()


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_seller_listing_trust_agent_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings()
    if not settings.live_agents_enabled or settings.openai_api_key is None:
        pytest.skip("Live agents and OPENAI_API_KEY must be configured in .env.")

    input_data = _established_input()
    engine, factory = await _hosted_database(input_data)
    try:
        result = await LiveSellerListingTrustAgent(
            settings=settings,
            citation_store_factory=lambda run_id: HostedCitationStore(
                run_id=run_id, session_factory=factory
            ),
        ).run(input_data)
        assert result.level in ListingTrustLevel
    finally:
        await engine.dispose()


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
