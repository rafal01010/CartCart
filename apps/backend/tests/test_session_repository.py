from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.schemas.intake import (
    BudgetConstraint,
    BudgetMode,
    CreateSessionRequest,
    FieldSource,
    PreferenceConstraint,
    PreferenceMode,
    ShoppingBrief,
)
from app.schemas.money import Money


@pytest.mark.asyncio
async def test_session_repository_creates_and_loads_session(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "sessions.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        original_input = CreateSessionRequest(
            query="Need a portable monitor",
            budget=BudgetConstraint(
                amount=Money(amount="250.00", currency="USD"),
                mode=BudgetMode.PREFERRED,
            ),
        )
        brief = ShoppingBrief(
            original_query=original_input.query,
            category="monitor",
            category_source=FieldSource.INFERRED,
        )

        async with session_factory() as db_session:
            created = await SessionRepository(db_session).create(
                original_input=original_input,
                current_brief=brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            loaded = await SessionRepository(db_session).get(created.session_id)

        assert loaded is not None
        assert loaded.session_id == created.session_id
        assert loaded.original_input.query == "Need a portable monitor"
        assert loaded.original_input.budget is not None
        assert loaded.current_brief.category == "monitor"
        assert loaded.created_at == created.created_at
        assert loaded.updated_at == created.updated_at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_repository_updates_current_brief(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "sessions.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        original_input = CreateSessionRequest(query="Need headphones for calls")
        initial_brief = ShoppingBrief(original_query=original_input.query)
        updated_brief = ShoppingBrief(
            original_query=original_input.query,
            category="headphones",
            category_source=FieldSource.INFERRED,
            preferences=(
                PreferenceConstraint(
                    text="Prefer a clear microphone.",
                    mode=PreferenceMode.SOFT,
                    source=FieldSource.USER_PROVIDED,
                ),
            ),
        )

        async with session_factory() as db_session:
            created = await SessionRepository(db_session).create(
                original_input=original_input,
                current_brief=initial_brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            updated = await SessionRepository(db_session).update_current_brief(
                created.session_id,
                updated_brief,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            loaded = await SessionRepository(db_session).get(created.session_id)

        assert updated is not None
        assert loaded is not None
        assert loaded.original_input.query == original_input.query
        assert loaded.current_brief.category == "headphones"
        assert loaded.current_brief.preferences[0].text == "Prefer a clear microphone."
        assert loaded.updated_at >= created.updated_at
    finally:
        await engine.dispose()
