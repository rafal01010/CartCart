"""Bounded public-community retrieval for the Reddit SDK specialist."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from agents import FunctionTool, function_tool

from app.agents.contracts import RedditCommunityIntelligenceAgentInput
from app.agents.reddit_community_intelligence_service import (
    _bundle_from_community_snapshots,
    _deleted_or_removed,
    _merge_community_bundles,
)
from app.providers import (
    CommunityDiscussionProvider,
    CommunityDiscussionProviderOptions,
    ProviderRunStatus,
)
from app.schemas.search_sources import (
    CommunityDiscussionEvidenceBundle,
    ExtractionStatus,
)


def _public_reddit_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    return (
        parsed.scheme == "https"
        and host in {"reddit.com", "www.reddit.com", "old.reddit.com"}
        and parsed.path.casefold().startswith("/r/")
        and "/comments/" in parsed.path.casefold()
    )


@dataclass
class RedditCommunityTools:
    input_data: RedditCommunityIntelligenceAgentInput
    community_provider: CommunityDiscussionProvider
    max_searches: int = 2
    max_discussions: int = 6
    max_summary_chars: int = 1600
    _bundles: list[CommunityDiscussionEvidenceBundle] = field(
        default_factory=list, init=False
    )
    _searches: int = field(default=0, init=False)
    _read: set[str] = field(default_factory=set, init=False)
    _activity: list[dict[str, Any]] = field(default_factory=list, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        seeded = _bundle_from_community_snapshots(self.input_data.source_snapshots)
        if seeded is not None:
            inaccessible = {
                item.source_id
                for item in self.input_data.source_snapshots
                if item.extraction_status
                in {ExtractionStatus.FAILED, ExtractionStatus.EXCLUDED}
            }
            seeded = seeded.model_copy(
                update={
                    "discussions": tuple(
                        item.model_copy(update={"extracted_public_summary": None})
                        if item.source_id in inaccessible
                        else item
                        for item in seeded.discussions
                    )
                }
            )
            self._bundles.append(self._sanitize(seeded))

    def _sanitize(
        self, bundle: CommunityDiscussionEvidenceBundle
    ) -> CommunityDiscussionEvidenceBundle:
        refs = {
            ref.source_id: ref
            for ref in bundle.source_references
            if _public_reddit_url(str(ref.url))
        }
        discussions = tuple(
            discussion.model_copy(
                update={
                    "extracted_public_summary": (
                        discussion.extracted_public_summary[: self.max_summary_chars]
                        if discussion.extracted_public_summary
                        and not _deleted_or_removed(discussion.extracted_public_summary)
                        else None
                    )
                }
            )
            for discussion in bundle.discussions[: self.max_discussions]
            if discussion.source_id in refs
            and _public_reddit_url(str(discussion.url))
            and str(discussion.url) == str(refs[discussion.source_id].url)
        )
        kept = {item.source_id for item in discussions}
        return CommunityDiscussionEvidenceBundle(
            source_references=tuple(
                ref for ref in bundle.source_references if ref.source_id in kept
            ),
            discussions=discussions,
            evidence_gaps=tuple(
                gap
                for gap in bundle.evidence_gaps
                if gap.source_id is None or gap.source_id in kept
            ),
        )

    @property
    def bundle(self) -> CommunityDiscussionEvidenceBundle | None:
        return _merge_community_bundles(tuple(self._bundles), ())

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._activity)

    def summaries(self) -> list[dict[str, Any]]:
        bundle = self.bundle
        return [
            {
                "source_id": str(item.source_id),
                "thread_id": item.thread_id,
                "comment_id": item.comment_id,
                "subreddit": item.community_name,
                "title": item.thread_title,
                "accessible": item.extracted_public_summary is not None,
            }
            for item in (bundle.discussions if bundle else ())[: self.max_discussions]
        ]

    def sdk_tools(self) -> tuple[FunctionTool, ...]:
        @function_tool
        async def search_community_discussions(query: str) -> str:
            """Search approved public Reddit excerpts; never access private or logged-in pages."""
            return json.dumps(await self.search(query))

        @function_tool
        async def read_community_discussion(source_id: str) -> str:
            """Read a permitted persisted public discussion by its returned source ID."""
            return json.dumps(await self.read(source_id))

        return search_community_discussions, read_community_discussion

    async def search(self, query: str) -> dict[str, Any]:
        query = query.strip()
        if not query or len(query) > 300:
            return {
                "status": "invalid_query",
                "gap": "Use a 1–300 character community query.",
            }
        async with self._lock:
            if self._searches >= self.max_searches:
                return {
                    "status": "budget_exhausted",
                    "gap": "Community search limit reached.",
                }
            self._searches += 1
        try:
            result = await self.community_provider.search_discussions(
                query,
                products=self.input_data.products,
                options=CommunityDiscussionProviderOptions(
                    region_code=(
                        self.input_data.brief.region.region.country_code
                        if self.input_data.brief.region
                        else None
                    ),
                    max_results=self.max_discussions,
                ),
            )
            if result.status == ProviderRunStatus.SUCCEEDED and result.bundle:
                self._bundles.append(self._sanitize(result.bundle))
            response: dict[str, Any] = {
                "status": result.status.value,
                "discussions": self.summaries(),
                "notes": list(result.notes),
            }
        except Exception:
            response = {
                "status": "provider_error",
                "discussions": [],
                "gap": "Public community search failed.",
            }
        self._activity.append(
            {
                "tool_name": "search_community_discussions",
                "status": response["status"],
                "input": {"query": query},
                "output": {"discussion_count": len(response["discussions"])},
            }
        )
        return response

    async def read(self, source_id: str) -> dict[str, Any]:
        bundle = self.bundle
        discussion = (
            next(
                (
                    item
                    for item in bundle.discussions
                    if str(item.source_id) == source_id
                ),
                None,
            )
            if bundle
            else None
        )
        if discussion is None:
            return {
                "status": "unknown_source",
                "gap": "Discussion source ID was not supplied or returned by approved search.",
            }
        if source_id not in self._read and len(self._read) >= self.max_discussions:
            return {
                "status": "budget_exhausted",
                "gap": "Discussion read limit reached.",
            }
        self._read.add(source_id)
        response = {
            "status": "ok" if discussion.extracted_public_summary else "inaccessible",
            "discussion": discussion.model_dump(mode="json"),
        }
        self._activity.append(
            {
                "tool_name": "read_community_discussion",
                "status": response["status"],
                "input": {"source_id": source_id},
                "output": {
                    "thread_id": discussion.thread_id,
                    "comment_id": discussion.comment_id,
                },
            }
        )
        return response
