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


def test_phone_owner_declares_current_research_and_failure_boundaries() -> None:
    phone = DEFAULT_AGENT_CATALOG.require("SmartphoneSpecialistAgent")
    assert {
        "CurrentRegionalResearchGuidance",
        "ShoppingRunFailureReporting",
        "PhoneReleaseAndLaunchGuidance",
    }.issubset(phone.planned_tool_boundaries)
    assert phone.parent_agent_name == "TechnologyDomainAnalystAgent"
    assert ApprovedSDKTool.HOSTED_WEB_SEARCH in phone.approved_sdk_tools


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
        ApprovedSDKTool.HOSTED_WEB_SEARCH,
        ApprovedSDKTool.COMPLETE_RESEARCH_RESULT,
        ApprovedSDKTool.READ_RESEARCH_RESULT,
        ApprovedSDKTool.READ_SEARCH_RESULTS,
    )
    assert DEFAULT_AGENT_CATALOG.require("DiscoveryAgent").planned_sdk_tools == ()
    assert DEFAULT_AGENT_CATALOG.require("QueryPlannerAgent").approved_sdk_tools == (
        ApprovedSDKTool.READ_RESEARCH_RESULT,
    )
    assert DEFAULT_AGENT_CATALOG.require("VerifierCriticAgent").approved_sdk_tools == (
        ApprovedSDKTool.READ_SOURCE_SNAPSHOT,
        ApprovedSDKTool.COMPLETE_RESEARCH_RESULT,
        ApprovedSDKTool.READ_RESEARCH_RESULT,
    )
    assert DEFAULT_AGENT_CATALOG.require("ExtractionAgent").approved_sdk_tools == (
        ApprovedSDKTool.READ_SOURCE_SNAPSHOT,
        ApprovedSDKTool.COMPLETE_RESEARCH_RESULT,
        ApprovedSDKTool.READ_RESEARCH_RESULT,
    )


def test_fixture_research_fallbacks_are_explicit_in_catalog() -> None:
    assert DEFAULT_AGENT_CATALOG.require("DiscoveryAgent").fixture_fallback == (
        FixtureFallback.UNCERTAIN_SOURCE
    )
    assert DEFAULT_AGENT_CATALOG.require("ExtractionAgent").fixture_fallback == (
        FixtureFallback.EVIDENCE_GAP
    )


@pytest.mark.parametrize("category", ("office chair", "phonebook", "megaphones"))
def test_agent_catalog_routes_unknown_categories_to_generic_fallback(
    category: str,
) -> None:
    route = DEFAULT_AGENT_CATALOG.route_product_analysis(category)

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
        ("phones", "SmartphoneSpecialistAgent"),
        ("smartphones", "SmartphoneSpecialistAgent"),
        ("mobile phones", "SmartphoneSpecialistAgent"),
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


def test_technology_handoff_targets_are_terminal_approved_specialists() -> None:
    technology = DEFAULT_AGENT_CATALOG.require("TechnologyDomainAnalystAgent")
    assert len(technology.target_handoff_agent_names) == 6
    for name in technology.target_handoff_agent_names:
        specialist = DEFAULT_AGENT_CATALOG.require(name)
        assert specialist.parent_agent_name == technology.agent_name
        assert specialist.target_can_finish_shopper_request
        assert specialist.target_handoff_agent_names == ()
        assert specialist.fallback_agent_names[0] == technology.agent_name
        assert specialist.run_profile == AgentRunProfileName.STRONG


def test_catalog_rejects_cyclic_shopper_owner_handoffs() -> None:
    payload = DEFAULT_AGENT_CATALOG.model_dump(mode="python")
    payload["entries"]["SmartphoneSpecialistAgent"]["target_handoff_agent_names"] = (
        "TechnologyDomainAnalystAgent",
    )
    with pytest.raises(ValidationError, match="acyclic"):
        AgentCatalog.model_validate(payload)


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
    assert youtube.fixture_fallback == FixtureFallback.EVIDENCE_GAP
    assert {tool.value for tool in youtube.approved_sdk_tools} == {
        "search_videos",
        "read_video_metadata",
        "read_video_transcript",
        "hosted_web_search",
        "complete_research_result",
        "read_research_result",
    }
    assert reddit.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
    assert reddit.sdk_implementation_pending is False
    assert {tool.value for tool in reddit.approved_sdk_tools} == {
        "search_community_discussions",
        "read_community_discussion",
        "hosted_web_search",
        "complete_research_result",
        "read_research_result",
    }
    assert amazon.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
    assert amazon.sdk_implementation_pending is False
    assert {tool.value for tool in amazon.approved_sdk_tools} == {
        "search_amazon_products",
        "read_amazon_product",
        "hosted_web_search",
        "complete_research_result",
        "read_research_result",
    }
    assert ikea.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
    assert ikea.sdk_implementation_pending is False
    assert {tool.value for tool in ikea.approved_sdk_tools} == {
        "search_ikea_products",
        "read_ikea_product",
        "hosted_web_search",
        "complete_research_result",
        "read_research_result",
    }
    assert all(agent.agent_as_tool_available for agent in source_agents)
    assert all(agent.approved_sdk_tools for agent in source_agents)
    assert all(agent.planned_sdk_tools == () for agent in source_agents)
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
        ApprovedSDKTool.HOSTED_WEB_SEARCH,
        ApprovedSDKTool.COMPLETE_RESEARCH_RESULT,
        ApprovedSDKTool.READ_RESEARCH_RESULT,
    )
    assert entry.agent_as_tool_available is True


