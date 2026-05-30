from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.schemas.confidence import Confidence, ConfidenceLevel
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.search_sources import (
    EvidenceTarget,
    EvidenceTargetType,
    EvidenceType,
    ExtractionStatus,
    ProviderMetadata,
    SearchIntent,
    SearchPlan,
    SearchQuery,
    SearchResult,
    SourceEvidence,
    SourceQuality,
    SourceQualityLevel,
    SourceSnapshot,
    SourceType,
)


def make_provider() -> ProviderMetadata:
    return ProviderMetadata(
        provider_name="fixture-search",
        provider_result_id="result-1",
        query_id="query-1",
        raw={"rank": 1, "provider_score": 0.92},
    )


def make_query() -> SearchQuery:
    return SearchQuery(
        query="best travel monitors",
        intent=SearchIntent.REVIEW,
        region_code="US",
        required_source_types=(SourceType.PROFESSIONAL_REVIEW,),
    )


def make_quality() -> SourceQuality:
    return SourceQuality(
        level=SourceQualityLevel.ADEQUATE,
        score=0.7,
        rationale="Fixture source with product-specific review context.",
    )


async def create_run(session_factory) -> tuple:
    async with session_factory() as db_session:
        shopping_session = await SessionRepository(db_session).create(
            original_input=CreateSessionRequest(query="Need a travel monitor"),
            current_brief=ShoppingBrief(original_query="Need a travel monitor"),
        )
        run = await RunRepository(db_session).create(shopping_session.session_id)
        await db_session.commit()
    return shopping_session, run


@pytest.mark.asyncio
async def test_search_source_repository_stores_snapshot_linked_to_run(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "sources.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        _shopping_session, run = await create_run(session_factory)
        provider = make_provider()
        query = make_query()
        plan = SearchPlan(
            queries=(query,),
            rationale="Find review and retailer evidence.",
        )
        result = SearchResult(
            query=query,
            url="https://example.com/reviews/travel-monitor",
            title="Best travel monitors",
            snippet="Review roundup.",
            source_type=SourceType.PROFESSIONAL_REVIEW,
            provider=provider,
            quality=make_quality(),
        )
        snapshot = SourceSnapshot(
            source_id=result.source_id,
            url=result.url,
            source_type=SourceType.PROFESSIONAL_REVIEW,
            provider=provider,
            title=result.title,
            extraction_status=ExtractionStatus.SUCCEEDED,
            quality=make_quality(),
        )

        async with session_factory() as db_session:
            repository = SearchSourceRepository(db_session)
            plan_id = await repository.create_search_plan(run.run_id, plan)
            stored_result = await repository.add_search_result(
                run.run_id,
                result,
                plan_id=plan_id,
            )
            stored_snapshot = await repository.add_source_snapshot(
                run.run_id,
                snapshot,
                search_result_id=stored_result.source_id,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            repository = SearchSourceRepository(db_session)
            loaded_plan = await repository.get_search_plan(plan_id)
            loaded_snapshot = await repository.get_source_snapshot(snapshot.source_id)
            run_snapshots = await repository.list_source_snapshots(run.run_id)
            run_results = await repository.list_search_results(run.run_id)

        assert loaded_plan is not None
        assert loaded_plan.queries[0].query == "best travel monitors"
        assert stored_snapshot.source_id == snapshot.source_id
        assert loaded_snapshot is not None
        assert loaded_snapshot.source_id == snapshot.source_id
        assert loaded_snapshot.provider.provider_name == "fixture-search"
        assert loaded_snapshot.provider.raw["provider_score"] == 0.92
        assert [item.source_id for item in run_snapshots] == [snapshot.source_id]
        assert [item.source_id for item in run_results] == [result.source_id]

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_search_source_repository_stores_source_evidence_for_run(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=tmp_path / "sources.sqlite3",
    )
    engine = create_database_engine(settings)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = create_session_factory(engine)
        _shopping_session, run = await create_run(session_factory)
        provider = make_provider()
        snapshot = SourceSnapshot(
            url="https://example.com/product/travel-monitor",
            source_type=SourceType.RETAILER_LISTING,
            provider=provider,
            title="Travel monitor listing",
            extraction_status=ExtractionStatus.PARTIAL,
            quality=make_quality(),
        )
        evidence = SourceEvidence(
            source_id=snapshot.source_id,
            target=EvidenceTarget(
                target_type=EvidenceTargetType.SOURCE_METADATA,
                source_id=snapshot.source_id,
            ),
            evidence_type=EvidenceType.AVAILABILITY,
            claim="The source lists the monitor as in stock.",
            confidence=Confidence(score=0.8, level=ConfidenceLevel.HIGH),
            source_quality=make_quality(),
        )

        async with session_factory() as db_session:
            repository = SearchSourceRepository(db_session)
            await repository.add_source_snapshot(run.run_id, snapshot)
            stored_evidence = await repository.add_source_evidence(
                run.run_id,
                evidence,
            )
            await db_session.commit()

        async with session_factory() as db_session:
            loaded_evidence = await SearchSourceRepository(
                db_session
            ).list_source_evidence(run.run_id)

        assert stored_evidence.source_id == snapshot.source_id
        assert len(loaded_evidence) == 1
        assert loaded_evidence[0].evidence_id == evidence.evidence_id
        assert loaded_evidence[0].claim == "The source lists the monitor as in stock."
        assert loaded_evidence[0].target.source_id == snapshot.source_id

    finally:
        await engine.dispose()
