from app.agents.catalog import DEFAULT_AGENT_CATALOG


def test_option_set_contract_preserves_existing_owners_and_fallbacks():
    catalog = DEFAULT_AGENT_CATALOG
    for name in (
        "GeneralShoppingAgent", "TechnologyDomainAnalystAgent", "SmartphoneSpecialistAgent",
        "LaptopSpecialistAgent", "ComparisonDecisionAgent",
    ):
        entry = catalog.require(name)
        assert "BuyerComparativeOptionSet" in entry.planned_tool_boundaries
        assert "SourceDecisionProjection" in entry.planned_tool_boundaries
    assert catalog.route_product_analysis("smartphone").agent_path == (
        "TechnologyDomainAnalystAgent", "SmartphoneSpecialistAgent",
    )
    assert catalog.route_product_analysis("handmade ceramic tea scoop").agent_path == (
        "GenericProductAnalystAgent",
    )
