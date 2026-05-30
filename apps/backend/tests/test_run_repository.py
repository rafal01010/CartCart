from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.runs import RunStage, RunStatus


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
