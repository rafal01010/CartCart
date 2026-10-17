from app.agents.catalog import DEFAULT_AGENT_CATALOG


def test_selected_source_and_shared_video_contracts_keep_existing_routes():
    catalog = DEFAULT_AGENT_CATALOG
    for name in ("GeneralShoppingAgent", "ComparisonDecisionAgent"):
        assert "SourceDecisionProjection" in catalog.require(name).planned_tool_boundaries
    for name in ("SourceIntelligenceManagerAgent", "YouTubeReviewIntelligenceAgent"):
        assert "SharedRunVideoWork" in catalog.require(name).planned_tool_boundaries
    phone = catalog.route_product_analysis("smartphone")
    assert phone.agent_path == ("TechnologyDomainAnalystAgent", "SmartphoneSpecialistAgent")
    assert phone.fallback_agent_names == ("TechnologyDomainAnalystAgent", "GenericProductAnalystAgent")
    unknown = catalog.route_product_analysis("handmade ceramic tea scoop")
    assert unknown.agent_path == ("GenericProductAnalystAgent",)
    assert unknown.fallback_agent_names == ()
