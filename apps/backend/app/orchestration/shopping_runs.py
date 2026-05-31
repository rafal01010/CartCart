from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.orchestration.fixtures import (
    MonitorFixtureRunOutput,
    build_monitor_fixture_run_output,
)
from app.schemas.errors import ErrorBody, ErrorEnvelope
from app.schemas.ids import RunId, SessionId
from app.schemas.runs import (
    AgentRunRecord,
    RunEvent,
    RunStage,
    RunStatus,
    ShoppingRunRecord,
)
from app.schemas.timestamps import Timestamp, utc_now


@dataclass(frozen=True)
class FixtureStageOutput:
    stage: RunStage
    trace_id: str
    summary: str
    payload: Mapping[str, str] = field(default_factory=dict)


@dataclass
class ShoppingRunContext:
    run_id: RunId
    session_id: SessionId
    trace_id: str
    stage_outputs: dict[RunStage, FixtureStageOutput] = field(default_factory=dict)
    events: list[RunEvent] = field(default_factory=list)
    agent_records: list[AgentRunRecord] = field(default_factory=list)
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

        plan_id = await self._search_source_repository.create_search_plan(
            context.run_id,
            output.search_plan,
        )
        for result in output.search_results:
            await self._search_source_repository.add_search_result(
                context.run_id,
                result,
                plan_id=plan_id,
            )
        for snapshot in output.source_snapshots:
            await self._search_source_repository.add_source_snapshot(
                context.run_id,
                snapshot,
                search_result_id=snapshot.source_id,
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
            "FixtureQueryPlanningStage",
            "Fixture query planning stage recorded.",
        ),
        _StageDefinition(
            RunStage.DISCOVERY,
            "FixtureDiscoveryStage",
            "Fixture discovery stage recorded.",
        ),
        _StageDefinition(
            RunStage.EXTRACTION,
            "FixtureExtractionStage",
            "Fixture extraction stage recorded.",
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

    def __init__(self, persistence_hooks: ShoppingRunPersistenceHooks) -> None:
        self._persistence_hooks = persistence_hooks

    @classmethod
    def stage_order(cls) -> tuple[RunStage, ...]:
        return tuple(stage.stage for stage in cls._STAGES) + (RunStage.COMPLETE,)

    @classmethod
    def executable_stage_order(cls) -> tuple[RunStage, ...]:
        return tuple(stage.stage for stage in cls._STAGES)

    async def run(self, run_id: RunId) -> ShoppingRunContext:
        run = await self._persistence_hooks.load_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")

        context = ShoppingRunContext(
            run_id=run_id,
            session_id=run.session_id,
            trace_id=self._run_trace_id(run_id),
        )

        try:
            for definition in self._STAGES:
                await self._run_stage(context, definition)

            fixture_output = build_monitor_fixture_run_output(
                run_id=context.run_id,
                session_id=context.session_id,
            )
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
    ) -> None:
        started_at = utc_now()
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
            message=definition.message,
        )
        context.events.append(event)

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
