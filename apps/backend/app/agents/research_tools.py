"""Run-scoped, bounded provider tools for agent-owned source research.

The model sees source IDs and safe excerpts, never provider credentials, vendor
arguments, raw metadata, artifact paths, or an arbitrary-URL fetch operation.
"""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_address
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from agents import FunctionTool, function_tool
from pydantic import Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG
from app.agents.hosted_web_search import HostedWebCitation
from app.db.repositories.search_sources import SearchSourceRepository
from app.providers.contracts import (
    ExtractionProvider,
    ExtractionProviderOptions,
    SearchProvider,
    SearchProviderOptions,
    SourceAllowAvoidPolicy,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import RunId, SourceId
from app.schemas.regions import RegionCode
from app.schemas.search_sources import (
    ExtractionStatus,
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    ProviderMetadata,
    SearchIntent,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
)


class ResearchToolLimits(CartCartBaseModel):
    max_search_calls: int = Field(default=4, ge=1, le=20)
    max_fetch_calls: int = Field(default=8, ge=1, le=40)
    max_results_per_search: int = Field(default=10, ge=1, le=20)
    max_page_text_chars: int = Field(default=12000, ge=500, le=50000)
    max_quote_calls: int = Field(default=8, ge=1, le=20)


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


class RecordSourceQuoteResult(CartCartBaseModel):
    status: ResearchToolStatus
    source_id: SourceId | None = None
    snapshot_id: SourceId | None = None
    evidence_id: SourceId | None = None
    quote: str | None = None
    gap: str | None = None


@dataclass(frozen=True)
class PersistedHostedCitation:
    url: str
    source_id: SourceId
    snapshot_id: SourceId
    evidence_id: SourceId
    call_id: str | None


class HostedCitationStore:
    """Citation-only persistence for SDK agents without provider research tools."""

    def __init__(
        self,
        *,
        run_id: RunId,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        shared_session: AsyncSession | None = None,
    ) -> None:
        if session_factory is None and shared_session is None:
            raise ValueError("Hosted citations require a database session.")
        self.run_id = run_id
        self.session_factory = session_factory
        self.shared_session = shared_session
        self.lock = asyncio.Lock()

    async def persist(
        self,
        *,
        agent_name: str,
        citations: tuple[HostedWebCitation, ...],
        query: str,
        region_code: RegionCode | None,
        source_policy: SourceAllowAvoidPolicy,
    ) -> tuple[tuple[PersistedHostedCitation, ...], tuple[tuple[str, str], ...]]:
        if not citations:
            return (), ()
        async with self.lock:
            if self.shared_session is not None:
                persisted, _, decisions = await save_hosted_citations(
                    session=self.shared_session,
                    agent_name=agent_name,
                    run_id=self.run_id,
                    citations=citations,
                    query=query,
                    region_code=region_code,
                    source_policy=source_policy,
                )
            else:
                assert self.session_factory is not None
                async with self.session_factory() as session:
                    persisted, _, decisions = await save_hosted_citations(
                        session=session,
                        agent_name=agent_name,
                        run_id=self.run_id,
                        citations=citations,
                        query=query,
                        region_code=region_code,
                        source_policy=source_policy,
                    )
        return persisted, decisions


async def save_hosted_citations(
    *,
    session: AsyncSession,
    agent_name: str,
    run_id: RunId,
    citations: tuple[HostedWebCitation, ...],
    query: str,
    region_code: RegionCode | None,
    source_policy: SourceAllowAvoidPolicy,
) -> tuple[
    tuple[PersistedHostedCitation, ...],
    tuple[SearchResult, ...],
    tuple[tuple[str, str], ...],
]:
    if (
        ApprovedSDKTool.HOSTED_WEB_SEARCH
        not in DEFAULT_AGENT_CATALOG.require(agent_name).approved_sdk_tools
    ):
        raise ValueError("Agent is not approved for hosted web search.")
    selected: list[tuple[SearchResult, SourceSnapshot, SourceEvidence, str | None]] = []
    decisions: list[tuple[str, str]] = []
    seen: set[str] = set()
    for citation in citations:
        try:
            normalized = _neutral_url(citation.url)
        except ValueError:
            decisions.append((citation.url, "source_rejected"))
            continue
        if normalized in seen:
            decisions.append((normalized, "duplicate_rejected"))
            continue
        seen.add(normalized)
        if len(selected) >= 8:
            decisions.append((normalized, "citation_limit_rejected"))
            continue
        if (
            len(normalized) > 2048
            or not _safe_public_result_url(citation.url)
            or not _source_policy_allows(
                citation.url, SourceType.SEARCH_RESULT, source_policy
            )
        ):
            decisions.append((normalized, "source_rejected"))
            continue
        quality = SourceQuality(
            level=SourceQualityLevel.WEAK,
            rationale="Hosted citation only; page and product claims are unverified.",
        )
        provider = ProviderMetadata(
            provider_name="openai-hosted-web-search",
            provider_result_id=citation.call_id,
            raw={"url_citation": True},
        )
        result = SearchResult(
            query=SearchQuery(
                query=query[:500],
                intent=SearchIntent.DISCOVERY,
                region_code=region_code,
            ),
            url=normalized,
            title=(citation.title.strip() or normalized)[:300],
            source_type=SourceType.SEARCH_RESULT,
            provider=provider,
            quality=quality,
        )
        snapshot = SourceSnapshot(
            url=normalized,
            source_type=SourceType.SEARCH_RESULT,
            title=result.title,
            provider=provider,
            extraction_status=ExtractionStatus.NOT_ATTEMPTED,
            quality=quality,
        )
        evidence = SourceEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA,
                source_id=snapshot.source_id,
            ),
            evidence_type=EvidenceType.OTHER,
            claim=(
                citation.cited_text.strip() or f"Hosted response cited {result.title}"
            )[:2000],
            confidence=Confidence(
                score=0.2,
                level=ConfidenceLevel.LOW,
                rationale="Citation establishes a referenced URL, not a verified product fact.",
            ),
            source_quality=quality,
        )
        selected.append((result, snapshot, evidence, citation.call_id))
        decisions.append((normalized, "retained"))
    if selected:
        repository = SearchSourceRepository(session)
        for result, snapshot, evidence, _ in selected:
            await repository.add_search_result(run_id, result)
            await repository.add_source_snapshot(
                run_id, snapshot, search_result_id=result.source_id
            )
            await repository.add_source_evidence(run_id, evidence)
        await session.commit()
    persisted = tuple(
        PersistedHostedCitation(
            url=_neutral_url(str(result.url)),
            source_id=result.source_id,
            snapshot_id=snapshot.source_id,
            evidence_id=evidence.evidence_id,
            call_id=call_id,
        )
        for result, snapshot, evidence, call_id in selected
    )
    return persisted, tuple(item[0] for item in selected), tuple(decisions)


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
        required_region_code: RegionCode | None = None,
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
        self._required_region_code = required_region_code
        self._search_calls = 0
        self._fetch_calls = 0
        self._quote_calls = 0
        self._lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._activity: list[dict[str, Any]] = []
        self._search_results: list[SearchResult] = []
        self._recorded_quote_ids: set[SourceId] = set()
        self._recorded_source_ids: set[SourceId] = set()

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._activity)

    @property
    def search_results(self) -> tuple[SearchResult, ...]:
        return tuple(self._search_results)

    @property
    def source_policy(self) -> SourceAllowAvoidPolicy:
        return self._source_policy

    @property
    def recorded_quote_ids(self) -> frozenset[SourceId]:
        return frozenset(self._recorded_quote_ids)

    @property
    def recorded_source_ids(self) -> frozenset[SourceId]:
        return frozenset(self._recorded_source_ids)

    @property
    def required_region_code(self) -> RegionCode | None:
        return self._required_region_code

    def for_agent(self, agent_name: str) -> "AgentResearchTools":
        """Give a receiving owner the same run, policy, and providers with its own budget."""
        return AgentResearchTools(
            agent_name=agent_name,
            run_id=self._run_id,
            session_factory=self._session_factory,
            shared_session=self._shared_session,
            search_provider=self._search_provider,
            extraction_provider=self._extraction_provider,
            source_policy=self._source_policy,
            limits=self._limits,
            required_region_code=self._required_region_code,
        )

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

    def sdk_owner_tools(self) -> tuple[FunctionTool, FunctionTool, FunctionTool]:
        """General owner may cite exact text from an already fetched page."""
        if (
            ApprovedSDKTool.RECORD_SOURCE_QUOTE
            not in DEFAULT_AGENT_CATALOG.require(self._agent_name).approved_sdk_tools
        ):
            raise ValueError("Agent is not approved to record page quotes.")

        @function_tool
        async def record_source_quote(source_id: str, quote: str) -> str:
            """Persist an exact quote from a fetched source in this run.

            Args:
                source_id: ID returned by search_sources, then fetched.
                quote: Exact page text, at most 400 characters; never a snippet.
            """
            try:
                parsed_id = SourceId(source_id)
            except ValueError:
                return RecordSourceQuoteResult(
                    status=ResearchToolStatus.INVALID_REQUEST,
                    gap="Source ID failed validation.",
                ).model_dump_json()
            return (await self.record_quote(parsed_id, quote)).model_dump_json()

        search, fetch = self.sdk_tools()
        return search, fetch, record_source_quote

    async def record_quote(
        self, source_id: SourceId, quote: str
    ) -> RecordSourceQuoteResult:
        bounded = quote.strip()
        if not bounded or len(bounded) > 400:
            return RecordSourceQuoteResult(
                status=ResearchToolStatus.INVALID_REQUEST,
                gap="Quote must contain 1 to 400 exact page characters.",
            )
        async with self._session_lock:
            if self._quote_calls >= self._limits.max_quote_calls:
                return RecordSourceQuoteResult(
                    status=ResearchToolStatus.BUDGET_EXHAUSTED,
                    gap="Quote limit reached.",
                )
            self._quote_calls += 1
            async with self._session() as session:
                repository = SearchSourceRepository(session)
                source = await repository.get_search_result_for_run(
                    self._run_id, source_id
                )
                snapshot = await repository.get_snapshot_for_search_result(
                    self._run_id, source_id
                )
                if (
                    source is None
                    or not _safe_public_result_url(str(source.url))
                    or not _source_policy_allows(
                        str(source.url), source.source_type, self._source_policy
                    )
                    or snapshot is None
                    or snapshot.extraction_status != ExtractionStatus.SUCCEEDED
                    or snapshot.extracted_content is None
                    or bounded not in snapshot.extracted_content.text
                    or bounded
                    not in snapshot.extracted_content.text[
                        : self._limits.max_page_text_chars
                    ]
                ):
                    result = RecordSourceQuoteResult(
                        status=ResearchToolStatus.GAP,
                        gap="Exact quote was not found in a fetched page in this run.",
                    )
                    self._record("record_source_quote", result.status)
                    return result
                evidence = SourceEvidence(
                    source_id=snapshot.source_id,
                    target=EvidenceTarget(
                        target_type=EvidenceTargetType.SOURCE_METADATA,
                        source_id=snapshot.source_id,
                    ),
                    evidence_type=(
                        EvidenceType.REVIEW_CLAIM
                        if source.source_type == SourceType.PROFESSIONAL_REVIEW
                        else EvidenceType.OTHER
                    ),
                    claim=bounded,
                    confidence=Confidence(
                        score=0.5,
                        level=ConfidenceLevel.MEDIUM,
                        rationale="Exact text on a fetched page; the claim is not independently verified.",
                    ),
                    source_quality=snapshot.quality,
                )
                await repository.add_source_evidence(self._run_id, evidence)
                await self._commit(session)
                self._recorded_quote_ids.add(evidence.evidence_id)
                self._recorded_source_ids.add(source_id)
                result = RecordSourceQuoteResult(
                    status=ResearchToolStatus.SUCCEEDED,
                    source_id=source_id,
                    snapshot_id=snapshot.source_id,
                    evidence_id=evidence.evidence_id,
                    quote=bounded,
                )
                self._record(
                    "record_source_quote",
                    result.status,
                    source_ids=[
                        str(source_id),
                        str(snapshot.source_id),
                        str(evidence.evidence_id),
                    ],
                )
                return result

    async def search(self, request: SearchSourcesRequest) -> SearchSourcesResult:
        if (
            self._required_region_code is not None
            or self._agent_name == "GeneralShoppingAgent"
        ):
            if request.region_code not in (None, self._required_region_code):
                result = SearchSourcesResult(
                    status=ResearchToolStatus.INVALID_REQUEST,
                    gap="Search region differs from the shopper's buying region.",
                )
                self._record("search_sources", result.status)
                return result
            request = request.model_copy(
                update={"region_code": self._required_region_code}
            )
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

    async def persist_hosted_citations(
        self,
        citations: tuple[HostedWebCitation, ...],
        *,
        query: str,
        region_code: RegionCode | None,
    ) -> tuple[PersistedHostedCitation, ...]:
        """Save actual SDK citations as weak source metadata, never listings."""
        async with self._session_lock:
            async with self._session() as session:
                persisted, results, decisions = await save_hosted_citations(
                    session=session,
                    agent_name=self._agent_name,
                    run_id=self._run_id,
                    citations=citations,
                    query=query,
                    region_code=region_code,
                    source_policy=self._source_policy,
                )
        self._search_results.extend(results)
        for decision in decisions:
            self._record("web_search", decision[1], url=decision[0])
        self._record(
            "web_search",
            "citations_persisted",
            source_ids=[str(item.source_id) for item in persisted],
        )
        return persisted

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
                    if (
                        cached is not None
                        and cached.extraction_status != ExtractionStatus.NOT_ATTEMPTED
                    ):
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
                        if cached is not None:
                            snapshot = snapshot.model_copy(
                                update={"source_id": cached.source_id}
                            )
                        await repository.save_source_snapshot(
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
        url: str | None = None,
    ) -> None:
        self._activity.append(
            {
                "tool_name": tool_name,
                "status": status,
                "input": {"agent": self._agent_name, "run_id": str(self._run_id)},
                "output": {
                    "source_ids": source_ids or [],
                    **({"url": url} if url is not None else {}),
                },
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
    query = ""
    if (parsed.hostname or "").lower() in {
        "youtube.com",
        "www.youtube.com",
    } and parsed.path == "/watch":
        video_ids = parse_qs(parsed.query).get("v", ())
        if video_ids:
            query = urlencode({"v": video_ids[0]})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def _safe_public_result_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "local", "internal", "invalid", "test"} or host.endswith(
        (".localhost", ".local", ".internal", ".invalid", ".test", ".lan")
    ):
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


def _source_policy_allows(
    url: str, source_type: SourceType, policy: SourceAllowAvoidPolicy
) -> bool:
    host = (urlsplit(url).hostname or "").rstrip(".").lower().removeprefix("www.")

    def matches(rule: Any) -> bool:
        domain = (
            rule.domain.rstrip(".").lower().removeprefix("www.")
            if rule.domain is not None
            else None
        )
        return (domain is None or host == domain or host.endswith(f".{domain}")) and (
            rule.source_type is None or rule.source_type == source_type
        )

    if any(matches(rule) for rule in policy.avoid):
        return False
    return not policy.allow or any(matches(rule) for rule in policy.allow)
