from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.agents import FakeQueryPlannerAgent, QueryPlannerAgent, QueryPlannerAgentInput
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.orchestration.fixtures import (
    MonitorFixtureRunOutput,
    build_monitor_fixture_run_output,
)
from app.providers import (
    ExtractionProvider,
    ExtractionProviderOptions,
    FakeExtractionProvider,
    FakeSearchProvider,
    SearchProvider,
    SearchProviderOptions,
    SourceQualityMetadata,
    score_source_quality,
)
from app.schemas.errors import ErrorBody, ErrorEnvelope
from app.schemas.ids import RunId, SessionId
from app.schemas.intake import ShoppingBrief
from app.schemas.regions import RegionCode
from app.schemas.runs import (
    AgentRunRecord,
    RunEvent,
    RunStage,
    RunStatus,
    ShoppingRunRecord,
)
from app.schemas.products import ProductListingExtraction
from app.schemas.search_sources import (
    ExtractionStatus,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceSnapshot,
    SourceType,
)
from app.schemas.timestamps import Timestamp, utc_now
from app.services.product_listing_extraction import ProductListingExtractor


@dataclass(frozen=True)
class FixtureStageOutput:
    stage: RunStage
    trace_id: str
    summary: str
    payload: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveredSourceExtraction:
    search_result: SearchResult
    snapshot: SourceSnapshot
    listing_extraction: ProductListingExtraction | None = None


@dataclass
class ShoppingRunContext:
    run_id: RunId
    session_id: SessionId
    trace_id: str
    stage_outputs: dict[RunStage, FixtureStageOutput] = field(default_factory=dict)
    events: list[RunEvent] = field(default_factory=list)
    agent_records: list[AgentRunRecord] = field(default_factory=list)
    search_plan: SearchPlan | None = None
    search_plan_id: UUID | None = None
    search_results: tuple[SearchResult, ...] = ()
    source_extractions: tuple[DiscoveredSourceExtraction, ...] = ()
    fixture_output: MonitorFixtureRunOutput | None = None


class ShoppingRunPersistenceHooks(Protocol):
    async def load_run(self, run_id: RunId) -> ShoppingRunRecord | None:
        """Load the persisted run before orchestration starts."""

    async def emit_event(
        self,
        run_id: RunId,
        *,
        stage: RunStage,
        status: RunStatus,
        message: str,
        error: ErrorEnvelope | None = None,
    ) -> RunEvent:
        """Persist and return one run event."""

    async def record_stage_trace(
        self,
        *,
        run_id: RunId,
        stage: RunStage,
        agent_name: str,
        status: RunStatus,
        trace_id: str,
        started_at: Timestamp,
        ended_at: Timestamp,
    ) -> AgentRunRecord:
        """Persist and return the trace record for a deterministic fixture stage."""

    async def persist_fixture_output(
        self,
        context: ShoppingRunContext,
        output: MonitorFixtureRunOutput,
    ) -> None:
        """Persist the fixture shopping-run output."""

    async def persist_search_plan(
        self,
        context: ShoppingRunContext,
        plan: SearchPlan,
    ) -> UUID:
        """Persist the query plan before provider discovery starts."""

    async def persist_search_results(
        self,
        context: ShoppingRunContext,
        results: tuple[SearchResult, ...],
        *,
        plan_id: UUID,
    ) -> None:
        """Persist provider discovery results without extracting them."""

    async def persist_source_extractions(
        self,
        context: ShoppingRunContext,
        extractions: tuple[DiscoveredSourceExtraction, ...],
    ) -> None:
        """Persist extracted snapshots and any generated shortlist candidates."""


