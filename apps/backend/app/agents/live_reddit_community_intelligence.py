from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.agents.contracts import RedditCommunityIntelligenceAgentInput
from app.core.settings import Settings
from app.providers import (
    CommunityDiscussionProvider,
    CommunityDiscussionProviderOptions,
    CommunityDiscussionProviderResult,
    ProviderRunStatus,
    build_community_discussion_provider,
)
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import SourceId
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    CommunityDiscussionContext,
    CommunityDiscussionEvidence,
    CommunityDiscussionEvidenceBundle,
    EvidenceTarget,
    EvidenceTargetType,
    ExtractionStatus,
    SourceEvidenceGap,
    SourceIntelligenceCapability,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
)
from app.schemas.source_references import SourceReference
from app.services.community_evidence_creation import (
    CommunityEvidenceCreator,
    SourceBackedCommunityClaim,
)


REDDIT_COMMUNITY_INTELLIGENCE_AGENT_NAME = "RedditCommunityIntelligenceAgent"
_MAX_DISCUSSIONS = 6
_MAX_RECURRING_SIGNALS = 4
_RECENT_WINDOW = timedelta(days=365)
_CLAIM_MAX_LENGTH = 420
_REDDIT_THREAD_PATH = re.compile(
    r"^/r/(?P<community>[^/]+)/comments/(?P<thread_id>[^/]+)"
    r"(?:/[^/]+)?(?:/(?P<comment_id>[^/]+))?/?$",
    re.IGNORECASE,
)
_DISCUSSION_CLAIM_PATTERN = re.compile(
    r"\b(?:owners?|users?|people|comments?|threads?|posts?|reviewers?)\s+"
    r"(?:also\s+)?(?:report|reports|reported|say|says|said|mention|mentions|"
    r"mentioned|complain|complains|complained|warn|warns|warned)\s+"
    r"(?:that\s+)?(?P<claim>[^.;\n]{18,220})",
    re.IGNORECASE,
)
_ISSUE_MARKERS = frozenset(
    {
        "avoid",
        "bad",
        "break",
        "broke",
        "complain",
        "concern",
        "crack",
        "defect",
        "disconnect",
        "fail",
        "issue",
        "peel",
        "poor",
        "problem",
        "split",
        "stale",
        "warranty",
        "weak",
        "wear",
    }
)
_DELETED_MARKERS = frozenset(
    {
        "[deleted]",
        "[removed]",
        "deleted by user",
        "removed by reddit",
    }
)
_QUALITATIVE_WARNING = (
    "Reddit/community evidence is qualitative and should not be treated as an "
    "authoritative product fact."
)
_MANIPULATION_WARNING = (
    "Community discussion patterns can be brigaded or astroturfed; corroborate "
    "with non-community sources."
)
_LOW_CONTEXT_WARNING = (
    "At least one cited discussion has limited context or missing engagement "
    "metadata."
)
_STALE_WARNING = "At least one cited discussion is stale."


