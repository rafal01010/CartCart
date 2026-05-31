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


def test_agent_catalog_exposes_reusable_source_agent_availability() -> None:
    source_agents = DEFAULT_AGENT_CATALOG.reusable_source_agents()

    assert [agent.agent_name for agent in source_agents] == [
        "YouTubeReviewIntelligenceAgent"
    ]
    youtube_agent = source_agents[0]
    assert youtube_agent.status == AgentStatus.CANDIDATE_MVP
    assert youtube_agent.kind == AgentKind.SOURCE_INTELLIGENCE
    assert youtube_agent.invocation_mode == InvocationMode.REUSABLE_SOURCE_TOOL
    assert youtube_agent.is_reusable_source_agent is True
    assert "youtube_data_api_optional" in youtube_agent.provider_requirements


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
