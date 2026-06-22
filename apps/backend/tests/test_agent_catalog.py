import pytest
from pydantic import ValidationError

from app.agents import (
    DEFAULT_AGENT_CATALOG,
    AgentCatalog,
    AgentKind,
    AgentStatus,
    InvocationMode,
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
    assert all(
        agent.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
        for agent in source_agents
    )
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
    assert "marketplace_availability_provider_optional" not in provider_requirement_names


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
