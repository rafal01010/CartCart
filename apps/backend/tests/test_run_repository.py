from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.db.models.runs import ShoppingRunRecordModel
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.schemas.analysis import RecommendationBundle
from app.schemas.errors import ErrorBody, ErrorEnvelope
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.runs import AgentRunRecord, RunStage, RunStatus, ShoppingRunRecord
from app.schemas.search_sources import SourceSnapshot
from app.services.runs import RunService


def lifecycle_error() -> ErrorEnvelope:
    return ErrorEnvelope(error=ErrorBody(
        code="fixture_failure", message="Saved failure.", request_id="lifecycle-control"
    ))


@pytest_asyncio.fixture
async def lifecycle_sessions(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, database_path=tmp_path / "lifecycle.sqlite3"
    )
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_lifecycle_keeps_intermediate_success_active_until_complete(
    lifecycle_sessions: async_sessionmaker[AsyncSession],
) -> None:
    factory = lifecycle_sessions
    run = await create_lifecycle_run(factory)
    steps = (
        (RunStage.INTAKE, RunStatus.PENDING, RunStatus.PENDING),
        (RunStage.INTAKE, RunStatus.SUCCEEDED, RunStatus.RUNNING),
        (RunStage.QUERY_PLANNING, RunStatus.PENDING, RunStatus.RUNNING),
        (RunStage.QUERY_PLANNING, RunStatus.RUNNING, RunStatus.RUNNING),
        (RunStage.COMPLETE, RunStatus.RUNNING, RunStatus.RUNNING),
        (RunStage.COMPLETE, RunStatus.SUCCEEDED, RunStatus.SUCCEEDED),
    )
    first_start = None
    for sequence, (stage, event_status, aggregate_status) in enumerate(steps):
        async with factory() as db:
            event = await RunRepository(db).append_event(
                run.run_id, stage=stage, status=event_status, message="Stage update."
            )
            assert event is not None
            await db.commit()
        async with factory() as db:
            repository = RunRepository(db)
            loaded = await repository.get(run.run_id)
            events = await repository.list_events(run.run_id)
            assert loaded is not None
            if sequence == 1:
                first_start = event.occurred_at
            assert loaded.status == aggregate_status
            assert loaded.current_stage == stage
            assert loaded.started_at == first_start
            assert loaded.completed_at == (
                event.occurred_at if aggregate_status == RunStatus.SUCCEEDED else None
            )
            assert loaded.error is None
            assert len(events) == sequence + 1
            assert events[-1] == event
            assert [item.sequence for item in events] == list(range(sequence + 1))


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", [RunStatus.FAILED, RunStatus.CANCELLED])
@pytest.mark.parametrize("started", [False, True])
async def test_run_lifecycle_failure_and_cancellation_preserve_optional_start(
    lifecycle_sessions: async_sessionmaker[AsyncSession],
    terminal_status: RunStatus,
    started: bool,
) -> None:
    factory = lifecycle_sessions
    run = await create_lifecycle_run(factory)
    async with factory() as db:
        repository = RunRepository(db)
        start_event = None
        if started:
            start_event = await repository.append_event(
                run.run_id, stage=RunStage.INTAKE, status=RunStatus.RUNNING,
                message="Started execution.",
            )
        error = lifecycle_error() if terminal_status == RunStatus.FAILED else None
        event = await repository.append_event(
            run.run_id, stage=RunStage.GENERAL_OWNER, status=terminal_status,
            message="Stopped execution.", error=error,
        )
        assert event is not None
        await db.commit()
    async with factory() as db:
        loaded = await RunRepository(db).get(run.run_id)
        assert loaded is not None
        assert loaded.status == terminal_status
        assert loaded.current_stage == RunStage.GENERAL_OWNER
        assert loaded.started_at == (start_event.occurred_at if start_event else None)
        assert loaded.completed_at == event.occurred_at
        assert loaded.error == error
        assert (await RunRepository(db).list_events(run.run_id))[-1] == event


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal_status", [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED]
)
@pytest.mark.parametrize(
    ("stage", "status"),
    [
        (RunStage.QUERY_PLANNING, RunStatus.PENDING),
        (RunStage.QUERY_PLANNING, RunStatus.RUNNING),
        (RunStage.QUERY_PLANNING, RunStatus.SUCCEEDED),
        (RunStage.COMPLETE, RunStatus.SUCCEEDED),
        (RunStage.QUERY_PLANNING, RunStatus.FAILED),
        (RunStage.QUERY_PLANNING, RunStatus.CANCELLED),
    ],
)
async def test_run_lifecycle_terminal_rejection_leaves_no_partial_write(
    lifecycle_sessions: async_sessionmaker[AsyncSession],
    terminal_status: RunStatus,
    stage: RunStage,
    status: RunStatus,
) -> None:
    factory = lifecycle_sessions
    run = await create_lifecycle_run(factory)
    async with factory() as db:
        repository = RunRepository(db)
        await repository.append_event(
            run.run_id, stage=RunStage.COMPLETE, status=terminal_status,
            message="Original terminal event.",
            error=lifecycle_error() if terminal_status == RunStatus.FAILED else None,
        )
        await db.commit()
    async with factory() as db:
        repository = RunRepository(db)
        before = await repository.get(run.run_id)
        history = await repository.list_events(run.run_id)
        with pytest.raises(ValueError, match="terminal shopping runs"):
            await repository.append_event(
                run.run_id, stage=stage, status=status, message="Rejected event.",
                error=lifecycle_error() if status == RunStatus.FAILED else None,
            )
        await db.commit()
    async with factory() as db:
        repository = RunRepository(db)
        assert await repository.get(run.run_id) == before
        assert await repository.list_events(run.run_id) == history


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED])
async def test_run_lifecycle_invalid_target_does_not_mutate_pending_run(
    lifecycle_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    status: RunStatus,
) -> None:
    factory = lifecycle_sessions
    run = await create_lifecycle_run(factory)
    monkeypatch.setattr(
        "app.db.repositories.runs.utc_now", lambda: run.created_at - timedelta(seconds=1)
    )
    async with factory() as db:
        repository = RunRepository(db)
        with pytest.raises(ValidationError):
            await repository.append_event(
                run.run_id, stage=RunStage.COMPLETE, status=status,
                message="Impossible timing.",
                error=lifecycle_error() if status == RunStatus.FAILED else None,
            )
        await db.commit()
    async with factory() as db:
        repository = RunRepository(db)
        assert await repository.get(run.run_id) == run
        assert await repository.list_events(run.run_id) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_run_lifecycle_explicit_retry_claim_preserves_saved_work(
    lifecycle_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    started: bool,
) -> None:
    factory = lifecycle_sessions
    run = await create_lifecycle_run(factory)
    async with factory() as db:
        repository = RunRepository(db)
        shopping = await SessionRepository(db).get(run.session_id)
        assert shopping is not None
        if started:
            await repository.append_event(
                run.run_id, stage=RunStage.INTAKE, status=RunStatus.RUNNING,
                message="Original execution started.",
            )
        trace = AgentRunRecord(
            run_id=run.run_id, stage=RunStage.GENERAL_OWNER,
            agent_name="SavedOwner", status=RunStatus.FAILED,
            started_at=run.created_at, ended_at=run.created_at,
            input_tokens=12, output_tokens=24, total_tokens=36,
            error=lifecycle_error(),
            tool_activity=({
                "tool_name": "general_owner_checkpoint",
                "input": {"original_input": shopping.original_input.model_dump(mode="json")},
                "output": {"saved": "research"},
            },),
        )
        results = ResultRepository(db)
        await results.add_agent_record(trace)
        source = SourceSnapshot(
            url="https://example.test/saved-research", title="Saved research",
            source_type="other", provider={"provider_name": "offline-control"},
            extraction_status="succeeded",
        )
        await SearchSourceRepository(db).add_source_snapshot(run.run_id, source)
        saved = await results.save_result_bundle(
            run.run_id, trust_assessments=(), category_analyses=(), agent_records=(),
            recommendation_bundle=RecommendationBundle(
                no_strong_buy=True, no_strong_buy_reason="Saved advice awaiting retry."
            ),
        )
        await repository.append_event(
            run.run_id, stage=RunStage.GENERAL_OWNER, status=RunStatus.FAILED,
            message="Original attempt failed.", error=lifecycle_error(),
        )
        before = await repository.get(run.run_id)
        history = await repository.list_events(run.run_id)
        saved_before = await results.load_result_bundle_by_version(saved.result_version.result_version_id)
        await db.commit()
    async with factory() as db:
        repository = RunRepository(db)
        identity = await db.get(ShoppingRunRecordModel, str(run.run_id))
        assert identity is not None
        observed = []

        class ResumeSavedDecision:
            async def resume(self, run_id, brief, **kwargs):
                claimed = await repository.get(run_id)
                assert claimed is not None
                assert claimed.status == RunStatus.RUNNING
                assert claimed.completed_at is None
                assert claimed.error is None
                assert claimed.started_at is not None
                assert before is not None
                if started:
                    assert claimed.started_at == before.started_at
                observed.append(claimed)
                assert brief == shopping.current_brief
                assert kwargs["original_input"] == shopping.original_input
                await repository.append_event(
                    run_id, stage=RunStage.COMPLETE, status=RunStatus.SUCCEEDED,
                    message="Saved decision resumed.",
                )
                await repository.checkpoint()

        monkeypatch.setattr(RunService, "_orchestrator", lambda self: ResumeSavedDecision())
        service = RunService(
            SessionRepository(db), repository, ResultRepository(db), SearchSourceRepository(db)
        )
        after = await service.retry_run(run.session_id, run.run_id)
        assert after is not None
        assert after.status == RunStatus.SUCCEEDED
        assert identity.status == RunStatus.SUCCEEDED.value
        assert len(observed) == 1
        assert after.started_at == observed[0].started_at
    async with factory() as db:
        repository = RunRepository(db)
        assert await repository.get(run.run_id) == after
        events = await repository.list_events(run.run_id)
        assert events[:len(history)] == history
        assert [event.sequence for event in events] == list(range(len(history) + 2))
        assert await ResultRepository(db).list_agent_records(run.run_id) == (trace,)
        assert await SearchSourceRepository(db).list_source_snapshots(run.run_id) == (source,)
        assert await ResultRepository(db).load_result_bundle_by_version(
            saved.result_version.result_version_id
        ) == saved_before
        assert await SessionRepository(db).get(run.session_id) == shopping


