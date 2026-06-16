from hashlib import sha256
from pathlib import Path

import pytest

from app.schemas import (
    CanonicalProduct,
    ConflictSeverity,
    EvidenceType,
    ProviderMetadata,
    RawSourceSnapshotArtifact,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
    new_id,
)
from app.services.product_listing_extraction import ProductListingExtractor
from app.services.source_evidence_creation import (
    SourceEvidenceCreationError,
    SourceEvidenceCreator,
    SourceEvidenceInput,
)
from app.services.source_extraction import StaticPageTextExtractor


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "extraction"


def test_listing_extraction_facts_create_source_backed_typed_evidence(
    tmp_path: Path,
) -> None:
    snapshot = _extracted_snapshot(tmp_path, "product_listing_page.html")
    extraction = ProductListingExtractor().extract_source_snapshot(snapshot)

    result = SourceEvidenceCreator().create(
        (
            SourceEvidenceInput(
                snapshot=snapshot,
                product=extraction.product,
                listing=extraction.listing,
            ),
        )
    )

    assert {item.source_id for item in result.evidence} == {snapshot.source_id}
    assert {item.evidence_type for item in result.evidence} == {
        EvidenceType.PRODUCT_SPEC,
        EvidenceType.PRICE,
        EvidenceType.LISTING_IDENTITY,
        EvidenceType.REGION_AVAILABILITY,
    }
    assert result.conflicts == ()


def test_product_claims_require_the_exact_snapshot_source_reference(
    tmp_path: Path,
) -> None:
    snapshot = _extracted_snapshot(tmp_path, "review_positive_evidence.html")
    product = CanonicalProduct(
        name="Northstar Arc 27",
        source_ids=(new_id(),),
    )

    with pytest.raises(
        SourceEvidenceCreationError,
        match="product claims require the snapshot source ID",
    ):
        SourceEvidenceCreator().create(
            (SourceEvidenceInput(snapshot=snapshot, product=product),)
        )


def test_conflicting_fixture_evidence_is_retained_and_marked(
    tmp_path: Path,
) -> None:
    positive = _extracted_snapshot(tmp_path, "review_positive_evidence.html")
    negative = _extracted_snapshot(tmp_path, "review_negative_evidence.html")
    product = CanonicalProduct(
        name="Northstar Arc 27",
        source_ids=(positive.source_id, negative.source_id),
    )

    result = SourceEvidenceCreator().create(
        (
            SourceEvidenceInput(snapshot=positive, product=product),
            SourceEvidenceInput(snapshot=negative, product=product),
        )
    )

    contradictory = tuple(
        item
        for item in result.evidence
        if item.evidence_type in {EvidenceType.WARRANTY, EvidenceType.REVIEW_CLAIM}
    )
    assert len(contradictory) == 4
    assert {item.source_id for item in contradictory} == {
        positive.source_id,
        negative.source_id,
    }
    assert len(result.conflicts) == 2
    assert {conflict.severity for conflict in result.conflicts} == {
        ConflictSeverity.MATERIAL,
        ConflictSeverity.MEDIUM,
    }
    assert {
        evidence_id
        for conflict in result.conflicts
        for evidence_id in conflict.evidence_ids
    } == {item.evidence_id for item in contradictory}
    assert any(conflict.affects_decision for conflict in result.conflicts)


def _extracted_snapshot(tmp_path: Path, fixture_name: str) -> SourceSnapshot:
    content = (FIXTURE_DIR / fixture_name).read_bytes()
    artifact_path = Path("2026/06/14") / fixture_name
    stored_path = tmp_path / artifact_path
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(content)
    snapshot = SourceSnapshot(
        url=f"https://reviews.example/{fixture_name}",
        source_type=(
            SourceType.RETAILER_LISTING
            if fixture_name == "product_listing_page.html"
            else SourceType.PROFESSIONAL_REVIEW
        ),
        provider=ProviderMetadata(provider_name="fixture-fetch"),
        http_status_code=200,
        raw_artifact=RawSourceSnapshotArtifact(
            path=artifact_path.as_posix(),
            content_type="text/html",
            size_bytes=len(content),
            sha256=sha256(content).hexdigest(),
        ),
        quality=SourceQuality(
            level=SourceQualityLevel.STRONG,
            score=0.9,
            rationale="Established fixture source.",
        ),
    )
    return StaticPageTextExtractor(snapshot_dir=tmp_path).extract(snapshot)
