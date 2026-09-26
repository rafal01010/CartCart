import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents import (
    DEFAULT_AGENT_CATALOG,
    AgentCatalog,
    AgentKind,
    AgentStatus,
    InvocationMode,
)
from app.agents.catalog import ApprovedSDKTool, FixtureFallback, ResearchDecision
from app.core.agent_run_profiles import AgentRunProfileName


def test_agent_catalog_assigns_workload_profiles() -> None:
    assert DEFAULT_AGENT_CATALOG.require("QueryPlannerAgent").run_profile == (
        AgentRunProfileName.FAST
    )
    assert DEFAULT_AGENT_CATALOG.require("ExtractionAgent").run_profile == (
        AgentRunProfileName.FAST
    )
    assert DEFAULT_AGENT_CATALOG.require("DiscoveryAgent").run_profile == (
        AgentRunProfileName.STRONG
    )
    assert DEFAULT_AGENT_CATALOG.require("ComparisonDecisionAgent").run_profile == (
        AgentRunProfileName.STRONG
    )
    assert DEFAULT_AGENT_CATALOG.require("VerifierCriticAgent").run_profile == (
        AgentRunProfileName.STRONG
    )


def test_research_sdk_tool_allowlist_is_scoped_by_agent() -> None:
    assert DEFAULT_AGENT_CATALOG.require("DiscoveryAgent").approved_sdk_tools == (
        ApprovedSDKTool.SEARCH_SOURCES,
        ApprovedSDKTool.FETCH_SOURCE,
    )
    assert DEFAULT_AGENT_CATALOG.require("QueryPlannerAgent").approved_sdk_tools == ()
    assert DEFAULT_AGENT_CATALOG.require("ExtractionAgent").approved_sdk_tools == (
        ApprovedSDKTool.READ_SOURCE_SNAPSHOT,
    )


def test_fixture_research_fallbacks_are_explicit_in_catalog() -> None:
    assert DEFAULT_AGENT_CATALOG.require("DiscoveryAgent").fixture_fallback == (
        FixtureFallback.UNCERTAIN_SOURCE
    )
    assert DEFAULT_AGENT_CATALOG.require("ExtractionAgent").fixture_fallback == (
        FixtureFallback.EVIDENCE_GAP
    )


def test_agent_catalog_routes_unknown_categories_to_generic_fallback() -> None:
    route = DEFAULT_AGENT_CATALOG.route_product_analysis("office chair")

    assert route.agent_path == ("GenericProductAnalystAgent",)
    assert route.fallback_agent_names == ()


def test_agent_catalog_routes_broad_technology_categories_to_domain_agent() -> None:
    route = DEFAULT_AGENT_CATALOG.route_product_analysis("gaming mouse")

    assert route.agent_path == ("TechnologyDomainAnalystAgent",)
    assert route.fallback_agent_names == ("GenericProductAnalystAgent",)


@pytest.mark.parametrize(
    ("category", "specialist_name"),
    (
        ("monitor", "MonitorSpecialistAgent"),
        ("gaming monitor", "MonitorSpecialistAgent"),
        ("smartphone", "SmartphoneSpecialistAgent"),
        ("laptop", "LaptopSpecialistAgent"),
        ("headphones", "EarphonesHeadphonesSpecialistAgent"),
        ("tv", "TVSpecialistAgent"),
        ("smartwatch", "SmartwatchSpecialistAgent"),
    ),
)
def test_agent_catalog_routes_configured_mvp_technology_specialists(
    category: str,
    specialist_name: str,
) -> None:
    route = DEFAULT_AGENT_CATALOG.route_product_analysis(category)

    assert route.agent_path == ("TechnologyDomainAnalystAgent", specialist_name)
    assert route.fallback_agent_names == (
        "TechnologyDomainAnalystAgent",
        "GenericProductAnalystAgent",
    )