@dataclass
class LiveRedditCommunityIntelligenceAgent:
    settings: Settings | None = None
    community_provider: CommunityDiscussionProvider | None = None
    evidence_creator: CommunityEvidenceCreator | None = None
    max_discussions: int = _MAX_DISCUSSIONS
    max_recurring_signals: int = _MAX_RECURRING_SIGNALS
    now: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now(UTC),
    )
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(
        self,
        input_data: RedditCommunityIntelligenceAgentInput,
    ) -> CommunityDiscussionEvidenceBundle:
        activity: list[dict[str, Any]] = []
        bundle = await self._collect_discussions(input_data, activity)
        bundle = _select_relevant_discussions(
            bundle,
            input_data,
            limit=self.max_discussions,
        )

        claims = _recurring_community_claims(
            bundle,
            input_data,
            max_claims=self.max_recurring_signals,
            now=self.now(),
        )
        output = self._evidence_creator().create(bundle, claims)
        output = _annotate_community_quality(output, now=self.now())
        output = _ensure_explicit_gap(output)
        activity.append(
            {
                "tool_name": "CommunityEvidenceCreator.create",
                "status": "community_evidence_created",
                "input": {
                    "agent": REDDIT_COMMUNITY_INTELLIGENCE_AGENT_NAME,
                    "allowed_tools": [],
                    "recurring_claim_count": len(claims),
                },
                "output": {
                    "discussion_count": len(output.discussions),
                    "evidence_count": len(output.evidence),
                    "gap_count": len(output.evidence_gaps),
                    "recurring_evidence_count": sum(
                        1 for item in output.evidence if item.recurring_signal
                    ),
                },
            }
        )
        self._workbench_activity = tuple(activity)
        return output

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    def _community_provider(self) -> CommunityDiscussionProvider:
        if self.community_provider is not None:
            return self.community_provider
        if self.settings is None:
            raise ValueError(
                "settings are required to build the community discussion provider."
            )
        return build_community_discussion_provider(self.settings)

    def _evidence_creator(self) -> CommunityEvidenceCreator:
        return self.evidence_creator or CommunityEvidenceCreator(now=self.now)

    async def _collect_discussions(
        self,
        input_data: RedditCommunityIntelligenceAgentInput,
        activity: list[dict[str, Any]],
    ) -> CommunityDiscussionEvidenceBundle:
        snapshot_bundle = _bundle_from_community_snapshots(input_data.source_snapshots)
        if snapshot_bundle is not None:
            activity.append(
                {
                    "tool_name": "supplied_reddit_discussions",
                    "status": "source_snapshots_selected",
                    "input": {
                        "agent": REDDIT_COMMUNITY_INTELLIGENCE_AGENT_NAME,
                        "allowed_tools": [],
                        "snapshot_count": len(input_data.source_snapshots),
                    },
                    "output": {
                        "discussion_count": len(snapshot_bundle.discussions),
                        "gap_count": len(snapshot_bundle.evidence_gaps),
                    },
                }
            )
            return snapshot_bundle

        provider = self._community_provider()
        bundles: list[CommunityDiscussionEvidenceBundle] = []
        provider_gaps: list[SourceEvidenceGap] = []
        queries = input_data.community_queries or (_fallback_community_query(input_data),)
        for query in queries:
            result = await provider.search_discussions(
                query,
                products=input_data.products,
                options=CommunityDiscussionProviderOptions(
                    region_code=_region_code(input_data),
                    max_results=self.max_discussions,
                ),
            )
            activity.append(_provider_activity(provider, query, result))
            if (
                result.status == ProviderRunStatus.SUCCEEDED
                and result.bundle is not None
            ):
                bundles.append(result.bundle)
            else:
                provider_gaps.append(_provider_gap(query, result))

        merged = _merge_community_bundles(tuple(bundles), tuple(provider_gaps))
        if merged is None:
            return CommunityDiscussionEvidenceBundle(
                evidence_gaps=(
                    SourceEvidenceGap(
                        capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                        summary="No accessible public Reddit discussions were available.",
                        reason=(
                            "The community discussion provider returned no usable "
                            "public Reddit thread or comment evidence."
                        ),
                        confidence=_confidence(
                            0.2,
                            "No usable community source was available.",
                        ),
                    ),
                ),
            )
        return merged


def _provider_activity(
    provider: CommunityDiscussionProvider,
    query: str,
    result: CommunityDiscussionProviderResult,
) -> dict[str, Any]:
    return {
        "tool_name": "CommunityDiscussionProvider.search_discussions",
        "status": result.status.value,
        "input": {
            "agent": REDDIT_COMMUNITY_INTELLIGENCE_AGENT_NAME,
            "allowed_tools": ["CommunityDiscussionProvider"],
            "query": query,
            "provider_name": provider.capabilities.provider_name,
        },
        "output": {
            "discussion_count": len(result.bundle.discussions)
            if result.bundle is not None
            else 0,
            "evidence_count": len(result.bundle.evidence)
            if result.bundle is not None
            else 0,
            "gap_count": len(result.bundle.evidence_gaps)
            if result.bundle is not None
            else 0,
            "notes": result.notes,
        },
    }


def _provider_gap(
    query: str,
    result: CommunityDiscussionProviderResult,
) -> SourceEvidenceGap:
    return SourceEvidenceGap(
        capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
        summary="Reddit community evidence was unavailable.",
        reason=(
            f"Community discussion provider returned {result.status.value} for "
            f"query '{query}'."
        ),
        confidence=_confidence(0.2, "Community provider did not return evidence."),
    )


