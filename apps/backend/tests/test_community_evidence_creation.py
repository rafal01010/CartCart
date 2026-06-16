from datetime import UTC, datetime

import pytest

from app.schemas import (
    CanonicalProduct,
    CommunityDiscussionContext,
    CommunityDiscussionEvidenceBundle,
    EvidenceTarget,
    EvidenceTargetType,
    SourceQuality,
    SourceQualityLevel,
    new_id,
)
from app.schemas.source_references import SourceReference
from app.services.community_evidence_creation import (
    CommunityEvidenceCreationError,
    CommunityEvidenceCreator,
    SourceBackedCommunityClaim,
)


def test_recurring_complaint_preserves_all_supporting_discussion_references() -> None:
    product = CanonicalProduct(name="Fixture Chair")
    first_source_id = new_id()
    second_source_id = new_id()
    recurring_claim = "the armrest padding wears down after several months"
    bundle = CommunityDiscussionEvidenceBundle(
        source_references=(
            SourceReference(
                source_id=first_source_id,
                url="https://www.reddit.com/r/OfficeChairs/comments/thread1/review/",
            ),
            SourceReference(
                source_id=second_source_id,
                url="https://www.reddit.com/r/OfficeChairs/comments/thread2/review/",
            ),
        ),
        discussions=(
            CommunityDiscussionContext(
                source_id=first_source_id,
                url="https://www.reddit.com/r/OfficeChairs/comments/thread1/review/",
                thread_id="thread1",
                posted_at=datetime(2026, 5, 1, tzinfo=UTC),
                comment_count=24,
                extracted_public_summary=(
                    f"Several owners say {recurring_claim}."
                ),
            ),
            CommunityDiscussionContext(
                source_id=second_source_id,
                url="https://www.reddit.com/r/OfficeChairs/comments/thread2/review/",
                thread_id="thread2",
                posted_at=datetime(2026, 4, 2, tzinfo=UTC),
                engagement_score=81,
                extracted_public_summary=(
                    f"Long-term users also report that {recurring_claim}."
                ),
            ),
        ),
    )

    created = CommunityEvidenceCreator(
        now=lambda: datetime(2026, 6, 14, tzinfo=UTC)
    ).create(
        bundle,
        (
            SourceBackedCommunityClaim(
                source_id=first_source_id,
                target=EvidenceTarget(
                    target_type=EvidenceTargetType.PRODUCT,
                    product_id=product.product_id,
                ),
                claim=recurring_claim,
                confidence={"score": 0.55, "level": "medium"},
                source_quality=SourceQuality(
                    level=SourceQualityLevel.ADEQUATE,
                    score=0.6,
                ),
                context_source_ids=(first_source_id, second_source_id),
                recurring_signal=True,
            ),
        ),
    )

    evidence = created.evidence[0]
    assert evidence.claim == recurring_claim
    assert evidence.recurring_signal is True
    assert evidence.qualitative_signal is True
    assert evidence.context_source_ids == (first_source_id, second_source_id)
    assert any("anecdotal" in warning for warning in evidence.evidence_quality_warnings)


def test_community_evidence_creator_rejects_fabricated_product_fact() -> None:
    product = CanonicalProduct(name="Fixture Chair")
    source_id = new_id()
    url = "https://www.reddit.com/r/OfficeChairs/comments/thread1/review/"
    bundle = CommunityDiscussionEvidenceBundle(
        source_references=(SourceReference(source_id=source_id, url=url),),
        discussions=(
            CommunityDiscussionContext(
                source_id=source_id,
                url=url,
                extracted_public_summary="An owner discusses seat comfort.",
            ),
        ),
    )

    with pytest.raises(
        CommunityEvidenceCreationError,
        match="must appear in every cited public discussion summary",
    ):
        CommunityEvidenceCreator().create(
            bundle,
            (
                SourceBackedCommunityClaim(
                    source_id=source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.PRODUCT,
                        product_id=product.product_id,
                    ),
                    claim="The chair includes a ten-year warranty.",
                    confidence={"score": 0.8, "level": "high"},
                    source_quality=SourceQuality(
                        level=SourceQualityLevel.ADEQUATE
                    ),
                    context_source_ids=(source_id,),
                ),
            ),
        )