def test_target_owner_graph_is_distinct_from_current_analysis_routes() -> None:
    catalog = DEFAULT_AGENT_CATALOG
    general = catalog.require(catalog.target_general_owner_agent_name)
    technology = catalog.require(catalog.technology_domain_agent_name)
    specialists = technology.target_handoff_agent_names

    assert general.invocation_mode == InvocationMode.TYPED_STEP
    assert general.sdk_implementation_pending is False
    assert general.target_handoff_agent_names == (technology.agent_name,)
    assert general.target_can_finish_shopper_request
    assert technology.target_can_finish_shopper_request
    assert len(specialists) == 6
    assert all(
        catalog.require(name).target_can_finish_shopper_request for name in specialists
    )
    assert all(
        not catalog.require(name).target_handoff_agent_names for name in specialists
    )
    assert catalog.route_product_analysis("wooden cane").agent_path == (
        "GenericProductAnalystAgent",
    )
    assert catalog.route_product_analysis("smartphone").agent_path == (
        "TechnologyDomainAnalystAgent",
        "SmartphoneSpecialistAgent",
    )


def test_hosted_search_access_by_role() -> None:
    catalog = DEFAULT_AGENT_CATALOG
    research_roles = {
        "DiscoveryAgent",
        "GeneralShoppingAgent",
        "TechnologyDomainAnalystAgent",
        "MonitorSpecialistAgent",
        "SmartphoneSpecialistAgent",
        "LaptopSpecialistAgent",
        "EarphonesHeadphonesSpecialistAgent",
        "TVSpecialistAgent",
        "SmartwatchSpecialistAgent",
        "SellerListingTrustAgent",
        *catalog.reusable_source_agent_names,
    }
    for name, entry in catalog.entries.items():
        assert ApprovedSDKTool.HOSTED_WEB_SEARCH not in entry.planned_sdk_tools
        assert (ApprovedSDKTool.HOSTED_WEB_SEARCH in entry.approved_sdk_tools) == (
            name in research_roles
        )
    assert (
        ApprovedSDKTool.RECORD_SOURCE_QUOTE
        in catalog.require("GeneralShoppingAgent").approved_sdk_tools
    )
    technology = catalog.require("TechnologyDomainAnalystAgent")
    assert {
        ApprovedSDKTool.SEARCH_SOURCES,
        ApprovedSDKTool.FETCH_SOURCE,
        ApprovedSDKTool.RECORD_SOURCE_QUOTE,
    }.issubset(set(technology.approved_sdk_tools))
    assert ApprovedSDKTool.HOSTED_WEB_SEARCH in technology.approved_sdk_tools
    assert not catalog.require(
        "SourceIntelligenceManagerAgent"
    ).target_can_finish_shopper_request
    assert not catalog.require(
        "ComparisonDecisionAgent"
    ).target_can_finish_shopper_request
    assert not catalog.require(
        "GenericProductAnalystAgent"
    ).target_can_finish_shopper_request


def test_target_handoffs_must_point_to_request_owners() -> None:
    catalog = DEFAULT_AGENT_CATALOG
    entries = {name: entry.model_dump() for name, entry in catalog.entries.items()}
    entries["GeneralShoppingAgent"]["target_handoff_agent_names"] = (
        "SourceIntelligenceManagerAgent",
    )
    with pytest.raises(ValidationError, match="shopper-request owner"):
        AgentCatalog.model_validate({**catalog.model_dump(), "entries": entries})


def test_amazon_source_agent_has_explicit_fast_profile_and_bounded_tools() -> None:
    entry = DEFAULT_AGENT_CATALOG.require("AmazonProductIntelligenceAgent")
    assert entry.sdk_implementation_pending is False
    assert entry.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
    assert entry.run_profile == AgentRunProfileName.FAST
    assert entry.approved_sdk_tools == (
        ApprovedSDKTool.SEARCH_AMAZON_PRODUCTS,
        ApprovedSDKTool.READ_AMAZON_PRODUCT,
        ApprovedSDKTool.HOSTED_WEB_SEARCH,
        ApprovedSDKTool.COMPLETE_RESEARCH_RESULT,
        ApprovedSDKTool.READ_RESEARCH_RESULT,
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
        "BoundedEvidenceContext",
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
        "BoundedEvidenceContext",
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


def test_reusable_source_catalog_preserves_live_unavailable_provider_boundary() -> None:
    for name in DEFAULT_AGENT_CATALOG.reusable_source_agent_names:
        entry = DEFAULT_AGENT_CATALOG.require(name)
        assert "LiveProviderEvidenceGaps" in entry.planned_tool_boundaries


def test_stage_catalog_allows_shared_original_context_lookup() -> None:
    from app.agents.research_history import history_tools

    lookup = history_tools()[1]
    for entry in DEFAULT_AGENT_CATALOG.entries.values():
        if "BoundedEvidenceContext" not in entry.planned_tool_boundaries:
            continue
        approved = [tool.value for tool in entry.approved_sdk_tools]
        assert lookup.name in approved
        assert len(approved) == len(set(approved))