def _bundle_from_community_snapshots(
    snapshots: tuple[SourceSnapshot, ...],
) -> CommunityDiscussionEvidenceBundle | None:
    references: list[SourceReference] = []
    discussions: list[CommunityDiscussionContext] = []
    evidence_gaps: list[SourceEvidenceGap] = []
    seen_source_ids: set[SourceId] = set()

    for snapshot in snapshots:
        if snapshot.source_type != SourceType.COMMUNITY_DISCUSSION:
            continue
        if snapshot.source_id in seen_source_ids:
            continue
        seen_source_ids.add(snapshot.source_id)

        context = _parse_reddit_path(str(snapshot.url))
        summary = (
            snapshot.extracted_content.text[:2000]
            if snapshot.extracted_content is not None
            else None
        )
        references.append(
            SourceReference(
                source_id=snapshot.source_id,
                url=snapshot.url,
                title=snapshot.title,
            )
        )
        discussions.append(
            CommunityDiscussionContext(
                source_id=snapshot.source_id,
                url=snapshot.url,
                community_name=context.get("community_name"),
                thread_id=context.get("thread_id"),
                comment_id=context.get("comment_id"),
                thread_title=snapshot.title,
                extracted_public_summary=summary,
            )
        )
        if (
            snapshot.extraction_status
            in {ExtractionStatus.FAILED, ExtractionStatus.EXCLUDED}
            or summary is None
            or _deleted_or_removed(summary)
        ):
            evidence_gaps.append(
                SourceEvidenceGap(
                    capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.SOURCE_METADATA,
                        source_id=snapshot.source_id,
                    ),
                    source_id=snapshot.source_id,
                    summary="Public Reddit content was inaccessible or too weak to use.",
                    reason=(
                        "The supplied community snapshot did not include usable "
                        "public discussion text."
                    ),
                    source_quality=snapshot.quality,
                    confidence=_confidence(
                        0.2,
                        "The available community snapshot is incomplete.",
                    ),
                )
            )

    if not references and not discussions and not evidence_gaps:
        return None
    return CommunityDiscussionEvidenceBundle(
        source_references=tuple(references),
        discussions=tuple(discussions),
        evidence_gaps=tuple(evidence_gaps),
    )


def _merge_community_bundles(
    bundles: tuple[CommunityDiscussionEvidenceBundle, ...],
    provider_gaps: tuple[SourceEvidenceGap, ...],
) -> CommunityDiscussionEvidenceBundle | None:
    if not bundles and not provider_gaps:
        return None

    references: list[SourceReference] = []
    discussions: list[CommunityDiscussionContext] = []
    evidence: list[CommunityDiscussionEvidence] = []
    evidence_gaps: list[SourceEvidenceGap] = list(provider_gaps)
    seen_source_ids: set[SourceId] = set()
    seen_discussion_ids: set[SourceId] = set()
    seen_evidence_ids: set[SourceId] = set()
    seen_gap_ids: set[SourceId] = {gap.gap_id for gap in provider_gaps}

    for bundle in bundles:
        for reference in bundle.source_references:
            if reference.source_id in seen_source_ids:
                continue
            seen_source_ids.add(reference.source_id)
            references.append(reference)
        for discussion in bundle.discussions:
            if discussion.source_id in seen_discussion_ids:
                continue
            seen_discussion_ids.add(discussion.source_id)
            discussions.append(discussion)
        for item in bundle.evidence:
            if item.evidence_id in seen_evidence_ids:
                continue
            seen_evidence_ids.add(item.evidence_id)
            evidence.append(item)
        for gap in bundle.evidence_gaps:
            if gap.gap_id in seen_gap_ids:
                continue
            seen_gap_ids.add(gap.gap_id)
            evidence_gaps.append(gap)

    return CommunityDiscussionEvidenceBundle(
        source_references=tuple(references),
        discussions=tuple(discussions),
        evidence=tuple(evidence),
        evidence_gaps=tuple(evidence_gaps),
    )


