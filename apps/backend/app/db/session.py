from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import Settings, get_settings


def make_sqlite_url(database_path: Path) -> str:
    resolved_path = database_path.expanduser().resolve()
    return f"sqlite+aiosqlite:///{resolved_path.as_posix()}"


def make_database_url(settings: Settings) -> str:
    return make_sqlite_url(settings.resolved_database_path)


def create_database_engine(settings: Settings) -> AsyncEngine:
    settings.resolved_database_path.parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(make_database_url(settings))


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_database_engine(get_settings())
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(get_engine())
    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session

