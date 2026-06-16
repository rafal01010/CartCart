from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Callable

from pydantic import Field

from app.schemas.base import CartCartBaseModel
from app.schemas.confidence import Confidence
from app.schemas.ids import SourceId
from app.schemas.search_sources import (
    CommunityDiscussionContext,
    CommunityDiscussionEvidence,
    CommunityDiscussionEvidenceBundle,
    EvidenceTarget,
    SourceQuality,
)


_RECENT_WINDOW = timedelta(days=365)
_ANECDOTAL_WARNING = "Community content is anecdotal and may be biased or manipulated."
_CORROBORATION_WARNING = (
    "Do not use Reddit alone for specifications, warranty, price, or availability."
)


class CommunityEvidenceCreationError(ValueError):
    """Raised when community evidence is not grounded in bundled discussion text."""


class SourceBackedCommunityClaim(CartCartBaseModel):
    source_id: SourceId
    target: EvidenceTarget
    claim: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    source_quality: SourceQuality
    context_source_ids: tuple[SourceId, ...] = Field(min_length=1)
    recurring_signal: bool = False
    evidence_quality_warnings: tuple[str, ...] = Field(default_factory=tuple)


class CommunityEvidenceCreator:
    """Create qualitative claims only from cited public discussion summaries."""

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))

    def create(
        self,
        bundle: CommunityDiscussionEvidenceBundle,
        claims: tuple[SourceBackedCommunityClaim, ...] = (),
    ) -> CommunityDiscussionEvidenceBundle:
        source_ids = {reference.source_id for reference in bundle.source_references}
        discussions = {
            discussion.source_id: discussion for discussion in bundle.discussions
        }
        evidence = list(bundle.evidence)

        for claim in claims:
            if claim.source_id not in source_ids:
                raise CommunityEvidenceCreationError(
                    "community claims must reference a bundled source."
                )
            if claim.source_id not in claim.context_source_ids:
                raise CommunityEvidenceCreationError(
                    "community claims must cite their primary source context."
                )

            cited_discussions = _cited_discussions(claim, discussions)
            if not all(
                _claim_is_source_backed(claim.claim, discussion)
                for discussion in cited_discussions
            ):
                raise CommunityEvidenceCreationError(
                    "community claims must appear in every cited public discussion summary."
                )

            warnings = _evidence_warnings(
                cited_discussions,
                now=self._now(),
                recurring_signal=claim.recurring_signal,
                supplied=claim.evidence_quality_warnings,
            )
            evidence.append(
                CommunityDiscussionEvidence(
                    source_id=claim.source_id,
                    target=claim.target,
                    claim=claim.claim,
                    confidence=claim.confidence,
                    source_quality=claim.source_quality,
                    context_source_ids=claim.context_source_ids,
                    recurring_signal=claim.recurring_signal,
                    qualitative_signal=True,
                    evidence_quality_warnings=warnings,
                )
            )

        return bundle.model_copy(update={"evidence": tuple(evidence)})


def _cited_discussions(
    claim: SourceBackedCommunityClaim,
    discussions: dict[SourceId, CommunityDiscussionContext],
) -> tuple[CommunityDiscussionContext, ...]:
    cited: list[CommunityDiscussionContext] = []
    for source_id in dict.fromkeys(claim.context_source_ids):
        discussion = discussions.get(source_id)
        if discussion is None:
            raise CommunityEvidenceCreationError(
                "community claims must cite bundled discussion contexts."
            )
        if discussion.extracted_public_summary is None:
            raise CommunityEvidenceCreationError(
                "community claims require usable public discussion text."
            )
        cited.append(discussion)
    return tuple(cited)


def _claim_is_source_backed(
    claim: str,
    discussion: CommunityDiscussionContext,
) -> bool:
    summary = discussion.extracted_public_summary
    if summary is None:
        return False
    return _normalize_text(claim) in _normalize_text(summary)


def _evidence_warnings(
    discussions: tuple[CommunityDiscussionContext, ...],
    *,
    now: datetime,
    recurring_signal: bool,
    supplied: tuple[str, ...],
) -> tuple[str, ...]:
    warnings = [*supplied, _ANECDOTAL_WARNING, _CORROBORATION_WARNING]
    if any(discussion.posted_at is None for discussion in discussions):
        warnings.append("Discussion recency was unavailable.")
    if any(
        discussion.posted_at is not None
        and discussion.posted_at < now - _RECENT_WINDOW
        for discussion in discussions
    ):
        warnings.append("At least one cited discussion is older than one year.")
    if any(
        discussion.engagement_score is None and discussion.comment_count is None
        for discussion in discussions
    ):
        warnings.append("Discussion engagement metadata was unavailable.")
    if recurring_signal and len(discussions) == 1:
        warnings.append(
            "The recurring signal comes from one discussion context and is not "
            "corroborated across separate threads."
        )
    return tuple(dict.fromkeys(warnings))


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())