def _select_relevant_discussions(
    bundle: CommunityDiscussionEvidenceBundle,
    input_data: RedditCommunityIntelligenceAgentInput,
    *,
    limit: int,
) -> CommunityDiscussionEvidenceBundle:
    if len(bundle.discussions) <= limit:
        return bundle

    scored = [
        (_discussion_relevance_score(discussion, input_data), index, discussion)
        for index, discussion in enumerate(bundle.discussions)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected_discussions = tuple(discussion for _, _, discussion in scored[:limit])
    selected_source_ids = {discussion.source_id for discussion in selected_discussions}

    selected_references = tuple(
        reference
        for reference in bundle.source_references
        if reference.source_id in selected_source_ids
    )
    selected_evidence = tuple(
        item
        for item in bundle.evidence
        if item.source_id in selected_source_ids
        and all(
            source_id in selected_source_ids for source_id in item.context_source_ids
        )
    )
    selected_gaps = tuple(
        gap
        for gap in bundle.evidence_gaps
        if gap.source_id is None or gap.source_id in selected_source_ids
    )
    return bundle.model_copy(
        update={
            "source_references": selected_references,
            "discussions": selected_discussions,
            "evidence": selected_evidence,
            "evidence_gaps": selected_gaps,
        }
    )


def _recurring_community_claims(
    bundle: CommunityDiscussionEvidenceBundle,
    input_data: RedditCommunityIntelligenceAgentInput,
    *,
    max_claims: int,
    now: datetime,
) -> tuple[SourceBackedCommunityClaim, ...]:
    discussions = tuple(
        discussion
        for discussion in bundle.discussions
        if discussion.extracted_public_summary is not None
        and not _deleted_or_removed(discussion.extracted_public_summary)
    )
    if len(discussions) < 2:
        return ()

    seen_claims: set[str] = set()
    claims: list[SourceBackedCommunityClaim] = []
    target = _product_target(input_data)
    for discussion in discussions:
        for claim in _candidate_claim_phrases(discussion):
            normalized_claim = _normalize_text(claim)
            if normalized_claim in seen_claims:
                continue
            context_source_ids = tuple(
                candidate.source_id
                for candidate in discussions
                if candidate.extracted_public_summary is not None
                and normalized_claim
                in _normalize_text(candidate.extracted_public_summary)
            )
            if len(context_source_ids) < 2:
                continue
            seen_claims.add(normalized_claim)
            claims.append(
                SourceBackedCommunityClaim(
                    source_id=context_source_ids[0],
                    target=target
                    or EvidenceTarget(
                        target_type=EvidenceTargetType.SOURCE_METADATA,
                        source_id=context_source_ids[0],
                    ),
                    claim=claim,
                    confidence=_confidence(
                        0.58,
                        "Recurring qualitative Reddit/community signal.",
                    ),
                    source_quality=_community_source_quality(
                        tuple(
                            candidate
                            for candidate in discussions
                            if candidate.source_id in context_source_ids
                        )
                    ),
                    context_source_ids=context_source_ids,
                    recurring_signal=True,
                    evidence_quality_warnings=_agent_quality_warnings(
                        tuple(
                            candidate
                            for candidate in discussions
                            if candidate.source_id in context_source_ids
                        ),
                        now=now,
                    ),
                )
            )
            if len(claims) >= max_claims:
                return tuple(claims)
    return tuple(claims)


def _candidate_claim_phrases(
    discussion: CommunityDiscussionContext,
) -> tuple[str, ...]:
    summary = discussion.extracted_public_summary
    if summary is None:
        return ()

    candidates: list[str] = []
    for match in _DISCUSSION_CLAIM_PATTERN.finditer(summary):
        claim = _clean_claim(match.group("claim"))
        if _usable_claim_phrase(claim):
            candidates.append(claim)

    for sentence in re.split(r"[.;\n]", summary):
        claim = _clean_claim(sentence)
        if _usable_claim_phrase(claim) and any(
            marker in claim.casefold() for marker in _ISSUE_MARKERS
        ):
            candidates.append(claim)

    return tuple(dict.fromkeys(candidates))


def _usable_claim_phrase(claim: str) -> bool:
    if not (18 <= len(claim) <= _CLAIM_MAX_LENGTH):
        return False
    if _deleted_or_removed(claim):
        return False
    return len(re.findall(r"[a-z0-9][a-z0-9-]{2,}", claim.casefold())) >= 4


def _clean_claim(value: str) -> str:
    normalized = " ".join(value.split()).strip(" -:;,")
    if len(normalized) <= _CLAIM_MAX_LENGTH:
        return normalized
    return normalized[:_CLAIM_MAX_LENGTH].rsplit(" ", 1)[0].strip(" -:;,.")


def _annotate_community_quality(
    bundle: CommunityDiscussionEvidenceBundle,
    *,
    now: datetime,
) -> CommunityDiscussionEvidenceBundle:
    discussions = {
        discussion.source_id: discussion for discussion in bundle.discussions
    }
    evidence = tuple(
        item.model_copy(
            update={
                "qualitative_signal": True,
                "evidence_quality_warnings": tuple(
                    dict.fromkeys(
                        (
                            *item.evidence_quality_warnings,
                            *_agent_quality_warnings(
                                tuple(
                                    discussions[source_id]
                                    for source_id in item.context_source_ids
                                    if source_id in discussions
                                ),
                                now=now,
                            ),
                        )
                    )
                ),
            }
        )
        for item in bundle.evidence
    )
    return bundle.model_copy(update={"evidence": evidence})


def _agent_quality_warnings(
    discussions: tuple[CommunityDiscussionContext, ...],
    *,
    now: datetime,
) -> tuple[str, ...]:
    warnings = [_QUALITATIVE_WARNING, _MANIPULATION_WARNING]
    if any(
        discussion.posted_at is not None
        and discussion.posted_at < now - _RECENT_WINDOW
        for discussion in discussions
    ):
        warnings.append(_STALE_WARNING)
    if any(
        discussion.engagement_score is None and discussion.comment_count is None
        for discussion in discussions
    ) or any(
        discussion.extracted_public_summary is None
        or len(discussion.extracted_public_summary) < 80
        for discussion in discussions
    ):
        warnings.append(_LOW_CONTEXT_WARNING)
    if any(
        discussion.extracted_public_summary is not None
        and _deleted_or_removed(discussion.extracted_public_summary)
        for discussion in discussions
    ):
        warnings.append("Deleted or removed Reddit content was not used as evidence.")
    return tuple(warnings)


def _ensure_explicit_gap(
    bundle: CommunityDiscussionEvidenceBundle,
) -> CommunityDiscussionEvidenceBundle:
    if bundle.evidence or bundle.evidence_gaps:
        return bundle
    return bundle.model_copy(
        update={
            "evidence_gaps": (
                SourceEvidenceGap(
                    capability=SourceIntelligenceCapability.COMMUNITY_DISCUSSION,
                    summary="No recurring usable Reddit community signal was found.",
                    reason=(
                        "Public discussions were available, but they did not contain "
                        "a recurring source-backed qualitative pattern."
                    ),
                    confidence=_confidence(
                        0.25,
                        "Community evidence was too sparse for a recurring signal.",
                    ),
                ),
            ),
        }
    )


def _community_source_quality(
    discussions: tuple[CommunityDiscussionContext, ...],
) -> SourceQuality:
    if any(
        discussion.engagement_score is None and discussion.comment_count is None
        for discussion in discussions
    ):
        return SourceQuality(
            level=SourceQualityLevel.WEAK,
            score=0.42,
            rationale=(
                "Recurring Reddit signal has limited engagement context and remains "
                "anecdotal."
            ),
        )
    return SourceQuality(
        level=SourceQualityLevel.MIXED,
        score=0.58,
        rationale=(
            "Recurring Reddit community signal with source context; qualitative "
            "and requiring corroboration."
        ),
    )


def _discussion_relevance_score(
    discussion: CommunityDiscussionContext,
    input_data: RedditCommunityIntelligenceAgentInput,
) -> int:
    tokens = _query_tokens(input_data)
    if not tokens:
        return 0
    haystack = _discussion_text(discussion)
    return sum(1 for token in tokens if token in haystack)


def _query_tokens(input_data: RedditCommunityIntelligenceAgentInput) -> set[str]:
    values = [
        input_data.brief.original_query,
        input_data.brief.category,
        *(product.name for product in input_data.products),
        *(product.brand or "" for product in input_data.products),
        *(product.model or "" for product in input_data.products),
        *input_data.community_queries,
    ]
    return {
        token
        for value in values
        if value
        for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", value.casefold())
    }


def _discussion_text(discussion: CommunityDiscussionContext) -> str:
    return " ".join(
        value
        for value in (
            discussion.platform,
            discussion.community_name,
            discussion.thread_id,
            discussion.thread_title,
            discussion.comment_id,
            discussion.extracted_public_summary,
        )
        if value
    ).casefold()


def _fallback_community_query(input_data: RedditCommunityIntelligenceAgentInput) -> str:
    terms = [product.name for product in input_data.products[:2]]
    if input_data.brief.category:
        terms.append(input_data.brief.category)
    terms.append(input_data.brief.original_query)
    return f"{' '.join(dict.fromkeys(term for term in terms if term))} reddit owner complaints"[
        :500
    ].strip()


def _region_code(
    input_data: RedditCommunityIntelligenceAgentInput,
) -> RegionCode | None:
    if input_data.brief.region is None:
        return None
    return input_data.brief.region.region.country_code


def _product_target(
    input_data: RedditCommunityIntelligenceAgentInput,
) -> EvidenceTarget | None:
    if not input_data.products:
        return None
    return EvidenceTarget(
        target_type=EvidenceTargetType.PRODUCT,
        product_id=input_data.products[0].product_id,
    )


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


def _deleted_or_removed(value: str) -> bool:
    text = value.casefold()
    return any(marker in text for marker in _DELETED_MARKERS)


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _confidence(score: float, rationale: str) -> Confidence:
    level = (
        ConfidenceLevel.HIGH
        if score >= 0.75
        else ConfidenceLevel.MEDIUM
        if score >= 0.45
        else ConfidenceLevel.LOW
    )
    return Confidence(score=score, level=level, rationale=rationale)