async def create_lifecycle_run(
    factory: async_sessionmaker[AsyncSession],
) -> ShoppingRunRecord:
    async with factory() as db:
        shopping = await SessionRepository(db).create(
            original_input=CreateSessionRequest(query="Need headphones"),
            current_brief=ShoppingBrief(original_query="Need headphones"),
        )
        run = await RunRepository(db).create(shopping.session_id)
        await db.commit()
        return run


@pytest.mark.asyncio
async def test_run_repository_creates_run_and_loads_latest_status(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "runs.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a travel laptop"),
                current_brief=ShoppingBrief(original_query="Need a travel laptop"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            repository = RunRepository(db_session)
            started_event = await repository.append_event(
                run.run_id,
                stage=RunStage.INTAKE,
                status=RunStatus.RUNNING,
                message="Intake started.",
            )
            completed_event = await repository.append_event(
                run.run_id,
                stage=RunStage.COMPLETE,
                status=RunStatus.SUCCEEDED,
                message="Run completed.",
            )
            await db_session.commit()

        async with session_factory() as db_session:
            loaded = await RunRepository(db_session).get(run.run_id)

        assert started_event is not None
        assert completed_event is not None
        assert started_event.sequence == 0
        assert completed_event.sequence == 1
        assert loaded is not None
        assert loaded.run_id == run.run_id
        assert loaded.session_id == shopping_session.session_id
        assert loaded.status == RunStatus.SUCCEEDED
        assert loaded.current_stage == RunStage.COMPLETE
        assert loaded.started_at == started_event.occurred_at
        assert loaded.completed_at == completed_event.occurred_at

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_repository_loads_events_ordered_by_sequence(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "runs.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need headphones"),
                current_brief=ShoppingBrief(original_query="Need headphones"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            repository = RunRepository(db_session)
            await repository.append_event(
                run.run_id,
                stage=RunStage.INTAKE,
                status=RunStatus.RUNNING,
                message="Intake started.",
            )
            await repository.append_event(
                run.run_id,
                stage=RunStage.QUERY_PLANNING,
                status=RunStatus.RUNNING,
                message="Query planning started.",
            )
            await db_session.commit()

        async with session_factory() as db_session:
            events = await RunRepository(db_session).list_events(run.run_id)

        assert [event.sequence for event in events] == [0, 1]
        assert [event.stage for event in events] == [
            RunStage.INTAKE,
            RunStage.QUERY_PLANNING,
        ]
        assert [event.message for event in events] == [
            "Intake started.",
            "Query planning started.",
        ]

    finally:
        await engine.dispose()
