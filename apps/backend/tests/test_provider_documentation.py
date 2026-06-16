from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PROVIDER_DOCS = REPO_ROOT / "docs" / "PROVIDERS.md"


@pytest.mark.parametrize(
    "required_text",
    (
        "## Provider Boundaries",
        "## Fixture, Live, And Disabled Behavior",
        "## Environment Variables",
        "## Fixture Replay",
        "## Compliance Constraints",
        "## Storage Boundaries",
        "## Section J Fixture Gate",
        "CARTCART_SEARCH_PROVIDER",
        "CARTCART_EXTRACTION_PROVIDER",
        "CARTCART_VIDEO_SEARCH_PROVIDER",
        "CARTCART_TRANSCRIPT_PROVIDER",
        "CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER",
        "CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER",
        "CARTCART_RECORD_PROVIDER_FIXTURES",
        "CARTCART_RUN_LIVE_PROVIDER_TESTS",
    ),
)
def test_provider_docs_cover_setup_and_safety_contract(required_text: str) -> None:
    content = PROVIDER_DOCS.read_text(encoding="utf-8")

    assert required_text in content


def test_provider_docs_do_not_advertise_removed_fake_only_runtime_values() -> None:
    content = PROVIDER_DOCS.read_text(encoding="utf-8")

    assert "CARTCART_EXTRACTION_PROVIDER=disabled|fixture|tavily" not in content
    assert "CARTCART_SHOPPING_PROVIDER" not in content