class RepositoryShoppingRunPersistenceHooks:
    def __init__(
        self,
        *,
        run_repository: RunRepository,
        result_repository: ResultRepository,
        search_source_repository: SearchSourceRepository | None = None,
        product_repository: ProductRepository | None = None,
    ) -> None:
        self._run_repository = run_repository
        self._result_repository = result_repository
        self._search_source_repository = search_source_repository
        self._product_repository = product_repository

    async def load_run(self, run_id: RunId) -> ShoppingRunRecord | None:
        return await self._run_repository.get(run_id)

    async def emit_event(
        self,
        run_id: RunId,
        *,
        stage: RunStage,
        status: RunStatus,
        message: str,
        error: ErrorEnvelope | None = None,
    ) -> RunEvent:
        event = await self._run_repository.append_event(
            run_id,
            stage=stage,
            status=status,
            message=message,
            error=error,
        )
        if event is None:
            raise ValueError(f"Run not found: {run_id}")
        return event

    async def record_stage_trace(
        self,
        *,
        run_id: RunId,
        stage: RunStage,
        agent_name: str,
        status: RunStatus,
        trace_id: str,
        started_at: Timestamp,
        ended_at: Timestamp,
    ) -> AgentRunRecord:
        return await self._result_repository.add_agent_record(
            AgentRunRecord(
                run_id=run_id,
                stage=stage,
                agent_name=agent_name,
                status=status,
                started_at=started_at,
                ended_at=ended_at,
                trace_id=trace_id,
            )
        )

    async def persist_fixture_output(
        self,
        context: ShoppingRunContext,
        output: MonitorFixtureRunOutput,
    ) -> None:
        if self._search_source_repository is None or self._product_repository is None:
            raise ValueError("fixture output persistence requires all repositories.")

        for snapshot in output.source_snapshots:
            await self._search_source_repository.add_source_snapshot(
                context.run_id,
                snapshot,
            )
        for evidence in output.source_evidence:
            await self._search_source_repository.add_source_evidence(
                context.run_id,
                evidence,
            )

        for product in output.products:
            await self._product_repository.add_canonical_product(
                context.run_id,
                product,
            )
        for listing in output.listings:
            await self._product_repository.add_product_listing(context.run_id, listing)
        if not any(
            item.listing_extraction is not None for item in context.source_extractions
        ):
            for item in output.shortlist_items:
                await self._product_repository.add_shortlist_membership(
                    context.run_id,
                    product_id=item.product_id,
                    listing_id=item.listing_id,
                    candidate_id=item.candidate_id,
                    position=item.position,
                )
        for user_added in output.user_added_products:
            await self._product_repository.add_user_added_product(
                context.session_id,
                user_added,
                run_id=context.run_id,
            )

        await self._result_repository.save_result_bundle(
            context.run_id,
            trust_assessments=output.trust_assessments,
            category_analyses=output.category_analyses,
            agent_records=(),
            recommendation_bundle=output.recommendation_bundle,
        )

    async def persist_search_plan(
        self,
        context: ShoppingRunContext,
        plan: SearchPlan,
    ) -> UUID:
        if self._search_source_repository is None:
            raise ValueError("search plan persistence requires a repository.")
        return await self._search_source_repository.create_search_plan(
            context.run_id,
            plan,
        )

    async def persist_search_results(
        self,
        context: ShoppingRunContext,
        results: tuple[SearchResult, ...],
        *,
        plan_id: UUID,
    ) -> None:
        if self._search_source_repository is None:
            raise ValueError("search result persistence requires a repository.")
        for result in results:
            await self._search_source_repository.add_search_result(
                context.run_id,
                result,
                plan_id=plan_id,
            )

    async def persist_source_extractions(
        self,
        context: ShoppingRunContext,
        extractions: tuple[DiscoveredSourceExtraction, ...],
    ) -> None:
        if self._search_source_repository is None or self._product_repository is None:
            raise ValueError("source extraction persistence requires all repositories.")

        shortlist_position = 1
        for item in extractions:
            await self._search_source_repository.add_source_snapshot(
                context.run_id,
                item.snapshot,
                search_result_id=item.search_result.source_id,
            )
            if item.listing_extraction is None:
                continue

            extracted = item.listing_extraction
            await self._product_repository.add_canonical_product(
                context.run_id,
                extracted.product,
            )
            await self._product_repository.add_product_listing(
                context.run_id,
                extracted.listing,
            )
            await self._product_repository.add_shortlist_membership(
                context.run_id,
                product_id=extracted.product.product_id,
                listing_id=extracted.listing.listing_id,
                position=shortlist_position,
            )
            shortlist_position += 1


@dataclass(frozen=True)
class _StageDefinition:
    stage: RunStage
    agent_name: str
    message: str


