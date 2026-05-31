from inspect import Signature, signature

import pytest

from app.agents import (
    ComparisonDecisionAgent,
    ComparisonDecisionAgentInput,
    DeduplicationReviewAgent,
    DeduplicationReviewAgentInput,
    DiscoveryAgent,
    DiscoveryAgentInput,
    DiscoveryAgentOutput,
    EarphonesHeadphonesSpecialistAgent,
    ExtractionReviewAgent,
    ExtractionReviewAgentInput,
    ExtractionReviewAgentOutput,
    FakeComparisonDecisionAgent,
    FakeDeduplicationReviewAgent,
    FakeDiscoveryAgent,
    FakeEarphonesHeadphonesSpecialistAgent,
    FakeExtractionReviewAgent,
    FakeGenericProductAnalystAgent,
    FakeIntakeAgent,
    FakeLaptopSpecialistAgent,
    FakeMonitorSpecialistAgent,
    FakeQueryPlannerAgent,
    FakeSellerListingTrustAgent,
    FakeSmartphoneSpecialistAgent,
    FakeSmartwatchSpecialistAgent,
    FakeSourceIntelligenceAgent,
    FakeTVSpecialistAgent,
    FakeTechnologyDomainAnalystAgent,
    FakeVerifierCriticAgent,
    FakeYouTubeReviewIntelligenceAgent,
    GenericProductAnalystAgent,
    IntakeAgent,
    IntakeAgentInput,
    LaptopSpecialistAgent,
    MonitorSpecialistAgent,
    ProductAnalysisAgentInput,
    QueryPlannerAgent,
    QueryPlannerAgentInput,
    SellerListingTrustAgent,
    SellerListingTrustAgentInput,
    SmartphoneSpecialistAgent,
    SmartwatchSpecialistAgent,
    SourceIntelligenceAgent,
    SourceIntelligenceAgentInput,
    SourceIntelligenceAgentOutput,
    TVSpecialistAgent,
    TechnologyDomainAnalystAgent,
    VerificationAgentInput,
    VerificationReport,
    VerifierCriticAgent,
    YouTubeReviewIntelligenceAgent,
    YouTubeReviewIntelligenceAgentInput,
)
from app.schemas.analysis import (
    CategoryAnalysis,
    DeduplicationDecision,
    ListingTrustAssessment,
    RecommendationBundle,
)
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.search_sources import SearchPlan, VideoReviewEvidenceBundle


def test_agent_protocols_declare_typed_run_boundaries() -> None:
    agent_protocols = (
        IntakeAgent,
        QueryPlannerAgent,
        DiscoveryAgent,
        ExtractionReviewAgent,
        DeduplicationReviewAgent,
        GenericProductAnalystAgent,
        TechnologyDomainAnalystAgent,
        MonitorSpecialistAgent,
        SmartphoneSpecialistAgent,
        LaptopSpecialistAgent,
        EarphonesHeadphonesSpecialistAgent,
        TVSpecialistAgent,
        SmartwatchSpecialistAgent,
        SellerListingTrustAgent,
        SourceIntelligenceAgent,
        YouTubeReviewIntelligenceAgent,
        ComparisonDecisionAgent,
        VerifierCriticAgent,
    )

    for protocol in agent_protocols:
        run_signature = signature(protocol.run)
        input_annotation = run_signature.parameters["input_data"].annotation
        assert input_annotation is not Signature.empty
        assert run_signature.return_annotation is not Signature.empty