def test_agent_catalog_exposes_required_reusable_source_tools() -> None:
    source_agents = DEFAULT_AGENT_CATALOG.reusable_source_agents()

    assert [agent.agent_name for agent in source_agents] == [
        "YouTubeReviewIntelligenceAgent",
        "RedditCommunityIntelligenceAgent",
        "AmazonProductIntelligenceAgent",
        "IKEAStoreIntelligenceAgent",
    ]
    assert all(agent.status == AgentStatus.REQUIRED_MVP for agent in source_agents)
    assert all(agent.kind == AgentKind.SOURCE_INTELLIGENCE for agent in source_agents)
    youtube, reddit, amazon, ikea = source_agents
    assert youtube.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
    assert youtube.sdk_implementation_pending is False
    assert {tool.value for tool in youtube.approved_sdk_tools} == {
        "search_videos",
        "read_video_metadata",
        "read_video_transcript",
    }
    assert reddit.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
    assert reddit.sdk_implementation_pending is False
    assert {tool.value for tool in reddit.approved_sdk_tools} == {
        "search_community_discussions",
        "read_community_discussion",
    }
    assert amazon.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
    assert amazon.sdk_implementation_pending is False
    assert {tool.value for tool in amazon.approved_sdk_tools} == {
        "search_amazon_products",
        "read_amazon_product",
    }
    assert ikea.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
    assert ikea.sdk_implementation_pending is False
    assert {tool.value for tool in ikea.approved_sdk_tools} == {
        "search_ikea_products",
        "read_ikea_product",
    }
    assert all(agent.agent_as_tool_available for agent in source_agents)
    assert all(agent.approved_sdk_tools for agent in source_agents)
    assert all(not agent.planned_sdk_tools for agent in source_agents)
    assert all(agent.provider_service_name for agent in source_agents)
    assert all(agent.run_profile == AgentRunProfileName.FAST for agent in source_agents)
    assert all(agent.is_reusable_source_agent is True for agent in source_agents)
    assert [agent.output_schema for agent in source_agents] == [
        "VideoReviewEvidenceBundle",
        "CommunityDiscussionEvidenceBundle",
        "AmazonProductEvidenceBundle",
        "IKEAStoreEvidenceBundle",
    ]

    provider_requirement_names = {
        requirement
        for agent in source_agents
        for requirement in agent.provider_requirements
    }
    assert "youtube_data_api_optional" in provider_requirement_names
    assert "reddit_community_discussion_provider_optional" in (
        provider_requirement_names
    )
    assert "amazon_product_intelligence_provider_optional" in (
        provider_requirement_names
    )
    assert "ikea_regional_official_store_provider_optional" in (
        provider_requirement_names
    )
    assert "youtube_video_metadata_provider_optional" not in (
        provider_requirement_names
    )
    assert (
        "marketplace_availability_provider_optional" not in provider_requirement_names
    )


def test_pending_source_agent_cannot_claim_sdk_tool_or_agent_as_tool_access() -> None:
    entry = DEFAULT_AGENT_CATALOG.require("IKEAStoreIntelligenceAgent")
    pending = {
        **entry.model_dump(),
        "sdk_implementation_pending": True,
        "invocation_mode": InvocationMode.NOT_IMPLEMENTED,
        "approved_sdk_tools": (),
    }
    with pytest.raises(ValidationError, match="pending SDK agents"):
        type(entry).model_validate({**pending, "approved_sdk_tools": ["search_videos"]})
    with pytest.raises(ValidationError, match="pending SDK agents"):
        type(entry).model_validate({**pending, "agent_as_tool_available": True})


def test_ikea_source_agent_has_explicit_fast_profile_and_bounded_tools() -> None:
    entry = DEFAULT_AGENT_CATALOG.require("IKEAStoreIntelligenceAgent")
    assert entry.run_profile == AgentRunProfileName.FAST
    assert entry.approved_sdk_tools == (
        ApprovedSDKTool.SEARCH_IKEA_PRODUCTS,
        ApprovedSDKTool.READ_IKEA_PRODUCT,
    )
    assert entry.agent_as_tool_available is True


def test_amazon_source_agent_has_explicit_fast_profile_and_bounded_tools() -> None:
    entry = DEFAULT_AGENT_CATALOG.require("AmazonProductIntelligenceAgent")
    assert entry.sdk_implementation_pending is False
    assert entry.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
    assert entry.run_profile == AgentRunProfileName.FAST
    assert entry.approved_sdk_tools == (
        ApprovedSDKTool.SEARCH_AMAZON_PRODUCTS,
        ApprovedSDKTool.READ_AMAZON_PRODUCT,
    )
    assert entry.agent_as_tool_available is True


