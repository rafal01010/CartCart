from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.settings import Settings
from app.db.session import (
    create_database_engine,
    create_session_factory,
    make_sqlite_url,
)


def test_make_sqlite_url_uses_async_sqlite_driver(tmp_path: Path) -> None:
    database_path = tmp_path / "cartcart.sqlite3"

    assert make_sqlite_url(database_path).startswith("sqlite+aiosqlite:////")
    assert make_sqlite_url(database_path).endswith("/cartcart.sqlite3")


@pytest.mark.asyncio
async def test_async_session_factory_opens_sqlite_session(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "test.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            result = await session.execute(text("select 1"))

        assert result.scalar_one() == 1
    finally:
        await engine.dispose()
