"""Run-scoped, bounded provider tools for agent-owned source research.

The model sees source IDs and safe excerpts, never provider credentials, vendor
arguments, raw metadata, artifact paths, or an arbitrary-URL fetch operation.
"""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import ip_address
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from agents import FunctionTool, function_tool
from pydantic import AnyHttpUrl, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG
from app.agents.hosted_web_search import HostedWebCitation
from app.agents.research_selection import ResearchSelection
from app.agents.research_history import active_history
from app.agents.source_spans import source_span
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.session import shared_tool_session
from app.providers.contracts import (
    ExtractionProvider,
    ExtractionProviderOptions,
    SearchProvider,
    SearchProviderOptions,
    SourceAllowAvoidPolicy,
)
from app.schemas.base import CartCartBaseModel
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.ids import RunId, SourceId, new_id
from app.schemas.intake import ShoppingBrief
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
    max_page_text_chars: int = Field(default=4000, ge=500, le=12000)
    max_quote_calls: int = Field(default=8, ge=1, le=20)
    max_initial_results: int = Field(default=4, ge=1, le=20)
    max_snippet_chars: int = Field(default=200, ge=50, le=500)


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
    start_char: int = Field(default=0, ge=0)
    focus: str | None = Field(default=None, min_length=1, max_length=200)
    need_id: str | None = Field(default=None, min_length=1, max_length=32)


class ToolSource(CartCartBaseModel):
    source_id: SourceId
    url: str
    title: str
    snippet: str | None = None
    provider_source_type: SourceType
    provider_name: str
    snippet_truncated: bool = False
    unreviewed_content: bool = False
    material_cautions: tuple[str, ...] = ()
    deferred_caution_count: int = 0
    cautions_truncated: bool = False
    caution_focus_terms: tuple[str, ...] = ()
    unreviewed_cautions: bool = False


class SearchSourcesResult(CartCartBaseModel):
    status: ResearchToolStatus
    sources: tuple[ToolSource, ...] = ()
    search_result_id: SourceId | None = None
    total_sources: int = 0
    next_offset: int | None = None
    deferred_source_ids: tuple[SourceId, ...] = ()
    gap: str | None = None
    evidence_need_id: str | None = None
    selection_reasons: dict[str, str] = Field(default_factory=dict)

    def tool_json(self) -> str:
        import json

        payload = self.model_dump(mode="json", exclude_defaults=True)
        payload["sources"] = [
            item.model_dump(mode="json", exclude_defaults=True) for item in self.sources
        ]
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class FetchSourceResult(CartCartBaseModel):
    status: ResearchToolStatus
    source_id: SourceId | None = None
    snapshot_id: SourceId | None = None
    url: str | None = None
    title: str | None = None
    published_date: str | None = None
    extraction_status: ExtractionStatus | None = None
    text: str | None = None
    text_truncated: bool = False
    unreviewed_content: bool = False
    material_cautions: tuple[str, ...] = ()
    deferred_caution_count: int = 0
    cautions_truncated: bool = False
    caution_focus_terms: tuple[str, ...] = ()
    unreviewed_cautions: bool = False
    start_char: int = 0
    total_characters: int = 0
    content_sha256: str | None = None
    provider_name: str | None = None
    gap: str | None = None
    evidence_need_id: str | None = None


