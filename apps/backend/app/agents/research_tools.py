"""Run-scoped, bounded provider tools for agent-owned source research.

The model sees source IDs and safe excerpts, never provider credentials, vendor
arguments, raw metadata, artifact paths, or an arbitrary-URL fetch operation.
"""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from enum import StrEnum
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agents import FunctionTool, function_tool
from pydantic import Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG
from app.db.repositories.search_sources import SearchSourceRepository
from app.providers.contracts import (
    ExtractionProvider,
    ExtractionProviderOptions,
    SearchProvider,
    SearchProviderOptions,
    SourceAllowAvoidPolicy,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.ids import RunId, SourceId
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchQuery,
    SearchResult,
    SourceSnapshot,
    SourceType,
)


class ResearchToolLimits(CartCartBaseModel):
    max_search_calls: int = Field(default=4, ge=1, le=20)
    max_fetch_calls: int = Field(default=8, ge=1, le=40)
    max_results_per_search: int = Field(default=10, ge=1, le=20)
    max_page_text_chars: int = Field(default=12000, ge=500, le=50000)


class ResearchToolStatus(StrEnum):
    SUCCEEDED = "succeeded"
    GAP = "gap"
    INVALID_REQUEST = "invalid_request"
    UNKNOWN_SOURCE = "unknown_source"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PERSISTENCE_FAILED = "persistence_failed"