@pytest.mark.asyncio
async def test_agent_contract_fakes_return_typed_outputs_without_live_calls() -> None:
    run_id = new_id()
    intake_output = await FakeIntakeAgent().run(
        IntakeAgentInput(
            run_id=run_id,
            request=CreateSessionRequest(query="Need a 27 inch monitor"),
        )
    )
    assert isinstance(intake_output, ShoppingBrief)

    search_plan = await FakeQueryPlannerAgent().run(
        QueryPlannerAgentInput(run_id=run_id, brief=intake_output)
    )
    assert isinstance(search_plan, SearchPlan)

    discovery_output = await FakeDiscoveryAgent().run(
        DiscoveryAgentInput(
            run_id=run_id,
            brief=intake_output,
            search_plan=search_plan,
        )
    )
    assert isinstance(discovery_output, DiscoveryAgentOutput)
    assert discovery_output.search_results

    extraction_output = await FakeExtractionReviewAgent().run(
        ExtractionReviewAgentInput(
            run_id=run_id,
            search_results=discovery_output.search_results,
        )
    )
    assert isinstance(extraction_output, ExtractionReviewAgentOutput)
    assert extraction_output.products
    assert extraction_output.listings
    assert extraction_output.source_evidence

    dedupe_output = await FakeDeduplicationReviewAgent().run(
        DeduplicationReviewAgentInput(
            run_id=run_id,
            products=extraction_output.products,
            listings=extraction_output.listings,
            evidence=extraction_output.source_evidence,
        )
    )
    assert all(isinstance(item, DeduplicationDecision) for item in dedupe_output)

    analysis_input = ProductAnalysisAgentInput(
        run_id=run_id,
        brief=intake_output,
        product=extraction_output.products[0],
        listings=extraction_output.listings,
        evidence=extraction_output.source_evidence,
    )
    analysis_agents = (
        FakeGenericProductAnalystAgent(),
        FakeTechnologyDomainAnalystAgent(),
        FakeMonitorSpecialistAgent(),
        FakeSmartphoneSpecialistAgent(),
        FakeLaptopSpecialistAgent(),
        FakeEarphonesHeadphonesSpecialistAgent(),
        FakeTVSpecialistAgent(),
        FakeSmartwatchSpecialistAgent(),
    )
    category_analysis_items: list[CategoryAnalysis] = []
    for agent in analysis_agents:
        category_analysis_items.append(await agent.run(analysis_input))
    category_analyses = tuple(category_analysis_items)
    assert all(isinstance(item, CategoryAnalysis) for item in category_analyses)

    trust_output = await FakeSellerListingTrustAgent().run(
        SellerListingTrustAgentInput(
            run_id=run_id,
            listing=extraction_output.listings[0],
            evidence=extraction_output.source_evidence,
        )
    )
    assert isinstance(trust_output, ListingTrustAssessment)

    source_intelligence_output = await FakeSourceIntelligenceAgent().run(
        SourceIntelligenceAgentInput(
            run_id=run_id,
            brief=intake_output,
            products=extraction_output.products,
            listings=extraction_output.listings,
            source_snapshots=extraction_output.source_snapshots,
        )
    )
    assert isinstance(source_intelligence_output, SourceIntelligenceAgentOutput)

    youtube_output = await FakeYouTubeReviewIntelligenceAgent().run(
        YouTubeReviewIntelligenceAgentInput(
            run_id=run_id,
            brief=intake_output,
            products=extraction_output.products,
            listings=extraction_output.listings,
            video_queries=("fixture monitor review",),
        )
    )
    assert isinstance(youtube_output, VideoReviewEvidenceBundle)

    comparison_output = await FakeComparisonDecisionAgent().run(
        ComparisonDecisionAgentInput(
            run_id=run_id,
            brief=intake_output,
            products=extraction_output.products,
            listings=extraction_output.listings,
            category_analyses=category_analyses,
            trust_assessments=(trust_output,),
            deduplication_decisions=dedupe_output,
            evidence=extraction_output.source_evidence,
        )
    )
    assert isinstance(comparison_output, RecommendationBundle)

    verification_output = await FakeVerifierCriticAgent().run(
        VerificationAgentInput(
            run_id=run_id,
            brief=intake_output,
            recommendation_bundle=comparison_output,
            evidence=extraction_output.source_evidence,
            trust_assessments=(trust_output,),
            category_analyses=category_analyses,
        )
    )
    assert isinstance(verification_output, VerificationReport)
    assert verification_output.approved is True
