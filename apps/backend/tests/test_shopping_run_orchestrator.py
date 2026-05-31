from pathlib import Path

import pytest

import app.db.models  # noqa: F401
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.orchestration import (
    RepositoryShoppingRunPersistenceHooks,
    ShoppingRunOrchestrator,
)
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.runs import RunStage, RunStatus


@pytest.mark.asyncio
async def test_shopping_run_orchestrator_records_all_expected_fixture_stages(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a 27 inch monitor"),
                current_brief=ShoppingBrief(original_query="Need a 27 inch monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            run_repository = RunRepository(db_session)
            result_repository = ResultRepository(db_session)
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=run_repository,
                    result_repository=result_repository,
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                )
            )

            context = await orchestrator.run(run.run_id)
            await db_session.commit()

        async with session_factory() as db_session:
            run_repository = RunRepository(db_session)
            result_repository = ResultRepository(db_session)
            loaded_run = await run_repository.get(run.run_id)
            events = await run_repository.list_events(run.run_id)
            agent_records = await result_repository.list_agent_records(run.run_id)

        expected_stages = ShoppingRunOrchestrator.stage_order()
        executable_stages = ShoppingRunOrchestrator.executable_stage_order()

        assert loaded_run is not None
        assert loaded_run.status == RunStatus.SUCCEEDED
        assert loaded_run.current_stage == RunStage.COMPLETE
        assert context.session_id == shopping_session.session_id
        assert context.trace_id == f"fixture-run-{run.run_id}"
        assert tuple(event.stage for event in events) == expected_stages
        assert tuple(event.sequence for event in events) == tuple(
            range(len(expected_stages))
        )
        expected_statuses = (RunStatus.RUNNING,) * len(executable_stages) + (
            RunStatus.SUCCEEDED,
        )
        assert tuple(event.status for event in events) == expected_statuses
        assert tuple(context.stage_outputs) == executable_stages
        assert {record.stage for record in agent_records} == set(executable_stages)
        assert {
            record.trace_id for record in agent_records
        } == {
            f"{context.trace_id}:{stage.value}" for stage in executable_stages
        }

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_shopping_run_orchestrator_persists_monitor_fixture_output(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "orchestrator-fixture.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        async with session_factory() as db_session:
            shopping_session = await SessionRepository(db_session).create(
                original_input=CreateSessionRequest(query="Need a 27 inch monitor"),
                current_brief=ShoppingBrief(original_query="Need a 27 inch monitor"),
            )
            run = await RunRepository(db_session).create(shopping_session.session_id)
            await db_session.commit()

        async with session_factory() as db_session:
            orchestrator = ShoppingRunOrchestrator(
                RepositoryShoppingRunPersistenceHooks(
                    run_repository=RunRepository(db_session),
                    result_repository=ResultRepository(db_session),
                    search_source_repository=SearchSourceRepository(db_session),
                    product_repository=ProductRepository(db_session),
                )
            )

            context = await orchestrator.run(run.run_id)
            await db_session.commit()

        assert context.fixture_output is not None

        async with session_factory() as db_session:
            search_repository = SearchSourceRepository(db_session)
            product_repository = ProductRepository(db_session)
            result_repository = ResultRepository(db_session)
            search_results = await search_repository.list_search_results(run.run_id)
            source_snapshots = await search_repository.list_source_snapshots(run.run_id)
            source_evidence = await search_repository.list_source_evidence(run.run_id)
            shortlist = await product_repository.list_shortlist_memberships(run.run_id)
            user_added = await product_repository.list_user_added_products(
                shopping_session.session_id
            )
            result = await result_repository.load_latest_result_bundle(run.run_id)
            listing_count_items: list[int] = []
            for product in context.fixture_output.products:
                product_listings = await product_repository.list_listings_for_product(
                    product.product_id
                )
                listing_count_items.append(len(product_listings))
            listing_counts = tuple(listing_count_items)

        fixture = context.fixture_output
        assert len(search_results) == len(fixture.search_results)
        assert len(source_snapshots) == len(fixture.source_snapshots)
        assert len(source_evidence) == len(fixture.source_evidence)
        assert len(shortlist) == 4
        assert len(user_added) == 1
        assert user_added[0].listing is not None
        assert user_added[0].listing.seller.seller_name == "FlashDealz Outlet"
        assert result is not None
        assert result.result_version.version == 1
        assert result.recommendation_bundle.final_rationale is not None
        assert result.recommendation_bundle.final_product_id == (
            fixture.recommendation_bundle.final_product_id
        )
        assert len(result.recommendation_bundle.runner_up_product_ids) == 2
        assert result.recommendation_bundle.rejected_items[0].listing_id == (
            user_added[0].listing.listing_id
        )
        assert any(
            assessment.level.value == "suspicious"
            for assessment in result.trust_assessments
        )
        assert any(count > 1 for count in listing_counts)

    finally:
        await engine.dispose()