def test_agent_catalog_exposes_guided_intake_and_guardrail_contracts() -> None:
    guide = DEFAULT_AGENT_CATALOG.require("ShoppingGuideAgent")
    guardrail = DEFAULT_AGENT_CATALOG.require("ShoppingScopeGuardrail")

    assert guide.status == AgentStatus.REQUIRED_MVP
    assert guide.kind == AgentKind.GUIDE
    assert guide.invocation_mode == InvocationMode.TYPED_STEP
    assert guide.contract_name == "ShoppingGuideAgent"
    assert guide.output_schema == "GuidedIntakeState"

    assert guardrail.status == AgentStatus.REQUIRED_MVP
    assert guardrail.kind == AgentKind.GUARDRAIL
    assert guardrail.invocation_mode == InvocationMode.TYPED_STEP
    assert guardrail.contract_name == "ShoppingScopeGuardrail"
    assert guardrail.output_schema == "ShoppingGuardrailResult"


def test_agent_catalog_exposes_category_router_contract() -> None:
    router = DEFAULT_AGENT_CATALOG.require("CategoryRouterAgent")

    assert router.status == AgentStatus.REQUIRED_MVP
    assert router.kind == AgentKind.ROUTER
    assert router.invocation_mode == InvocationMode.TYPED_STEP
    assert router.contract_name == "CategoryRouterAgent"
    assert router.output_schema == "ProductAnalysisRoute"


def test_agent_catalog_declares_agent_owned_research_and_extraction() -> None:
    discovery = DEFAULT_AGENT_CATALOG.require("DiscoveryAgent")
    extraction = DEFAULT_AGENT_CATALOG.require("ExtractionAgent")
    legacy = DEFAULT_AGENT_CATALOG.require("ExtractionReviewAgent")

    assert set(discovery.target_research_decisions) == {
        ResearchDecision.SOURCE_CLASSIFICATION,
        ResearchDecision.SOURCE_RELEVANCE,
        ResearchDecision.CANDIDATE_IDENTIFICATION,
        ResearchDecision.FOLLOW_UP_SEARCH,
    }
    assert discovery.planned_tool_boundaries == (
        "SearchProvider",
        "ExtractionProvider",
    )
    assert set(extraction.target_research_decisions) == {
        ResearchDecision.PAGE_SHAPE_INTERPRETATION,
        ResearchDecision.MULTI_PRODUCT_EXTRACTION,
        ResearchDecision.REVIEW_TO_CANDIDATE,
        ResearchDecision.EVIDENCE_INTERPRETATION,
    }
    assert extraction.invocation_mode == InvocationMode.TYPED_STEP
    assert extraction.contract_name == "ExtractionAgent"
    assert extraction.output_schema == "ExtractionAgentOutput"
    assert extraction.planned_tool_boundaries == (
        "SourceSnapshotReader",
        "MechanicalExtractionHelpers",
    )
    assert legacy.status == AgentStatus.TRANSITIONAL
    assert legacy.superseded_by == extraction.agent_name
    assert legacy.target_research_decisions == ()


def test_research_fixture_preserves_review_and_generic_provider_shapes() -> None:
    fixture_path = (
        Path(__file__).parent / "fixtures/providers/agent_research_source_shapes.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture["shopper_query"] == "Which TV should I buy?"
    assert [result["source_type"] for result in fixture["results"]] == [
        "professional_review",
        *("search_result",) * 5,
    ]
    assert all(result["url"].startswith("https://") for result in fixture["results"])


def test_agent_catalog_requires_explicit_entries_for_specialist_routes() -> None:
    with pytest.raises(ValidationError, match="unknown category route agent"):
        AgentCatalog(
            entries=DEFAULT_AGENT_CATALOG.entries,
            product_category_routes={"mouse": "MouseSpecialistAgent"},
            technology_category_keywords=(
                DEFAULT_AGENT_CATALOG.technology_category_keywords
            ),
            reusable_source_agent_names=(
                DEFAULT_AGENT_CATALOG.reusable_source_agent_names
            ),
        )


def test_agent_catalog_requires_explicit_entries_for_reusable_source_agents() -> None:
    with pytest.raises(ValidationError, match="unknown source agent"):
        AgentCatalog(
            entries=DEFAULT_AGENT_CATALOG.entries,
            product_category_routes=DEFAULT_AGENT_CATALOG.product_category_routes,
            technology_category_keywords=(
                DEFAULT_AGENT_CATALOG.technology_category_keywords
            ),
            reusable_source_agent_names=("OfficialBrandStoreAgent",),
        )