class ShoppingRunOrchestrator:
    _STAGES: tuple[_StageDefinition, ...] = (
        _StageDefinition(
            RunStage.INTAKE,
            "FixtureIntakeStage",
            "Fixture intake stage recorded.",
        ),
        _StageDefinition(
            RunStage.QUERY_PLANNING,
            "QueryPlanningStage",
            "Search queries planned.",
        ),
        _StageDefinition(
            RunStage.DISCOVERY,
            "SearchProviderDiscoveryStage",
            "Search provider discovery completed.",
        ),
        _StageDefinition(
            RunStage.EXTRACTION,
            "SourceExtractionStage",
            "Shopping sources checked.",
        ),
        _StageDefinition(
            RunStage.DEDUPLICATION,
            "FixtureDeduplicationStage",
            "Fixture deduplication stage recorded.",
        ),
        _StageDefinition(
            RunStage.LISTING_TRUST,
            "FixtureListingTrustStage",
            "Fixture listing trust stage recorded.",
        ),
        _StageDefinition(
            RunStage.CATEGORY_ANALYSIS,
            "FixtureCategoryAnalysisStage",
            "Fixture category analysis stage recorded.",
        ),
        _StageDefinition(
            RunStage.COMPARISON_DECISION,
            "FixtureComparisonDecisionStage",
            "Fixture comparison decision stage recorded.",
        ),
        _StageDefinition(
            RunStage.VERIFICATION,
            "FixtureVerificationStage",
            "Fixture verification stage recorded.",
        ),
    )

    def __init__(
        self,
        persistence_hooks: ShoppingRunPersistenceHooks,
        *,
        query_planner: QueryPlannerAgent | None = None,
        search_provider: SearchProvider | None = None,
        extraction_provider: ExtractionProvider | None = None,
        default_region_code: RegionCode = "US",
    ) -> None:
        self._persistence_hooks = persistence_hooks
        self._query_planner = query_planner or FakeQueryPlannerAgent()
        self._search_provider = search_provider or FakeSearchProvider()
        self._extraction_provider = extraction_provider or FakeExtractionProvider()
        self._listing_extractor = ProductListingExtractor()
        self._default_region_code = default_region_code

    @classmethod
    def stage_order(cls) -> tuple[RunStage, ...]:
        return tuple(stage.stage for stage in cls._STAGES) + (RunStage.COMPLETE,)

    @classmethod
    def executable_stage_order(cls) -> tuple[RunStage, ...]:
        return tuple(stage.stage for stage in cls._STAGES)

    async def run(
        self,
        run_id: RunId,
        brief: ShoppingBrief | None = None,
    ) -> ShoppingRunContext:
        run = await self._persistence_hooks.load_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        context = ShoppingRunContext(
            run_id=run_id,
            session_id=run.session_id,
            trace_id=self._run_trace_id(run_id),
        )
        fixture_output = build_monitor_fixture_run_output(
            run_id=context.run_id,
            session_id=context.session_id,
        )
        active_brief = brief or ShoppingBrief(
            original_query=fixture_output.search_plan.queries[0].query
        )

        try:
            for definition in self._STAGES:
                await self._run_stage(context, definition, active_brief)

            await self._persistence_hooks.persist_fixture_output(
                context,
                fixture_output,
            )
            context.fixture_output = fixture_output

            complete_event = await self._persistence_hooks.emit_event(
                run_id,
                stage=RunStage.COMPLETE,
                status=RunStatus.SUCCEEDED,
                message="Fixture shopping run completed.",
            )
            context.events.append(complete_event)
        except Exception as exc:
            failed_stage = self._current_or_initial_stage(context)
            failed_event = await self._persistence_hooks.emit_event(
                run_id,
                stage=failed_stage,
                status=RunStatus.FAILED,
                message="Fixture shopping run failed.",
                error=_orchestrator_error(context.trace_id, failed_stage, exc),
            )
            context.events.append(failed_event)
            raise

        return context

    async def _run_stage(
        self,
        context: ShoppingRunContext,
        definition: _StageDefinition,
        brief: ShoppingBrief,
    ) -> None:
        started_at = utc_now()
        if definition.stage == RunStage.QUERY_PLANNING:
            stage_output = await self._plan_queries(context, brief)
        elif definition.stage == RunStage.DISCOVERY:
            stage_output = await self._discover_sources(context, brief)
        elif definition.stage == RunStage.EXTRACTION:
            stage_output = await self._extract_sources(context, brief)
        else:
            stage_output = self._fixture_stage_output(context, definition.stage)
        ended_at = utc_now()

        context.stage_outputs[definition.stage] = stage_output
        agent_record = await self._persistence_hooks.record_stage_trace(
            run_id=context.run_id,
            stage=definition.stage,
            agent_name=definition.agent_name,
            status=RunStatus.SUCCEEDED,
            trace_id=stage_output.trace_id,
            started_at=started_at,
            ended_at=ended_at,
        )
        context.agent_records.append(agent_record)

        event = await self._persistence_hooks.emit_event(
            context.run_id,
            stage=definition.stage,
            status=RunStatus.RUNNING,
            message=(
                stage_output.summary
                if definition.stage == RunStage.EXTRACTION
                else definition.message
            ),
        )
        context.events.append(event)

    async def _plan_queries(
        self,
        context: ShoppingRunContext,
        brief: ShoppingBrief,
    ) -> FixtureStageOutput:
        plan = await self._query_planner.run(
            QueryPlannerAgentInput(run_id=context.run_id, brief=brief)
        )
        region_code = _effective_region_code(brief, self._default_region_code)
        plan = plan.model_copy(
            update={
                "queries": tuple(
                    query
                    if query.region_code is not None
                    else query.model_copy(update={"region_code": region_code})
                    for query in plan.queries
                )
            }
        )
        plan_id = await self._persistence_hooks.persist_search_plan(context, plan)
        context.search_plan = plan
        context.search_plan_id = plan_id
        return FixtureStageOutput(
            stage=RunStage.QUERY_PLANNING,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.QUERY_PLANNING),
            summary="Search queries planned.",
            payload={"query_count": str(len(plan.queries))},
        )

    async def _discover_sources(
        self,
        context: ShoppingRunContext,
        brief: ShoppingBrief,
    ) -> FixtureStageOutput:
        if context.search_plan is None or context.search_plan_id is None:
            raise ValueError("search discovery requires a persisted query plan.")

        region_code = _effective_region_code(brief, self._default_region_code)
        options = SearchProviderOptions(
            region_code=region_code,
            category=brief.category,
        )
        discovered: list[SearchResult] = []
        for query in context.search_plan.queries:
            provider_results = await self._search_provider.search(query, options)
            discovered.extend(
                _score_search_results(
                    tuple(
                        _apply_planned_source_type(result, query)
                        for result in provider_results
                    ),
                    region_code=region_code,
                )
            )

        context.search_results = tuple(discovered)
        await self._persistence_hooks.persist_search_results(
            context,
            context.search_results,
            plan_id=context.search_plan_id,
        )
        provider_name = getattr(
            self._search_provider,
            "provider_name",
            self._search_provider.__class__.__name__,
        )
        return FixtureStageOutput(
            stage=RunStage.DISCOVERY,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.DISCOVERY),
            summary="Search provider discovery completed.",
            payload={
                "provider": str(provider_name),
                "result_count": str(len(context.search_results)),
            },
        )

    async def _extract_sources(
        self,
        context: ShoppingRunContext,
        brief: ShoppingBrief,
    ) -> FixtureStageOutput:
        region_code = _effective_region_code(brief, self._default_region_code)
        extracted_sources: list[DiscoveredSourceExtraction] = []
        for result in _selected_extraction_results(context.search_results):
            snapshot = await self._extraction_provider.extract(
                result.url,
                ExtractionProviderOptions(source_type=result.source_type),
            )
            snapshot = _link_snapshot_to_search_result(
                snapshot,
                result,
                region_code=region_code,
            )
            listing_extraction = _listing_from_extracted_source(
                self._listing_extractor,
                result=result,
                snapshot=snapshot,
                category=brief.category,
            )
            extracted_sources.append(
                DiscoveredSourceExtraction(
                    search_result=result,
                    snapshot=snapshot,
                    listing_extraction=listing_extraction,
                )
            )

        context.source_extractions = tuple(extracted_sources)
        await self._persistence_hooks.persist_source_extractions(
            context,
            context.source_extractions,
        )
        listing_count = sum(
            item.listing_extraction is not None for item in context.source_extractions
        )
        provider_name = getattr(
            self._extraction_provider,
            "provider_name",
            self._extraction_provider.__class__.__name__,
        )
        return FixtureStageOutput(
            stage=RunStage.EXTRACTION,
            trace_id=self._stage_trace_id(context.trace_id, RunStage.EXTRACTION),
            summary=(
                f"Checked {_counted(len(context.source_extractions), 'shopping source')} "
                f"and added {_counted(listing_count, 'product')} to compare."
            ),
            payload={
                "provider": str(provider_name),
                "snapshot_count": str(len(context.source_extractions)),
                "listing_count": str(listing_count),
            },
        )

    def _fixture_stage_output(
        self,
        context: ShoppingRunContext,
        stage: RunStage,
    ) -> FixtureStageOutput:
        return FixtureStageOutput(
            stage=stage,
            trace_id=self._stage_trace_id(context.trace_id, stage),
            summary=f"Fixture output for {stage.value}.",
            payload={
                "mode": "fixture",
                "stage": stage.value,
            },
        )

    def _current_or_initial_stage(self, context: ShoppingRunContext) -> RunStage:
        if context.events:
            return context.events[-1].stage
        return RunStage.INTAKE

    @staticmethod
    def _run_trace_id(run_id: RunId) -> str:
        return f"fixture-run-{run_id}"

    @staticmethod
    def _stage_trace_id(run_trace_id: str, stage: RunStage) -> str:
        return f"{run_trace_id}:{stage.value}"


