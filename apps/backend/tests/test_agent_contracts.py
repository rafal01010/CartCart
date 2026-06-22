from inspect import Signature, signature

import pytest

from app.agents import (
    AmazonProductIntelligenceAgent,
    AmazonProductIntelligenceAgentInput,
    CategoryRouterAgent,
    CategoryRouterAgentInput,
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
    FakeAmazonProductIntelligenceAgent,
    FakeCategoryRouterAgent,
    FakeComparisonDecisionAgent,
    FakeDeduplicationReviewAgent,
    FakeDiscoveryAgent,
    FakeEarphonesHeadphonesSpecialistAgent,
    FakeExtractionReviewAgent,
    FakeGenericProductAnalystAgent,
    FakeIKEAStoreIntelligenceAgent,
    FakeIntakeAgent,
    FakeLaptopSpecialistAgent,
    FakeMonitorSpecialistAgent,
    FakeQueryPlannerAgent,
    FakeRedditCommunityIntelligenceAgent,
    FakeSellerListingTrustAgent,
    FakeShoppingGuideAgent,
    FakeShoppingScopeGuardrail,
    FakeSmartphoneSpecialistAgent,
    FakeSmartwatchSpecialistAgent,
    FakeSourceIntelligenceAgent,
    FakeTVSpecialistAgent,
    FakeTechnologyDomainAnalystAgent,
    FakeVerifierCriticAgent,
    FakeYouTubeReviewIntelligenceAgent,
    GenericProductAnalystAgent,
    IKEAStoreIntelligenceAgent,
    IKEAStoreIntelligenceAgentInput,
    IntakeAgent,
    IntakeAgentInput,
    LaptopSpecialistAgent,
    MonitorSpecialistAgent,
    ProductAnalysisAgentInput,
    ProductAnalysisRoute,
    QueryPlannerAgent,
    QueryPlannerAgentInput,
    RedditCommunityIntelligenceAgent,
    RedditCommunityIntelligenceAgentInput,
    SellerListingTrustAgent,
    SellerListingTrustAgentInput,
    ShoppingGuideAgent,
    ShoppingGuideAgentInput,
    ShoppingScopeGuardrail,
    ShoppingScopeGuardrailInput,
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
from app.schemas.guided_intake import (
    GuidedAnswerSurface,
    GuidedIntakeState,
    GuidedIntakeStatus,
    InlineChoiceControlType,
    RegionSetupStatus,
    ShoppingGuardrailDecision,
    ShoppingGuardrailReason,
    ShoppingGuardrailResult,
)
from app.schemas.regions import Region
from app.schemas.search_sources import (
    AmazonProductEvidenceBundle,
    CommunityDiscussionEvidenceBundle,
    IKEAStoreEvidenceBundle,
    SearchPlan,
    VideoReviewEvidenceBundle,
)


def test_agent_protocols_declare_typed_run_boundaries() -> None:
    agent_protocols = (
        IntakeAgent,
        ShoppingGuideAgent,
        ShoppingScopeGuardrail,
        QueryPlannerAgent,
        DiscoveryAgent,
        CategoryRouterAgent,
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
        RedditCommunityIntelligenceAgent,
        AmazonProductIntelligenceAgent,
        IKEAStoreIntelligenceAgent,
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

    guardrail_output = await FakeShoppingScopeGuardrail().run(
        ShoppingScopeGuardrailInput(user_input="Need a 27 inch monitor")
    )
    assert isinstance(guardrail_output, ShoppingGuardrailResult)
    assert guardrail_output.decision == ShoppingGuardrailDecision.ALLOWED

    guide_output = await FakeShoppingGuideAgent().run(
        ShoppingGuideAgentInput(user_input="Need a 27 inch monitor")
    )
    assert isinstance(guide_output, GuidedIntakeState)
    assert guide_output.status == GuidedIntakeStatus.COLLECTING
    assert guide_output.current_question is not None
    assert guide_output.current_question.answer_surface == (
        GuidedAnswerSurface.INLINE_CHOICE
    )

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

    route_output = await FakeCategoryRouterAgent().run(
        CategoryRouterAgentInput(
            run_id=run_id,
            brief=intake_output,
        )
    )
    assert isinstance(route_output, ProductAnalysisRoute)
    assert route_output.agent_path == (
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
    )

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
    assert not isinstance(youtube_output, RecommendationBundle)

    reddit_output = await FakeRedditCommunityIntelligenceAgent().run(
        RedditCommunityIntelligenceAgentInput(
            run_id=run_id,
            brief=intake_output,
            products=extraction_output.products,
            listings=extraction_output.listings,
            community_queries=("fixture monitor reddit",),
        )
    )
    assert isinstance(reddit_output, CommunityDiscussionEvidenceBundle)
    assert not isinstance(reddit_output, RecommendationBundle)
    assert reddit_output.evidence
    assert reddit_output.evidence[0].qualitative_signal is True

    amazon_output = await FakeAmazonProductIntelligenceAgent().run(
        AmazonProductIntelligenceAgentInput(
            run_id=run_id,
            brief=intake_output,
            products=extraction_output.products,
            listings=extraction_output.listings,
            product_queries=("fixture monitor amazon",),
            target_region_code="US",
        )
    )
    assert isinstance(amazon_output, AmazonProductEvidenceBundle)
    assert not isinstance(amazon_output, RecommendationBundle)
    assert amazon_output.listing_contexts
    assert amazon_output.evidence

    ikea_output = await FakeIKEAStoreIntelligenceAgent().run(
        IKEAStoreIntelligenceAgentInput(
            run_id=run_id,
            brief=intake_output,
            products=extraction_output.products,
            listings=extraction_output.listings,
            product_queries=("fixture monitor ikea",),
            target_region_code="US",
        )
    )
    assert isinstance(ikea_output, IKEAStoreEvidenceBundle)
    assert not isinstance(ikea_output, RecommendationBundle)
    assert ikea_output.store_contexts
    assert ikea_output.evidence_gaps

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


@pytest.mark.asyncio
async def test_fake_shopping_guide_asks_budget_before_product_names() -> None:
    guide = await FakeShoppingGuideAgent().run(
        ShoppingGuideAgentInput(
            user_input="Which laptop should I buy for travel?",
            region_setup={
                "status": RegionSetupStatus.PROVIDED,
                "region": Region(country_code="US", currency="USD"),
            },
        )
    )

    assert guide.status == GuidedIntakeStatus.COLLECTING
    assert guide.current_question is not None
    assert guide.current_question.question_id == "budget"
    assert guide.current_question.answer_surface == GuidedAnswerSurface.TEXTBOX
    assert guide.current_question.inline_choice is None
    assert guide.current_question.combined_optional_prompt is None
    assert guide.skippable_question.can_skip is True
    assert guide.analysis_start.can_skip_all_and_start_analysis is True
    assert guide.region_setup.status == RegionSetupStatus.PROVIDED


@pytest.mark.asyncio
async def test_fake_shopping_guide_uses_inline_choices_only_when_helpful() -> None:
    monitor_guide = await FakeShoppingGuideAgent().run(
        ShoppingGuideAgentInput(user_input="Need a portable monitor for travel")
    )
    comparison_guide = await FakeShoppingGuideAgent().run(
        ShoppingGuideAgentInput(
            user_input="Between an iPhone and a Samsung, which is better?"
        )
    )

    assert monitor_guide.current_question is not None
    assert monitor_guide.current_question.inline_choice is not None
    assert monitor_guide.current_question.inline_choice.control_type == (
        InlineChoiceControlType.YES_NO
    )
    assert comparison_guide.current_question is not None
    assert comparison_guide.current_question.inline_choice is not None
    assert comparison_guide.current_question.inline_choice.control_type == (
        InlineChoiceControlType.TWO_OPTION_PLUS_TYPE_ANSWER
    )


@pytest.mark.asyncio
async def test_fake_shopping_guide_can_skip_all_and_hand_complete_brief_to_intake() -> None:
    guide = await FakeShoppingGuideAgent().run(
        ShoppingGuideAgentInput(
            user_input="Which laptop should I buy for travel?",
            prior_answers=(
                {
                    "question_id": "budget",
                    "answer": {
                        "answer_type": "natural_language",
                        "text": "Around $1,200.",
                    },
                },
                {
                    "question_id": "considered-products",
                    "answer": {
                        "answer_type": "natural_language",
                        "text": (
                            "ThinkPad X1 Carbon. I need long battery life."
                        ),
                    },
                },
            ),
            start_analysis_requested=True,
        )
    )

    assert guide.status == GuidedIntakeStatus.READY_FOR_ANALYSIS
    assert guide.ready_brief is not None
    assert guide.ready_brief.category == "laptop"
    assert guide.ready_brief.budget is not None
    assert guide.ready_brief.budget.amount.amount == 1200
    assert guide.ready_brief.constraints[0].text.endswith("long battery life.")
    assert "ThinkPad X1 Carbon" in guide.ready_brief.constraints[0].text


@pytest.mark.asyncio
async def test_fake_shopping_guide_supports_skip_all_optional_questions() -> None:
    guide = await FakeShoppingGuideAgent().run(
        ShoppingGuideAgentInput(
            user_input="Which desk should I buy?",
            skipped_question_ids=("budget", "considered-products"),
        )
    )

    assert guide.status == GuidedIntakeStatus.READY_FOR_ANALYSIS
    assert guide.ready_brief is not None
    assert guide.ready_brief.category == "desk"


@pytest.mark.asyncio
async def test_fake_shopping_guide_supports_reanswer_without_restart() -> None:
    guide = await FakeShoppingGuideAgent().run(
        ShoppingGuideAgentInput(
            user_input="Need a portable monitor for travel",
            prior_answers=(
                {
                    "question_id": "monitor-connection",
                    "answer": {"answer_type": "yes_no", "value": True},
                },
            ),
            reanswer_question_id="monitor-connection",
        )
    )

    assert guide.status == GuidedIntakeStatus.COLLECTING
    assert guide.current_question is not None
    assert guide.current_question.question_id == "monitor-connection"
    assert guide.navigation.can_go_back is True
    assert guide.navigation.current_reanswer_question_id == "monitor-connection"


@pytest.mark.asyncio
async def test_fake_shopping_guardrail_blocks_unsuitable_requests_before_discovery() -> None:
    off_topic = await FakeShoppingScopeGuardrail().run(
        ShoppingScopeGuardrailInput(user_input="Write a poem about a laptop")
    )
    unsafe = await FakeShoppingScopeGuardrail().run(
        ShoppingScopeGuardrailInput(user_input="Which gun should I buy?")
    )
    blocked_guide = await FakeShoppingGuideAgent().run(
        ShoppingGuideAgentInput(user_input="Write a poem about a laptop")
    )

    assert off_topic.decision == ShoppingGuardrailDecision.BLOCKED
    assert off_topic.reason == ShoppingGuardrailReason.OFF_TOPIC
    assert unsafe.decision == ShoppingGuardrailDecision.BLOCKED
    assert unsafe.reason == ShoppingGuardrailReason.UNSAFE_PRODUCT
    assert blocked_guide.status == GuidedIntakeStatus.BLOCKED
    assert blocked_guide.guardrail is not None
    assert "shopping decisions" in blocked_guide.guardrail.message