class SearchSourcesRequest(CartCartBaseModel):
    query: str = Field(min_length=1, max_length=500)
    intent: SearchIntent = SearchIntent.DISCOVERY
    region_code: RegionCode | None = None
    max_results: int = Field(default=10, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def _nonblank_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped


class FetchSourceRequest(CartCartBaseModel):
    source_id: SourceId


class ToolSource(CartCartBaseModel):
    source_id: SourceId
    url: str
    title: str
    snippet: str | None = None
    provider_source_type: SourceType
    provider_name: str


class SearchSourcesResult(CartCartBaseModel):
    status: ResearchToolStatus
    sources: tuple[ToolSource, ...] = ()
    gap: str | None = None


class FetchSourceResult(CartCartBaseModel):
    status: ResearchToolStatus
    source_id: SourceId | None = None
    snapshot_id: SourceId | None = None
    url: str | None = None
    title: str | None = None
    extraction_status: ExtractionStatus | None = None
    text: str | None = None
    text_truncated: bool = False
    provider_name: str | None = None
    gap: str | None = None


class AgentResearchTools:
    """One instance per agent run; provider and database dependencies stay private."""

    def __init__(
        self,
        *,
        agent_name: str,
        run_id: RunId,
        session_factory: async_sessionmaker[AsyncSession] | None,
        shared_session: AsyncSession | None = None,
        search_provider: SearchProvider,
        extraction_provider: ExtractionProvider,
        source_policy: SourceAllowAvoidPolicy | None = None,
        limits: ResearchToolLimits | None = None,
    ) -> None:
        entry = DEFAULT_AGENT_CATALOG.require(agent_name)
        required_tools = {
            ApprovedSDKTool.SEARCH_SOURCES,
            ApprovedSDKTool.FETCH_SOURCE,
        }
        if not required_tools.issubset(entry.approved_sdk_tools):
            raise ValueError(
                f"{agent_name} is not approved for research provider tools."
            )
        if session_factory is None and shared_session is None:
            raise ValueError(
                "Research tools require a session factory or shared session."
            )
        self._agent_name = agent_name
        self._run_id = run_id
        self._session_factory = session_factory
        self._shared_session = shared_session
        self._search_provider = search_provider
        self._extraction_provider = extraction_provider
        self._source_policy = source_policy or SourceAllowAvoidPolicy()
        self._limits = limits or ResearchToolLimits()
        self._search_calls = 0
        self._fetch_calls = 0
        self._lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._activity: list[dict[str, Any]] = []
        self._search_results: list[SearchResult] = []

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._activity)

    @property
    def search_results(self) -> tuple[SearchResult, ...]:
        return tuple(self._search_results)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        if self._shared_session is not None:
            yield self._shared_session
        else:
            assert self._session_factory is not None
            async with self._session_factory() as session:
                yield session

    async def _commit(self, session: AsyncSession) -> None:
        # IDs returned to the agent must already be durable, including when
        # the shopping run shares its unit-of-work session with these tools.
        await session.commit()

    def sdk_tools(self) -> tuple[FunctionTool, FunctionTool]:
        """Return SDK tools; SDK traces record calls without exposing dependencies."""

        @function_tool
        async def search_sources(
            query: str,
            intent: SearchIntent = SearchIntent.DISCOVERY,
            region_code: str | None = None,
            max_results: int = 10,
        ) -> str:
            """Search approved shopping sources and return persisted source IDs.

            Args:
                query: Search terms chosen for the shopping research.
                intent: Purpose of this search, not a classification of results.
                region_code: Optional two-letter target buying region.
                max_results: Requested result count, bounded by backend policy.
            """
            try:
                request = SearchSourcesRequest(
                    query=query,
                    intent=intent,
                    region_code=region_code,
                    max_results=max_results,
                )
            except ValidationError:
                return SearchSourcesResult(
                    status=ResearchToolStatus.INVALID_REQUEST,
                    gap="Search request failed validation.",
                ).model_dump_json()
            return (await self.search(request)).model_dump_json()

        @function_tool
        async def fetch_source(source_id: str) -> str:
            """Inspect a persisted search result by ID; arbitrary URLs are not accepted.

            Args:
                source_id: Source ID returned by search_sources in this run.
            """
            try:
                request = FetchSourceRequest(source_id=source_id)
            except ValidationError:
                return FetchSourceResult(
                    status=ResearchToolStatus.INVALID_REQUEST,
                    gap="Source ID failed validation.",
                ).model_dump_json()
            return (await self.fetch(request)).model_dump_json()

        return search_sources, fetch_source

    async def search(self, request: SearchSourcesRequest) -> SearchSourcesResult:
        async with self._lock:
            if self._search_calls >= self._limits.max_search_calls:
                result = SearchSourcesResult(
                    status=ResearchToolStatus.BUDGET_EXHAUSTED,
                    gap="Search call limit reached.",
                )
                self._record("search_sources", result.status)
                return result
            self._search_calls += 1

        query = SearchQuery(
            query=request.query,
            intent=request.intent,
            region_code=request.region_code,
        )
        options = SearchProviderOptions(
            region_code=request.region_code,
            max_results=min(request.max_results, self._limits.max_results_per_search),
            source_policy=self._source_policy,
        )
        try:
            candidates = await self._search_provider.search(query, options)
        except Exception:
            result = SearchSourcesResult(
                status=ResearchToolStatus.PROVIDER_UNAVAILABLE,
                gap="Search provider could not return results.",
            )
            self._record("search_sources", result.status)
            return result

        selected: list[SearchResult] = []
        for candidate in candidates[: options.max_results]:
            if _safe_public_result_url(str(candidate.url)) and _domain_policy_allows(
                str(candidate.url), self._source_policy
            ):
                selected.append(
                    candidate.model_copy(
                        update={
                            "query": query,
                            "provider": _safe_search_metadata(
                                candidate.provider,
                                _provider_label(self._search_provider),
                            ),
                        }
                    )
                )

        try:
            async with self._session_lock:
                async with self._session() as session:
                    repository = SearchSourceRepository(session)
                    for candidate in selected:
                        await repository.add_search_result(self._run_id, candidate)
                    await self._commit(session)
        except Exception:
            result = SearchSourcesResult(
                status=ResearchToolStatus.PERSISTENCE_FAILED,
                gap="Search sources could not be saved.",
            )
            self._record("search_sources", result.status)
            return result

        result = SearchSourcesResult(
            status=ResearchToolStatus.SUCCEEDED,
            sources=tuple(
                _tool_source(item, _provider_label(self._search_provider))
                for item in selected
            ),
            gap=None if selected else "No approved search sources were returned.",
        )
        self._search_results.extend(selected)
        self._record(
            "search_sources",
            result.status,
            source_ids=[str(item.source_id) for item in selected],
        )
        return result

    async def fetch(self, request: FetchSourceRequest) -> FetchSourceResult:
        async with self._lock:
            async with self._session_lock:
                async with self._session() as session:
                    repository = SearchSourceRepository(session)
                    source = await repository.get_search_result_for_run(
                        self._run_id, request.source_id
                    )
                    if source is None:
                        result = FetchSourceResult(
                            status=ResearchToolStatus.UNKNOWN_SOURCE,
                            gap="Source ID is not in this run.",
                        )
                        self._record("fetch_source", result.status)
                        return result
                    if not _safe_public_result_url(
                        str(source.url)
                    ) or not _domain_policy_allows(
                        str(source.url), self._source_policy
                    ):
                        result = FetchSourceResult(
                            status=ResearchToolStatus.GAP,
                            source_id=request.source_id,
                            gap="Source URL is outside approved retrieval policy.",
                        )
                        self._record("fetch_source", result.status)
                        return result
                    cached = await repository.get_snapshot_for_search_result(
                        self._run_id, request.source_id
                    )
                    if cached is not None:
                        result = self._fetch_result(source, cached)
                        self._record(
                            "fetch_source",
                            "cached",
                            source_ids=[str(request.source_id)],
                        )
                        return result
            if self._fetch_calls >= self._limits.max_fetch_calls:
                result = FetchSourceResult(
                    status=ResearchToolStatus.BUDGET_EXHAUSTED,
                    gap="Page retrieval limit reached.",
                )
                self._record("fetch_source", result.status)
                return result
            self._fetch_calls += 1

            try:
                snapshot = await self._extraction_provider.extract(
                    source.url,
                    ExtractionProviderOptions(
                        source_type=source.source_type,
                        source_policy=self._source_policy,
                    ),
                )
            except Exception:
                result = FetchSourceResult(
                    status=ResearchToolStatus.PROVIDER_UNAVAILABLE,
                    source_id=request.source_id,
                    gap="Page retrieval provider could not inspect this source.",
                )
                self._record(
                    "fetch_source", result.status, source_ids=[str(request.source_id)]
                )
                return result

            if not _safe_public_result_url(
                str(snapshot.url)
            ) or not _domain_policy_allows(str(snapshot.url), self._source_policy):
                result = FetchSourceResult(
                    status=ResearchToolStatus.GAP,
                    source_id=request.source_id,
                    gap="Page retrieval returned an unsafe URL.",
                )
                self._record(
                    "fetch_source", result.status, source_ids=[str(request.source_id)]
                )
                return result

            snapshot = snapshot.model_copy(
                update={
                    "title": snapshot.title or source.title,
                    "quality": source.quality,
                    "provider": _safe_snapshot_metadata(
                        snapshot.provider,
                        _provider_label(self._extraction_provider),
                        source.source_id,
                    ),
                }
            )
            try:
                async with self._session_lock:
                    async with self._session() as session:
                        repository = SearchSourceRepository(session)
                        await repository.add_source_snapshot(
                            self._run_id,
                            snapshot,
                            search_result_id=request.source_id,
                        )
                        await self._commit(session)
            except Exception:
                result = FetchSourceResult(
                    status=ResearchToolStatus.PERSISTENCE_FAILED,
                    source_id=request.source_id,
                    gap="Page snapshot could not be saved.",
                )
                self._record(
                    "fetch_source", result.status, source_ids=[str(request.source_id)]
                )
                return result

            result = self._fetch_result(source, snapshot)
            self._record(
                "fetch_source",
                result.status,
                source_ids=[str(request.source_id), str(snapshot.source_id)],
            )
            return result

    def _fetch_result(
        self, source: SearchResult, snapshot: SourceSnapshot
    ) -> FetchSourceResult:
        text = (
            snapshot.extracted_content.text
            if snapshot.extracted_content is not None
            else None
        )
        bounded_text = text[: self._limits.max_page_text_chars] if text else None
        has_usable_text = (
            snapshot.extraction_status == ExtractionStatus.SUCCEEDED and bool(text)
        )
        return FetchSourceResult(
            status=(
                ResearchToolStatus.SUCCEEDED
                if has_usable_text
                else ResearchToolStatus.GAP
            ),
            source_id=source.source_id,
            snapshot_id=snapshot.source_id,
            url=_neutral_url(str(snapshot.url)),
            title=snapshot.title,
            extraction_status=snapshot.extraction_status,
            text=bounded_text,
            text_truncated=text is not None and len(text) > len(bounded_text or ""),
            provider_name=_provider_label(self._extraction_provider),
            gap=(
                None
                if has_usable_text
                else "Page content is incomplete or unavailable."
            ),
        )

    def _record(
        self,
        tool_name: str,
        status: ResearchToolStatus | str,
        *,
        source_ids: list[str] | None = None,
    ) -> None:
        self._activity.append(
            {
                "tool_name": tool_name,
                "status": status,
                "input": {"agent": self._agent_name, "run_id": str(self._run_id)},
                "output": {"source_ids": source_ids or []},
            }
        )


