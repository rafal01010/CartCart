from pathlib import Path

from app.tools.export_openapi import export_openapi


def test_openapi_export_includes_current_endpoints_and_schemas(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "openapi.json"

    spec = export_openapi(output_path)

    assert output_path.exists()
    paths = spec["paths"]
    assert set(paths) >= {
        "/healthz",
        "/readyz",
        "/api/sessions",
        "/api/sessions/{session_id}",
        "/api/sessions/{session_id}/brief",
        "/api/sessions/{session_id}/runs",
        "/api/sessions/{session_id}/runs/{run_id}",
        "/api/sessions/{session_id}/runs/{run_id}/events",
        "/api/sessions/{session_id}/results",
        "/api/sessions/{session_id}/products",
        "/api/sessions/{session_id}/refinements",
    }

    schemas = spec["components"]["schemas"]
    assert set(schemas) >= {
        "ShoppingRunRecord",
        "AgentRunRecord",
        "CanonicalProduct",
        "ProductListing",
        "ListingTrustAssessment",
        "CategoryAnalysis",
        "RecommendationBundle",
        "CreateSessionRequest-Input",
        "CreateUserAddedProductRequest",
        "RefinementRunResponse",
        "SessionResultsResponse",
    }
