from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.providers.contracts import (
    CommunityDiscussionProviderOptions,
    CommunityDiscussionProviderResult,
    ProviderCapabilityFlags,
    ProviderRunStatus,
    SearchProvider,
    SearchProviderOptions,
    SourceAllowAvoidPolicy,
    SourcePolicyAction,
    SourcePolicyRule,
)
from app.providers.source_quality import (
    SourceEvidenceContext,
    SourceQualityMetadata,
    normalize_source_url,
    score_source_quality,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.products import CanonicalProduct
from app.schemas.search_sources import (
    CommunityDiscussionContext,
    CommunityDiscussionEvidenceBundle,
    EvidenceTarget,
    EvidenceTargetType,
    SearchIntent,
    SearchQuery,
    SearchResult,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
    SourceType,
)
from app.schemas.source_references import SourceReference
from app.services.community_evidence_creation import (
    CommunityEvidenceCreator,
    SourceBackedCommunityClaim,
)


_REDDIT_THREAD_PATH = re.compile(
    r"^/r/(?P<community>[^/]+)/comments/(?P<thread_id>[^/]+)"
    r"(?:/[^/]+)?(?:/(?P<comment_id>[^/]+))?/?$",
    re.IGNORECASE,
)
_LOW_QUALITY_MARKERS = (
    "[deleted]",
    "[removed]",
    "deleted by user",
    "removed by reddit",
)
_RECENT_WINDOW = timedelta(days=365)


class RedditCommunityDiscoveryProvider:
    provider_name = "reddit-community-search"

    def __init__(
        self,
        *,
        search_provider: SearchProvider,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._search_provider = search_provider
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            supports_domain_scoped_search=True,
            supports_public_page_extraction=False,
            supports_community_discussion_retrieval=True,
            compliance_notes=(
                "Uses the configured general search provider with reddit.com scope.",
                "Search excerpts are preserved; Reddit pages are not fetched directly.",
                "Reddit evidence remains qualitative and requires corroboration.",
            ),
        )

    async def search_discussions(
        self,
        query: str,
        products: tuple[CanonicalProduct, ...] = (),
        options: CommunityDiscussionProviderOptions | None = None,
    ) -> CommunityDiscussionProviderResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("Reddit community search query must not be empty.")
        discussion_options = options or CommunityDiscussionProviderOptions()
        search_query = SearchQuery(
            query=_reddit_scoped_query(normalized_query),
            intent=SearchIntent.REVIEW,
            region_code=discussion_options.region_code,
            required_source_types=(SourceType.COMMUNITY_DISCUSSION,),
        )
        search_results = await self._search_provider.search(
            search_query,
            SearchProviderOptions(
                region_code=discussion_options.region_code,
                max_results=discussion_options.max_results,
                source_policy=_reddit_source_policy(discussion_options.source_policy),
            ),
        )

        source_references: list[SourceReference] = []
        discussions: list[CommunityDiscussionContext] = []
        claims: list[SourceBackedCommunityClaim] = []
        evidence_gaps: list[SourceEvidenceGap] = []

        for result in search_results:
            normalized_url, domain = normalize_source_url(str(result.url))
            if not _is_reddit_domain(domain):
                continue

            raw = result.provider.raw
            posted_at = _optional_datetime(raw.get("posted_at")) or _optional_datetime(
                raw.get("published_at")
            )
            engagement_score = _optional_nonnegative_int(raw.get("engagement_score"))
            comment_count = _optional_nonnegative_int(raw.get("comment_count"))
            extracted_text = _optional_text(raw.get("extracted_public_text"), 2000)
            summary = extracted_text or result.snippet
            recurring_signal = raw.get("recurring_signal") is True
            recent = posted_at is not None and posted_at >= self._now() - _RECENT_WINDOW
            assessment = score_source_quality(
                normalized_url,
                SourceQualityMetadata(
                    target_region_code=discussion_options.region_code,
                    evidence_context=SourceEvidenceContext.COMMUNITY,
                    recurring_community_signal=recurring_signal,
                    community_engagement_available=(
                        engagement_score is not None or comment_count is not None
                    ),
                    community_source_recent=recent,
                ),
            )
            source_quality = assessment.quality
            path_context = _parse_reddit_path(normalized_url)
            low_quality_reason = _low_quality_reason(result.title, summary)

            source_references.append(
                SourceReference(
                    source_id=result.source_id,
                    url=normalized_url,
                    title=result.title,
                )
            )
            discussions.append(
                CommunityDiscussionContext(
                    source_id=result.source_id,
                    url=normalized_url,
                    community_name=path_context.get("community_name"),
                    thread_id=path_context.get("thread_id"),
                    thread_title=result.title,
                    comment_id=path_context.get("comment_id"),
                    posted_at=posted_at,
                    engagement_score=engagement_score,
                    comment_count=comment_count,
                    extracted_public_summary=summary,
                )
            )

            if low_quality_reason is not None or summary is None:
                evidence_gaps.append(
                    _source_gap(
                        result=result,
                        source_quality=source_quality,
                        summary="Public Reddit content was inaccessible or too weak to use.",
                        reason=low_quality_reason or "The search result contained no usable excerpt.",
                    )
                )
                continue

            for target in _evidence_targets(result, summary, products):
                claims.append(
                    SourceBackedCommunityClaim(
                        source_id=result.source_id,
                        target=target,
                        claim=summary,
                        confidence=Confidence(
                            score=0.45 if extracted_text is not None else 0.35,
                            level=ConfidenceLevel.LOW,
                            rationale=(
                                "Community discussion is anecdotal and must be corroborated."
                            ),
                        ),
                        source_quality=source_quality,
                        context_source_ids=(result.source_id,),
                        recurring_signal=recurring_signal,
                        evidence_quality_warnings=(
                            ("Only a search-result excerpt was available.",)
                            if extracted_text is None
                            else ()
                        ),
                    )
                )

            if extracted_text is None:
                evidence_gaps.append(
                    _source_gap(
                        result=result,
                        source_quality=source_quality,
                        summary="Full public Reddit content was not extracted.",
                        reason=(
                            "Only the general search provider's public excerpt is available."
                        ),
                    )
                )

        if not source_references:
            evidence_gaps.append(
                SourceEvidenceGap(
                    capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                    summary="No accessible public Reddit discussions were returned.",
                    reason=(
                        "The domain-scoped search returned no reddit.com results that "
                        "could be used as community evidence."
                    ),
                )
            )

        bundle = CommunityEvidenceCreator(now=self._now).create(
            CommunityDiscussionEvidenceBundle(
                source_references=tuple(source_references),
                discussions=tuple(discussions),
                evidence_gaps=tuple(evidence_gaps),
            ),
            tuple(claims),
        )
        return CommunityDiscussionProviderResult(
            status=ProviderRunStatus.SUCCEEDED,
            capabilities=self.capabilities,
            bundle=bundle,
            notes=(
                "Reddit results are qualitative community signals, not official facts.",
            ),
        )


def _reddit_scoped_query(query: str) -> str:
    suffix = " site:reddit.com"
    if "site:reddit.com" in query.casefold():
        return query[:500]
    return f"{query[: 500 - len(suffix)]}{suffix}"


def _reddit_source_policy(
    policy: SourceAllowAvoidPolicy,
) -> SourceAllowAvoidPolicy:
    return SourceAllowAvoidPolicy(
        allow=(
            SourcePolicyRule(
                action=SourcePolicyAction.ALLOW,
                domain="reddit.com",
                reason="Reddit community discovery is restricted to public reddit.com pages.",
            ),
        ),
        avoid=policy.avoid,
    )


def _is_reddit_domain(domain: str) -> bool:
    return domain == "reddit.com" or domain.endswith(".reddit.com")


def _parse_reddit_path(url: str) -> dict[str, str | None]:
    from urllib.parse import urlsplit

    match = _REDDIT_THREAD_PATH.match(urlsplit(url).path)
    if match is None:
        return {
            "community_name": None,
            "thread_id": None,
            "comment_id": None,
        }
    return {
        "community_name": match.group("community"),
        "thread_id": match.group("thread_id"),
        "comment_id": match.group("comment_id"),
    }


def _evidence_targets(
    result: SearchResult,
    summary: str,
    products: tuple[CanonicalProduct, ...],
) -> tuple[EvidenceTarget, ...]:
    searchable = f"{result.title} {summary}".casefold()
    product_targets = tuple(
        EvidenceTarget(
            target_type=EvidenceTargetType.PRODUCT,
            product_id=product.product_id,
        )
        for product in products
        if product.name.casefold() in searchable
    )
    if product_targets:
        return product_targets
    return (
        EvidenceTarget(
            target_type=EvidenceTargetType.SOURCE_METADATA,
            source_id=result.source_id,
        ),
    )


def _source_gap(
    *,
    result: SearchResult,
    source_quality: SourceQuality,
    summary: str,
    reason: str,
) -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
        target=EvidenceTarget(
            target_type=EvidenceTargetType.SOURCE_METADATA,
            source_id=result.source_id,
        ),
        source_id=result.source_id,
        summary=summary,
        reason=reason,
        source_quality=source_quality,
        confidence=Confidence(
            score=0.2,
            level=ConfidenceLevel.LOW,
            rationale="The available public community evidence is incomplete.",
        ),
    )


def _low_quality_reason(title: str, summary: str | None) -> str | None:
    combined = f"{title} {summary or ''}".casefold()
    if any(marker in combined for marker in _LOW_QUALITY_MARKERS):
        return "The Reddit content appears deleted or removed."
    return None


def _optional_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _optional_text(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()[:max_length]
    return normalized or None