def _tool_source(result: SearchResult, provider_name: str) -> ToolSource:
    return ToolSource(
        source_id=result.source_id,
        url=_neutral_url(str(result.url)),
        title=result.title,
        snippet=result.snippet,
        provider_source_type=result.source_type,
        provider_name=provider_name,
    )


def _provider_label(provider: object) -> str:
    label = getattr(provider, "provider_name", None)
    return (
        label
        if isinstance(label, str)
        and label.isascii()
        and label.replace("-", "").isalnum()
        else "approved-provider"
    )


def _safe_search_metadata(
    original: ProviderMetadata, provider_name: str
) -> ProviderMetadata:
    rank = original.raw.get("rank")
    score = original.raw.get("score")
    safe_raw: dict[str, int | float] = {}
    if isinstance(rank, int) and not isinstance(rank, bool) and 0 <= rank <= 1000:
        safe_raw["rank"] = rank
    if (
        isinstance(score, (int, float))
        and not isinstance(score, bool)
        and 0 <= score <= 1
    ):
        safe_raw["score"] = float(score)
    return ProviderMetadata(
        provider_name=provider_name,
        provider_result_id=original.provider_result_id,
        query_id=original.query_id,
        raw=safe_raw,
    )


def _safe_snapshot_metadata(
    original: ProviderMetadata, provider_name: str, search_result_id: SourceId
) -> ProviderMetadata:
    safe_raw: dict[str, str | int | bool] = {
        "search_result_source_id": str(search_result_id)
    }
    for key in (
        "extraction_failure_code",
        "extraction_decision",
        "extraction_decision_reason",
    ):
        value = original.raw.get(key)
        if isinstance(value, str) and value.isascii() and len(value) <= 80:
            safe_raw[key] = value
    retryable = original.raw.get("extraction_failure_retryable")
    if isinstance(retryable, bool):
        safe_raw["extraction_failure_retryable"] = retryable
    redirect_count = original.raw.get("redirect_count")
    if isinstance(redirect_count, int) and 0 <= redirect_count <= 100:
        safe_raw["redirect_count"] = redirect_count
    return ProviderMetadata(provider_name=provider_name, raw=safe_raw)


def _neutral_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _safe_public_result_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        return False
    try:
        return ip_address(host).is_global
    except ValueError:
        return True


def _domain_policy_allows(url: str, policy: SourceAllowAvoidPolicy) -> bool:
    host = (urlsplit(url).hostname or "").rstrip(".").lower().removeprefix("www.")

    def matches(domain: str) -> bool:
        normalized = domain.rstrip(".").lower().removeprefix("www.")
        return host == normalized or host.endswith(f".{normalized}")

    if any(rule.domain and matches(rule.domain) for rule in policy.avoid):
        return False
    allowed_domains = [rule.domain for rule in policy.allow if rule.domain]
    return not allowed_domains or any(matches(domain) for domain in allowed_domains)