def _orchestrator_error(
    trace_id: str,
    stage: RunStage,
    error: Exception,
) -> ErrorEnvelope:
    return ErrorEnvelope(
        error=ErrorBody(
            code="orchestrator_stage_failed",
            message=str(error) or error.__class__.__name__,
            request_id=trace_id,
            details={"stage": stage.value},
        )
    )


def _score_search_results(
    results: tuple[SearchResult, ...],
    *,
    region_code: RegionCode,
) -> tuple[SearchResult, ...]:
    scored: list[SearchResult] = []
    for result in results:
        assessment = score_source_quality(
            str(result.url),
            SourceQualityMetadata(target_region_code=region_code),
        )
        if assessment.excluded:
            continue
        provider = result.provider.model_copy(
            update={
                "raw": {
                    **result.provider.raw,
                    "source_policy_version": assessment.policy_version,
                    "source_class": assessment.source_class.value,
                    "requires_trust_assessment": (assessment.requires_trust_assessment),
                    "region_relevance": assessment.region_relevance.value,
                    "region_relevance_score": assessment.region_relevance_score,
                }
            }
        )
        scored.append(
            result.model_copy(
                update={
                    "provider": provider,
                    "quality": assessment.quality,
                    "url": assessment.normalized_url,
                }
            )
        )
    return tuple(scored)