class RecordSourceQuoteResult(CartCartBaseModel):
    status: ResearchToolStatus
    source_id: SourceId | None = None
    snapshot_id: SourceId | None = None
    evidence_id: SourceId | None = None
    quote: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    content_sha256: str | None = None
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
                async with shared_tool_session(self.shared_session) as session:
                    persisted, _, decisions = await save_hosted_citations(
                        session=session,
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
            url=AnyHttpUrl(normalized),
            title=(citation.title.strip() or normalized)[:300],
            source_type=SourceType.SEARCH_RESULT,
            provider=provider,
            quality=quality,
        )
        snapshot = SourceSnapshot(
            url=AnyHttpUrl(normalized),
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


@dataclass
class ResearchRunState:
    search_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    query_cache: dict[tuple[str, str, str | None, int], SearchSourcesResult] = field(
        default_factory=dict
    )
    search_pages: dict[SourceId, tuple[SourceId, ...]] = field(default_factory=dict)
    recorded_quote_ids: set[SourceId] = field(default_factory=set)
    recorded_source_ids: set[SourceId] = field(default_factory=set)
    observed_spans: dict[SourceId, list[tuple[int, int, str]]] = field(
        default_factory=dict
    )
    selection: ResearchSelection | None = None


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
        self._run_state = ResearchRunState()
        self._bind_run_state(self._run_state)
        self._span_reads = 0

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
        receiving = AgentResearchTools(
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
        receiving._bind_run_state(self._run_state)
        return receiving

    def _bind_run_state(self, state: ResearchRunState) -> None:
        self._run_state = state
        self._query_cache = state.query_cache
        self._recorded_quote_ids = state.recorded_quote_ids
        self._recorded_source_ids = state.recorded_source_ids
        self._observed_spans = state.observed_spans

    def share_run_state(self, other: "AgentResearchTools") -> bool:
        if (
            self._run_id != other._run_id
            or self._required_region_code != other._required_region_code
            or self._source_policy != other._source_policy
            or self._search_provider is not other._search_provider
            or self._extraction_provider is not other._extraction_provider
        ):
            return False
        other._bind_run_state(self._run_state)
        return True

    def set_brief(self, brief: ShoppingBrief) -> None:
        selection = self._run_state.selection
        if selection is None:
            self._run_state.selection = ResearchSelection(brief)
        elif selection.brief != brief:
            raise ValueError("Shared research must retain the same buyer brief.")

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        if self._shared_session is not None:
            async with shared_tool_session(self._shared_session) as session:
                yield session
        else:
            assert self._session_factory is not None
            async with self._session_factory() as session:
                yield session

    async def _commit(self, session: AsyncSession) -> None:
        # IDs returned to the agent must already be durable, including when
        # the shopping run shares its unit-of-work session with these tools.
        await session.commit()

    def sdk_tools(self) -> tuple[FunctionTool, ...]:
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
            return (await self.search(request)).tool_json()

        @function_tool
        async def fetch_source(
            source_id: str,
            start_char: int = 0,
            focus: str | None = None,
            need_id: str | None = None,
        ) -> str:
            """Read an exact bounded span by run-scoped ID, including later page text.

            Args:
                source_id: Source ID returned by search_sources in this run.
                start_char: Character offset for the next span, default zero.
                focus: Optional exact search term to locate relevant support anywhere in the page.
                need_id: Optional open evidence need returned by search_sources.
            """
            try:
                request = FetchSourceRequest.model_validate(
                    {
                        "source_id": source_id,
                        "start_char": start_char,
                        "focus": focus,
                        "need_id": need_id,
                    }
                )
            except ValidationError:
                return FetchSourceResult(
                    status=ResearchToolStatus.INVALID_REQUEST,
                    gap="Source ID failed validation.",
                ).model_dump_json()
            result = await self.fetch(request)
            return result.model_dump_json(
                exclude={
                    name
                    for name in (
                        "deferred_caution_count",
                        "cautions_truncated",
                        "caution_focus_terms",
                        "unreviewed_cautions",
                    )
                    if not getattr(result, name)
                }
            )

        @function_tool
        async def read_search_results(
            search_result_id: str | None = None,
            offset: int = 0,
            source_id: str | None = None,
            start_char: int = 0,
            focus: str | None = None,
            need_id: str | None = None,
        ) -> str:
            """Retrieve deferred leads or original snippet spans without provider calls.

            Args:
                search_result_id: Result batch ID returned by search_sources.
                offset: Index of the next bounded lead batch.
                source_id: One persisted lead ID, instead of a batch ID.
                start_char: Offset into the original snippet.
                focus: Optional exact term to locate in the original snippet.
                need_id: Widen the shortlist for this unresolved evidence need.
            """
            return await self.read_search_results(
                search_result_id=search_result_id,
                offset=offset,
                source_id=source_id,
                start_char=start_char,
                focus=focus,
                need_id=need_id,
            )

        from app.agents.research_history import tracked_tools

        search_sources.is_enabled = lambda _context, _agent: (
            self._search_calls < self._limits.max_search_calls
        )
        fetch_source.is_enabled = lambda _context, _agent: (
            self._span_reads < self._limits.max_fetch_calls * 3
        )
        return tracked_tools((search_sources, fetch_source, read_search_results))

    def sdk_owner_tools(self) -> tuple[FunctionTool, ...]:
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

        from app.agents.research_history import tracked_tools

        return (
            *self.sdk_tools(),
            *tracked_tools((record_source_quote,), include_controls=False),
        )

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
                history = active_history()
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
                    or (
                        history is not None
                        and not history.quote_visible(source_id, bounded)
                    )
                    or not any(
                        bounded in snapshot.extracted_content.text[start:end]
                        and digest
                        == source_span(snapshot.extracted_content.text).content_sha256
                        for start, end, digest in self._observed_spans.get(
                            source_id, ()
                        )
                    )
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
                if self._run_state.selection is not None:
                    self._run_state.selection.record_support(
                        source, bounded, evidence.evidence_id
                    )
                quote_start = next(
                    start + snapshot.extracted_content.text[start:end].index(bounded)
                    for start, end, _ in self._observed_spans[source_id]
                    if bounded in snapshot.extracted_content.text[start:end]
                )
                result = RecordSourceQuoteResult(
                    status=ResearchToolStatus.SUCCEEDED,
                    source_id=source_id,
                    snapshot_id=snapshot.source_id,
                    evidence_id=evidence.evidence_id,
                    quote=bounded,
                    start_char=quote_start,
                    end_char=quote_start + len(bounded),
                    content_sha256=source_span(
                        snapshot.extracted_content.text
                    ).content_sha256,
                )
                self._record(
                    "record_source_quote",
                    result.status,
                    source_ids=[
                        str(source_id),
                        str(snapshot.source_id),
                        str(evidence.evidence_id),
                    ],
                    support_span={
                        "snapshot_id": str(snapshot.source_id),
                        "start_char": result.start_char,
                        "end_char": result.end_char,
                        "content_sha256": result.content_sha256,
                    },
                )
                return result

    async def search(self, request: SearchSourcesRequest) -> SearchSourcesResult:
        async with self._run_state.search_lock:
            return await self._search(request)

    async def _search(self, request: SearchSourcesRequest) -> SearchSourcesResult:
        selection = self._run_state.selection
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
        if selection is not None and selection.covered:
            result = SearchSourcesResult(
                status=ResearchToolStatus.GAP,
                gap="Required research already has exact support. Continue to candidate validation and verification.",
            )
            self._record("search_sources", "coverage_satisfied")
            return result
        async with self._lock:
            cache_key = (
                request.query.casefold(),
                request.intent.value,
                request.region_code,
                request.max_results,
            )
            if cache_key in self._query_cache:
                self._record("search_sources", "cached_query", query=request.query)
                return self._query_cache[cache_key]
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
            if selection is not None or (
                _safe_public_result_url(str(candidate.url))
                and _domain_policy_allows(str(candidate.url), self._source_policy)
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

        need = (
            selection.need(request.query, request.intent)
            if selection is not None
            else None
        )

        try:
            async with self._session_lock:
                async with self._session() as session:
                    repository = SearchSourceRepository(session)
                    existing = {
                        (
                            str(item.url),
                            item.source_type,
                            item.title,
                            item.snippet,
                            item.query.region_code,
                        ): item
                        for item in await repository.list_search_results(self._run_id)
                    }
                    prepared = []
                    for candidate in selected:
                        key = (
                            str(candidate.url),
                            candidate.source_type,
                            candidate.title,
                            candidate.snippet,
                            candidate.query.region_code,
                        )
                        if key in existing:
                            candidate = candidate.model_copy(
                                update={"source_id": existing[key].source_id}
                            )
                        elif any(
                            item.source_id == candidate.source_id
                            for item in existing.values()
                        ):
                            candidate = candidate.model_copy(
                                update={"source_id": new_id()}
                            )
                        prepared.append(candidate)
                    selected = prepared
                    if selection is not None and need is not None:
                        approved = []
                        for item in selected:
                            if not _safe_public_result_url(str(item.url)):
                                selection.reject(item, need, "unsafe_url")
                            elif not _domain_policy_allows(
                                str(item.url), self._source_policy
                            ):
                                selection.reject(item, need, "outside_source_policy")
                            else:
                                approved.append(item)
                        selection.select(
                            approved, need, limit=self._limits.max_initial_results
                        )
                        selected = [
                            item.model_copy(
                                update={
                                    "provider": item.provider.model_copy(
                                        update={
                                            "raw": {
                                                **item.provider.raw,
                                                "research_selection": selection.decisions[
                                                    item.source_id
                                                ].metadata(),
                                            }
                                        }
                                    )
                                }
                            )
                            for item in selected
                        ]
                    unique = {}
                    for candidate in selected:
                        key = (
                            str(candidate.url),
                            candidate.source_type,
                            candidate.title,
                            candidate.snippet,
                            candidate.query.region_code,
                        )
                        if key not in unique:
                            if key in existing:
                                unique[key] = existing[key]
                            else:
                                if any(
                                    item.source_id == candidate.source_id
                                    for item in existing.values()
                                ):
                                    candidate = candidate.model_copy(
                                        update={"source_id": new_id()}
                                    )
                                unique[key] = await repository.add_search_result(
                                    self._run_id, candidate
                                )
                    selected = list(unique.values())
                    await self._commit(session)
        except Exception:
            result = SearchSourcesResult(
                status=ResearchToolStatus.PERSISTENCE_FAILED,
                gap="Search sources could not be saved.",
            )
            self._record("search_sources", result.status)
            return result

        batch_id = new_id()
        self._run_state.search_pages[batch_id] = tuple(
            item.source_id for item in selected
        )
        result = self._search_page(batch_id, selected, 0)
        if selection is not None and need is not None:
            admitted = [
                item
                for item in selected
                if selection.decisions.get(item.source_id) is not None
                and selection.decisions[item.source_id].status == "selected"
            ]
            result = result.model_copy(
                update={
                    "sources": tuple(
                        _tool_source(
                            item,
                            _provider_label(self._search_provider),
                            self._limits.max_snippet_chars,
                        )
                        for item in admitted
                    ),
                    "deferred_source_ids": tuple(
                        item.source_id for item in selected if item not in admitted
                    ),
                    "evidence_need_id": need.need_id,
                    "selection_reasons": {
                        str(item.source_id): selection.decisions[item.source_id].reason
                        for item in selected
                        if item.source_id in selection.decisions
                    },
                }
            )
        self._search_results.extend(
            item
            for item in selected
            if _safe_public_result_url(str(item.url))
            and _domain_policy_allows(str(item.url), self._source_policy)
        )
        self._query_cache[cache_key] = result
        self._record(
            "search_sources",
            result.status,
            source_ids=[str(item.source_id) for item in selected],
            query=request.query,
            selection_reasons=result.selection_reasons,
            lead_bytes={
                "admitted": sum(
                    len(item.model_dump_json(exclude_defaults=True).encode())
                    for item in result.sources
                ),
                "original": sum(
                    len(item.model_dump_json().encode()) for item in selected
                ),
            }
            if selection is not None
            else None,
        )
        return result

    def _search_page(
        self, batch_id: SourceId, sources: list[SearchResult], offset: int
    ) -> SearchSourcesResult:
        end = min(len(sources), offset + self._limits.max_initial_results)
        return SearchSourcesResult(
            status=ResearchToolStatus.SUCCEEDED,
            search_result_id=batch_id,
            total_sources=len(sources),
            next_offset=end if end < len(sources) else None,
            deferred_source_ids=tuple(item.source_id for item in sources[end:]),
            sources=tuple(
                _tool_source(
                    item,
                    _provider_label(self._search_provider),
                    self._limits.max_snippet_chars,
                )
                for item in sources[offset:end]
                if _safe_public_result_url(str(item.url))
                and _domain_policy_allows(str(item.url), self._source_policy)
            ),
            gap=None if sources else "No approved search sources were returned.",
        )

    async def read_search_results(
        self,
        *,
        search_result_id: str | None = None,
        offset: int = 0,
        source_id: str | None = None,
        start_char: int = 0,
        focus: str | None = None,
        need_id: str | None = None,
    ) -> str:
        import json

        selection = self._run_state.selection
        if need_id is not None:
            if selection is None or need_id not in selection.needs:
                return json.dumps(
                    {
                        "status": "invalid_request",
                        "gap": "Evidence need is not in this shopping run.",
                    }
                )
            leads = selection.widen(need_id, limit=self._limits.max_initial_results)
            self._record(
                "read_search_results",
                "widened" if leads else "no_open_deferred_support",
                source_ids=[str(item.source_id) for item in leads],
                evidence_need_id=need_id,
            )
            return SearchSourcesResult(
                status=ResearchToolStatus.SUCCEEDED
                if leads
                else ResearchToolStatus.GAP,
                sources=tuple(
                    _tool_source(
                        item,
                        _provider_label(self._search_provider),
                        self._limits.max_snippet_chars,
                    )
                    for item in leads
                ),
                evidence_need_id=need_id,
                selection_reasons={
                    str(item.source_id): selection.decisions[item.source_id].reason
                    for item in leads
                },
                gap=None
                if leads
                else "No additional useful deferred leads for this open need.",
            ).tool_json()

        if (search_result_id is None) == (source_id is None) or offset < 0:
            return json.dumps(
                {
                    "status": "invalid_request",
                    "gap": "Supply one search batch or source ID and a nonnegative offset.",
                }
            )
        try:
            parsed = SourceId(search_result_id or source_id)
        except (TypeError, ValueError):
            return json.dumps(
                {"status": "invalid_request", "gap": "Invalid search/source ID."}
            )
        async with self._session_lock:
            async with self._session() as session:
                repo = SearchSourceRepository(session)
                if search_result_id is not None:
                    ids = self._run_state.search_pages.get(parsed)
                    if ids is None:
                        return json.dumps(
                            {
                                "status": "unknown_source",
                                "gap": "Search batch is not in this run.",
                            }
                        )
                    sources = [
                        await repo.get_search_result_for_run(self._run_id, item)
                        for item in ids
                    ]
                    if any(item is None for item in sources):
                        return json.dumps(
                            {
                                "status": "unknown_source",
                                "gap": "Original search lead is unavailable.",
                            }
                        )
                    if offset > len(sources):
                        return json.dumps(
                            {
                                "status": "invalid_request",
                                "gap": "Search batch offset is out of range.",
                            }
                        )
                    return self._search_page(
                        parsed, [item for item in sources if item is not None], offset
                    ).tool_json()
                source = await repo.get_search_result_for_run(self._run_id, parsed)
        if source is None:
            return json.dumps(
                {"status": "unknown_source", "gap": "Source is not in this run."}
            )
        if not _safe_public_result_url(str(source.url)) or not _source_policy_allows(
            str(source.url), source.source_type, self._source_policy
        ):
            return json.dumps(
                {"status": "gap", "gap": "Source is outside approved retrieval policy."}
            )
        try:
            span = source_span(
                source.snippet or "", start=start_char, focus=focus, limit=2000
            )
        except ValueError as exc:
            return json.dumps({"status": "invalid_request", "gap": str(exc)})
        return json.dumps(
            {
                "status": "succeeded",
                "source_id": str(parsed),
                "title": source.title,
                "url": _neutral_url(str(source.url)),
                "snippet": span.text,
                "start_char": span.start,
                "total_characters": span.total_characters,
                "content_sha256": span.content_sha256,
                "unreviewed_content": len(span.text) < span.total_characters,
                **_caution_details(source.snippet or ""),
                "gap": "Search snippets are discovery leads, not verified evidence.",
            }
        )

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
        selection = self._run_state.selection
        if request.need_id is not None and (
            selection is None or request.need_id not in selection.needs
        ):
            return FetchSourceResult(
                status=ResearchToolStatus.INVALID_REQUEST,
                gap="Evidence need is not in this shopping run.",
            )
        async with self._lock:
            if self._span_reads >= self._limits.max_fetch_calls * 3:
                return FetchSourceResult(
                    status=ResearchToolStatus.BUDGET_EXHAUSTED,
                    gap="Source span read limit reached.",
                )
            self._span_reads += 1
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
                        result = self._fetch_result(source, cached, request)
                        self._record(
                            "fetch_source",
                            "cached",
                            source_ids=[str(request.source_id)],
                        )
                        return result
                    selection = self._run_state.selection
                    if selection is not None:
                        need = selection.admit_fetch(source, request.need_id)
                        if selection.covered or need is None:
                            self._record(
                                "fetch_source",
                                "coverage_satisfied",
                                source_ids=[str(request.source_id)],
                            )
                            return FetchSourceResult(
                                status=ResearchToolStatus.GAP,
                                source_id=request.source_id,
                                gap="This evidence need already has exact support. Continue to validation, or reread its existing source.",
                            )
                        request = request.model_copy(update={"need_id": need.need_id})
                        self._record(
                            "research_evidence_need",
                            "open",
                            source_ids=[str(request.source_id)],
                            evidence_need_id=need.need_id,
                            query=need.query,
                        )
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

            result = self._fetch_result(source, snapshot, request)
            self._record(
                "fetch_source",
                result.status,
                source_ids=[str(request.source_id), str(snapshot.source_id)],
            )
            return result

    def _fetch_result(
        self,
        source: SearchResult,
        snapshot: SourceSnapshot,
        request: FetchSourceRequest,
    ) -> FetchSourceResult:
        text = (
            snapshot.extracted_content.text
            if snapshot.extracted_content is not None
            else None
        )
        try:
            span = (
                source_span(
                    text,
                    start=request.start_char,
                    focus=request.focus,
                    limit=self._limits.max_page_text_chars,
                )
                if text
                else None
            )
        except ValueError as exc:
            return FetchSourceResult(
                status=ResearchToolStatus.GAP,
                source_id=source.source_id,
                snapshot_id=snapshot.source_id,
                gap=str(exc),
            )
        bounded_text = span.text if span else None
        if span is not None and bounded_text:
            self._observed_spans.setdefault(source.source_id, []).append(
                (span.start, span.start + len(span.text), span.content_sha256)
            )
        if text and self._run_state.selection is not None:
            self._run_state.selection.observe(source.source_id, text)
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
            published_date=(
                snapshot.extracted_content.published_date
                if snapshot.extracted_content is not None
                else None
            ),
            extraction_status=snapshot.extraction_status,
            text=bounded_text,
            start_char=span.start if span else 0,
            total_characters=span.total_characters if span else 0,
            content_sha256=span.content_sha256 if span else None,
            text_truncated=text is not None and len(text) > len(bounded_text or ""),
            unreviewed_content=text is not None and len(text) > len(bounded_text or ""),
            **_caution_details(text or ""),
            provider_name=_provider_label(self._extraction_provider),
            gap=(
                None
                if has_usable_text
                else "Page content is incomplete or unavailable."
            ),
            evidence_need_id=request.need_id,
        )

    def _record(
        self,
        tool_name: str,
        status: ResearchToolStatus | str,
        *,
        source_ids: list[str] | None = None,
        url: str | None = None,
        query: str | None = None,
        support_span: dict[str, Any] | None = None,
        selection_reasons: dict[str, str] | None = None,
        evidence_need_id: str | None = None,
        lead_bytes: dict[str, int] | None = None,
    ) -> None:
        self._activity.append(
            {
                "tool_name": tool_name,
                "status": status,
                "input": {
                    "agent": self._agent_name,
                    "run_id": str(self._run_id),
                    **({"query": query} if query is not None else {}),
                },
                "output": {
                    "source_ids": source_ids or [],
                    **({"url": url} if url is not None else {}),
                    **(
                        {"support_span": support_span}
                        if support_span is not None
                        else {}
                    ),
                    **(
                        {"selection_reasons": selection_reasons}
                        if selection_reasons
                        else {}
                    ),
                    **(
                        {"evidence_need_id": evidence_need_id}
                        if evidence_need_id
                        else {}
                    ),
                    **({"lead_bytes": lead_bytes} if lead_bytes else {}),
                },
            }
        )


def _caution_details(text: str) -> dict[str, Any]:
    from app.agents.research_history import bounded_cautions

    return bounded_cautions(text)


def _tool_source(
    result: SearchResult, provider_name: str, snippet_limit: int = 200
) -> ToolSource:
    return ToolSource(
        source_id=result.source_id,
        url=_neutral_url(str(result.url)),
        title=result.title,
        snippet=result.snippet[:snippet_limit] if result.snippet else None,
        snippet_truncated=bool(result.snippet and len(result.snippet) > snippet_limit),
        unreviewed_content=bool(result.snippet and len(result.snippet) > snippet_limit),
        **_caution_details(result.snippet or ""),
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
    safe_raw: dict[str, Any] = {}
    published_date = original.raw.get("published_date")
    if isinstance(published_date, str) and len(published_date) == 10:
        from datetime import date

        try:
            date.fromisoformat(published_date)
            safe_raw["published_date"] = published_date
        except ValueError:
            pass
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
