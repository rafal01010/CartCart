from hashlib import sha256
from pathlib import Path

import pytest

from app.schemas.search_sources import (
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    RawSourceSnapshotArtifact,
    SourceSnapshot,
    SourceType,
)
from app.services.source_extraction import (
    DynamicExtractionPolicy,
    ExtractionDecisionAction,
    ExtractionDecisionReason,
    StaticPageExtractionError,
    StaticPageTextExtractor,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "extraction"


def test_static_page_text_extractor_stores_usable_text_and_metadata(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_from_fixture(tmp_path, "static_product_page.html")

    extracted = StaticPageTextExtractor(snapshot_dir=tmp_path).extract(snapshot)

    assert snapshot.extraction_status == ExtractionStatus.NOT_ATTEMPTED
    assert extracted.extraction_status == ExtractionStatus.SUCCEEDED
    assert extracted.title == "Northstar 27 USB-C Monitor Review"
    assert extracted.extracted_content is not None
    assert "90 watt USB-C charging port" in extracted.extracted_content.text
    assert "three-year limited warranty" in extracted.extracted_content.text
    assert extracted.extracted_content.extractor == "trafilatura"
    assert extracted.extracted_content.author == "Jamie Rivera"
    assert extracted.extracted_content.description is not None
    assert extracted.extracted_content.site_name == "Fixture Reviews"
    assert extracted.extracted_content.published_date == "2026-05-10"
    assert extracted.extracted_content.word_count >= 70

    restored = SourceSnapshot.model_validate(extracted.model_dump(mode="json"))
    assert restored.extracted_content == extracted.extracted_content


def test_static_page_text_extractor_marks_page_without_text_as_failed(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_from_fixture(tmp_path, "static_empty_page.html")

    extracted = StaticPageTextExtractor(snapshot_dir=tmp_path).extract(snapshot)

    assert extracted.extraction_status == ExtractionStatus.FAILED
    assert extracted.extracted_content is None


def test_static_page_text_extractor_requires_stored_artifact(tmp_path: Path) -> None:
    snapshot = SourceSnapshot(
        url="https://example.com/no-artifact",
        source_type=SourceType.OTHER,
        provider=ProviderMetadata(provider_name="fixture"),
    )

    with pytest.raises(StaticPageExtractionError):
        StaticPageTextExtractor(snapshot_dir=tmp_path).extract(snapshot)


def test_dynamic_policy_always_attempts_static_extraction_first() -> None:
    snapshot = SourceSnapshot(
        url="https://example.com/product",
        source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="fixture"),
    )

    decision = DynamicExtractionPolicy(
        dynamic_fallback_enabled=True
    ).decide(snapshot)

    assert decision.action == ExtractionDecisionAction.RUN_STATIC
    assert decision.reason == ExtractionDecisionReason.STATIC_NOT_ATTEMPTED
    assert decision.dynamic_fallback_optional is True


def test_dynamic_policy_accepts_usable_static_extraction(tmp_path: Path) -> None:
    snapshot = _snapshot_from_fixture(tmp_path, "static_product_page.html")
    extracted = StaticPageTextExtractor(snapshot_dir=tmp_path).extract(snapshot)

    decision = DynamicExtractionPolicy(
        dynamic_fallback_enabled=True
    ).decide(extracted)

    assert decision.action == ExtractionDecisionAction.ACCEPT_STATIC
    assert decision.reason == ExtractionDecisionReason.STATIC_SUFFICIENT
    assert decision.uses_dynamic_fallback is False


def test_dynamic_policy_keeps_failed_fallback_optional_by_default() -> None:
    snapshot = SourceSnapshot(
        url="https://example.com/client-rendered-product",
        source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="fixture"),
        extraction_status=ExtractionStatus.FAILED,
    )

    decision = DynamicExtractionPolicy().decide(snapshot)

    assert decision.action == ExtractionDecisionAction.STOP
    assert decision.reason == ExtractionDecisionReason.STATIC_FAILED
    assert decision.dynamic_fallback_optional is True
    assert decision.uses_dynamic_fallback is False


@pytest.mark.parametrize(
    ("status", "word_count", "expected_reason"),
    [
        (ExtractionStatus.FAILED, None, ExtractionDecisionReason.STATIC_FAILED),
        (ExtractionStatus.PARTIAL, 120, ExtractionDecisionReason.STATIC_PARTIAL),
        (ExtractionStatus.SUCCEEDED, 12, ExtractionDecisionReason.STATIC_TOO_SPARSE),
    ],
)
def test_dynamic_policy_can_request_optional_fallback_after_weak_static_result(
    status: ExtractionStatus,
    word_count: int | None,
    expected_reason: ExtractionDecisionReason,
) -> None:
    snapshot = SourceSnapshot(
        url="https://example.com/client-rendered-product",
        source_type=SourceType.PRODUCT_PAGE,
        provider=ProviderMetadata(provider_name="fixture"),
        extraction_status=status,
        extracted_content=(
            None
            if word_count is None
            else _extracted_content(word_count=word_count)
        ),
    )

    decision = DynamicExtractionPolicy(
        dynamic_fallback_enabled=True
    ).decide(snapshot)

    assert decision.action == ExtractionDecisionAction.TRY_DYNAMIC
    assert decision.reason == expected_reason
    assert decision.dynamic_fallback_optional is True
    assert decision.uses_dynamic_fallback is True


@pytest.mark.parametrize(
    ("source_type", "status", "expected_reason"),
    [
        (
            SourceType.SEARCH_RESULT,
            ExtractionStatus.NOT_ATTEMPTED,
            ExtractionDecisionReason.SOURCE_NOT_HTML_PAGE,
        ),
        (
            SourceType.OTHER,
            ExtractionStatus.EXCLUDED,
            ExtractionDecisionReason.SOURCE_EXCLUDED,
        ),
    ],
)
def test_dynamic_policy_does_not_browse_non_page_or_excluded_sources(
    source_type: SourceType,
    status: ExtractionStatus,
    expected_reason: ExtractionDecisionReason,
) -> None:
    snapshot = SourceSnapshot(
        url="https://example.com/source",
        source_type=source_type,
        provider=ProviderMetadata(provider_name="fixture"),
        extraction_status=status,
    )

    decision = DynamicExtractionPolicy(
        dynamic_fallback_enabled=True
    ).decide(snapshot)

    assert decision.action == ExtractionDecisionAction.STOP
    assert decision.reason == expected_reason


def _snapshot_from_fixture(tmp_path: Path, fixture_name: str) -> SourceSnapshot:
    content = (FIXTURE_DIR / fixture_name).read_bytes()
    artifact_path = Path("2026/06/14") / fixture_name
    stored_path = tmp_path / artifact_path
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(content)
    return SourceSnapshot(
        url=f"https://example.com/{fixture_name}",
        source_type=SourceType.PROFESSIONAL_REVIEW,
        provider=ProviderMetadata(provider_name="http-fetch"),
        http_status_code=200,
        raw_artifact=RawSourceSnapshotArtifact(
            path=artifact_path.as_posix(),
            content_type="text/html",
            size_bytes=len(content),
            sha256=sha256(content).hexdigest(),
        ),
    )


def _extracted_content(*, word_count: int) -> ExtractedPageContent:
    return ExtractedPageContent(
        text="word " * word_count,
        extractor="fixture",
        word_count=word_count,
    )