def _apply_planned_source_type(
    result: SearchResult,
    query: SearchQuery,
) -> SearchResult:
    if (
        result.source_type == SourceType.SEARCH_RESULT
        and len(query.required_source_types) == 1
    ):
        return result.model_copy(
            update={"source_type": query.required_source_types[0]}
        )
    return result


def _selected_extraction_results(
    results: tuple[SearchResult, ...],
) -> tuple[SearchResult, ...]:
    return tuple(
        result
        for result in results
        if result.source_type not in {SourceType.SEARCH_RESULT, SourceType.VIDEO}
    )


def _link_snapshot_to_search_result(
    snapshot: SourceSnapshot,
    result: SearchResult,
    *,
    region_code: RegionCode,
) -> SourceSnapshot:
    provider = snapshot.provider.model_copy(
        update={
            "raw": {
                **snapshot.provider.raw,
                "search_result_source_id": str(result.source_id),
                "search_provider": result.provider.provider_name,
                "search_provider_result_id": result.provider.provider_result_id,
                "target_region_code": region_code,
            }
        }
    )
    return snapshot.model_copy(
        update={
            "source_type": result.source_type,
            "title": snapshot.title or result.title,
            "provider": provider,
            "quality": result.quality,
        }
    )


def _listing_from_extracted_source(
    extractor: ProductListingExtractor,
    *,
    result: SearchResult,
    snapshot: SourceSnapshot,
    category: str | None,
) -> ProductListingExtraction | None:
    if snapshot.extraction_status not in {
        ExtractionStatus.SUCCEEDED,
        ExtractionStatus.PARTIAL,
    }:
        return None

    if (
        snapshot.source_type
        in {
            SourceType.PRODUCT_PAGE,
            SourceType.RETAILER_LISTING,
            SourceType.OFFICIAL_BRAND_PAGE,
        }
        and snapshot.extracted_content is not None
    ):
        extracted = extractor.extract_source_snapshot(snapshot)
    else:
        extracted = extractor.extract_search_result(result)

    if category is None or extracted.product.category is not None:
        return extracted
    return extracted.model_copy(
        update={
            "product": extracted.product.model_copy(update={"category": category})
        }
    )


def _effective_region_code(
    brief: ShoppingBrief,
    default_region_code: RegionCode,
) -> RegionCode:
    if brief.region is not None:
        return brief.region.region.code
    return default_region_code


def _counted(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"
