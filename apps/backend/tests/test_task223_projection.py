"""Local projection controls. This text is not live caption evidence."""

import asyncio
from hashlib import sha256
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.models.results import ResultSourceProjectionRecord, ResultVersionRecord
from app.db.session import create_database_engine, create_session_factory, get_db_session
from app.main import create_app
from app.schemas.analysis import RecommendationBundle
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.products import CanonicalProduct, ProductListing, UserAddedProduct
from app.schemas.runs import AgentRunRecord, RunStage, RunStatus
from app.schemas.search_sources import SourceEvidence, SourceSnapshot, VideoTranscriptSupport


def local_evidence() -> SourceEvidence:
    source_id, segment_id = new_id(), new_id()
    text = "Local projection control speech. The smaller stand leaves more desk space."
    return SourceEvidence(
        source_id=source_id,
        target={"target_type": "source_metadata", "source_id": source_id},
        evidence_type="video_claim",
        claim="The smaller stand leaves more desk space.",
        confidence={"level": "medium", "score": 0.6},
        source_quality={"level": "unknown"},
        video={
            "video_id": "local-control",
            "url": "https://www.youtube.com/watch?v=local-control",
            "title": "Local projection control review",
            "channel_name": "Local control creator",
            "transcript_availability": "available",
        },
        timestamp_references=({"start_seconds": 75, "end_seconds": 91},),
        transcript_segment_ids=(segment_id,),
        transcript_support=(VideoTranscriptSupport(
            segment_id=segment_id,
            video_id="local-control",
            start_seconds=75,
            end_seconds=91,
            text=text,
            content_sha256=sha256(text.encode()).hexdigest(),
        ),),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("primary_count", "runner_count"), [(1, 0), (2, 0), (3, 2), (0, 0)])
async def test_local_sqlite_api_keeps_caption_proof_and_literal_authored_groups(
    tmp_path: Path, primary_count: int, runner_count: int,
) -> None:
    settings = Settings(_env_file=None, database_path=tmp_path / "projection.sqlite3")
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        evidence = local_evidence()
        assert evidence.video is not None
        async with factory() as db:
            shopping_session = await SessionRepository(db).create(
                original_input=CreateSessionRequest(query="Local projection control"),
                current_brief=ShoppingBrief(original_query="Local projection control"),
            )
            run = await RunRepository(db).create(shopping_session.session_id)
            products = tuple(CanonicalProduct(name=f"Local choice {i}") for i in range(5))
            for product in products:
                await ProductRepository(db).add_canonical_product(run.run_id, product)
            await ProductRepository(db).add_shortlist_membership(
                run.run_id, product_id=products[0].product_id, position=1,
            )
            await ProductRepository(db).add_user_added_product(
                shopping_session.session_id, UserAddedProduct(input_text="Local considered choice"),
                run_id=run.run_id,
            )
            sources = SearchSourceRepository(db)
            await sources.add_source_snapshot(run.run_id, SourceSnapshot(
                source_id=evidence.source_id, url=evidence.video.url,
                source_type="video", title=evidence.video.title,
                provider={"provider_name": "local-projection-control"},
                extraction_status="succeeded", video=evidence.video,
            ))
            await sources.add_source_evidence(run.run_id, evidence)
            primary = tuple(p.product_id for p in products[:primary_count])
            runners = tuple(p.product_id for p in products[3:3 + runner_count])
            bundle = RecommendationBundle(
                primary_product_ids=primary, runner_up_product_ids=runners,
                no_strong_buy=not primary,
                no_strong_buy_reason="Local control has no suitable choice." if not primary else None,
                final_rationale="Local control advice.",
                source_ids=(evidence.source_id,), evidence_ids=(evidence.evidence_id,),
            )
            saved = await ResultRepository(db).save_result_bundle(
                run.run_id, trust_assessments=(), category_analyses=(), agent_records=(),
                recommendation_bundle=bundle,
            )
            await RunRepository(db).append_event(
                run.run_id, stage=RunStage.COMPLETE, status=RunStatus.SUCCEEDED,
                message="Local projection control completed.",
            )
            await db.commit()
        app = create_app(settings)

        async def local_db_session():
            async with factory() as db:
                yield db

        app.dependency_overrides[get_db_session] = local_db_session
        path = f"/api/sessions/{shopping_session.session_id}/results/{saved.result_version.result_version_id}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local-control") as client:
            response = await client.get(path)
            assert response.status_code == 200
            first = response.json()
            assert first["source_evidence"] == [evidence.model_dump(mode="json")]
            assert first["source_snapshots"][0]["video"]["channel_name"] == "Local control creator"
            assert first["recommendation_bundle"]["primary_product_ids"] == [str(item) for item in primary]
            assert first["recommendation_bundle"]["runner_up_product_ids"] == [str(item) for item in runners]
            async with factory() as db:
                later_evidence = local_evidence()
                assert later_evidence.video is not None
                await SearchSourceRepository(db).add_source_snapshot(run.run_id, SourceSnapshot(
                    source_id=later_evidence.source_id, url=later_evidence.video.url,
                    source_type="video", title="Later local caption source",
                    provider={"provider_name": "local-projection-control"},
                    extraction_status="succeeded", video=later_evidence.video,
                ))
                await SearchSourceRepository(db).add_source_evidence(run.run_id, later_evidence)
                later_product = CanonicalProduct(name="Later local candidate")
                await ProductRepository(db).add_canonical_product(run.run_id, later_product)
                await ProductRepository(db).add_product_listing(run.run_id, ProductListing(
                    product_id=later_product.product_id, title="Later local listing",
                    url="https://example.test/local-listing", seller={"seller_name": "Local control seller"},
                    source_ids=(later_evidence.source_id,),
                ))
                await ProductRepository(db).add_shortlist_membership(
                    run.run_id, product_id=later_product.product_id, position=2,
                )
                await ProductRepository(db).add_user_added_product(
                    shopping_session.session_id, UserAddedProduct(input_text="Later local considered choice"),
                    run_id=run.run_id,
                )
                await ResultRepository(db).add_agent_record(AgentRunRecord(
                    run_id=run.run_id, stage=RunStage.SOURCE_INTELLIGENCE,
                    agent_name="LocalCaptionProjectionControl", status=RunStatus.SUCCEEDED,
                    started_at="2026-10-16T00:00:00Z",
                ))
                later = await ResultRepository(db).save_result_bundle(
                    run.run_id, trust_assessments=(), category_analyses=(), agent_records=(),
                    recommendation_bundle=RecommendationBundle(
                        primary_product_ids=(products[4].product_id,),
                        final_rationale="A later local control choice.",
                    ),
                )
                await db.commit()
            assert (await client.get(path)).json() == first
            later_path = f"/api/sessions/{shopping_session.session_id}/results/{later.result_version.result_version_id}"
            latest = (await client.get(later_path)).json()
            assert len(latest["source_evidence"]) == 2
            assert later_evidence.model_dump(mode="json") in latest["source_evidence"]
            assert latest["source_evidence"] != first["source_evidence"]
            assert {p["name"] for p in latest["products"]} - {p["name"] for p in first["products"]} == {"Later local candidate"}
            assert len(first["listings"]) == 0 and len(latest["listings"]) == 1
            assert len(first["shortlist"]) == 1 and len(latest["shortlist"]) == 2
            assert len(first["considered_products"]) == 1 and len(latest["considered_products"]) == 2
            assert first["agent_records"] == []
            assert latest["agent_records"][0]["agent_name"] == "LocalCaptionProjectionControl"
            async with factory() as db:
                projection = await db.get(ResultSourceProjectionRecord, str(saved.result_version.result_version_id))
                assert projection is not None
                assert projection.payload["source_evidence"] == first["source_evidence"]
                assert projection.payload["source_evidence"][0]["transcript_support"][0]["text"].startswith("Local projection control speech.")
    finally:
        await engine.dispose()


@pytest.mark.parametrize("change", ["hash", "video", "segment", "metadata"])
def test_local_caption_proof_rejects_mismatched_provenance(change: str) -> None:
    data = local_evidence().model_dump(mode="json")
    if change == "hash":
        data["transcript_support"][0]["content_sha256"] = "0" * 64
    elif change == "video":
        data["transcript_support"][0]["video_id"] = "other-video"
    elif change == "segment":
        data["transcript_segment_ids"] = [str(new_id())]
    else:
        data["metadata_only"] = True
    with pytest.raises(ValidationError):
        SourceEvidence.model_validate(data)


def test_local_legacy_metadata_does_not_acquire_caption_proof() -> None:
    data = local_evidence().model_dump(mode="json")
    for key in ("transcript_support", "transcript_segment_ids", "metadata_only"):
        data.pop(key)
    loaded = SourceEvidence.model_validate(data)
    assert loaded.claim == "The smaller stand leaves more desk space."
    assert loaded.transcript_support == ()
    assert loaded.transcript_segment_ids == ()


@pytest.mark.asyncio
async def test_local_legacy_reload_is_read_only_and_explicit_retry_freezes_once(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, database_path=tmp_path / "legacy-projection.sqlite3")
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as db:
            shopping_session = await SessionRepository(db).create(
                original_input=CreateSessionRequest(query="Local legacy control"),
                current_brief=ShoppingBrief(original_query="Local legacy control"),
            )
            run = await RunRepository(db).create(shopping_session.session_id)
            evidence = local_evidence()
            assert evidence.video is not None
            await SearchSourceRepository(db).add_source_snapshot(run.run_id, SourceSnapshot(
                source_id=evidence.source_id, url=evidence.video.url, source_type="video",
                provider={"provider_name": "local-legacy-control"},
                extraction_status="succeeded", video=evidence.video,
            ))
            await SearchSourceRepository(db).add_source_evidence(run.run_id, evidence)
            bundle = RecommendationBundle(
                no_strong_buy=True, no_strong_buy_reason="Local legacy advice.",
            )
            results = ResultRepository(db)
            matrix_id = await results.add_comparison_matrix(run.run_id, bundle.comparison_matrix)
            await results.add_recommendation_bundle(run.run_id, bundle, comparison_matrix_id=matrix_id)
            version_id = new_id()
            db.add(ResultVersionRecord(
                result_version_id=str(version_id), run_id=str(run.run_id), version=1,
                recommendation_bundle_id=str(bundle.bundle_id), comparison_matrix_id=str(matrix_id),
                created_at="2026-10-16T00:00:00Z",
            ))
            second_version_id = new_id()
            db.add(ResultVersionRecord(
                result_version_id=str(second_version_id), run_id=str(run.run_id), version=2,
                recommendation_bundle_id=str(bundle.bundle_id), comparison_matrix_id=str(matrix_id),
                created_at="2026-10-16T00:00:01Z",
            ))
            await RunRepository(db).append_event(
                run.run_id, stage=RunStage.COMPLETE, status=RunStatus.SUCCEEDED,
                message="Local legacy control completed.",
            )
            await db.commit()
        app = create_app(settings)

        async def local_db_session():
            async with factory() as db:
                yield db

        app.dependency_overrides[get_db_session] = local_db_session
        path = f"/api/sessions/{shopping_session.session_id}/results/{version_id}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local-control") as client:
            for _ in range(2):
                response = await client.get(path)
                assert response.status_code == 200
                assert response.json()["source_evidence"] == [evidence.model_dump(mode="json")]
            before_retry = response.json()
            async with factory() as db:
                assert await db.scalar(select(func.count()).select_from(ResultSourceProjectionRecord)) == 0
                loaded = await ResultRepository(db).load_result_bundle_by_version(version_id)
                assert loaded is not None
                assert loaded.source_projection is None
                frozen = await ResultRepository(db).freeze_legacy_projection(version_id)
                assert frozen.source_evidence == (evidence,)
                await RunRepository(db).append_event(
                    run.run_id, stage=RunStage.SOURCE_INTELLIGENCE, status=RunStatus.RUNNING,
                    message="Local explicit retry claimed the run.",
                )
                await ResultRepository(db).freeze_run_projections(run.run_id)
                second = await db.get(ResultSourceProjectionRecord, str(second_version_id))
                assert second is not None
                assert second.payload == frozen.model_dump(mode="json", exclude_computed_fields=True)
                await RunRepository(db).append_event(
                    run.run_id, stage=RunStage.COMPLETE, status=RunStatus.SUCCEEDED,
                    message="Local explicit retry control completed.",
                )
                await db.commit()
            async with factory() as db:
                later_evidence = local_evidence()
                assert later_evidence.video is not None
                await SearchSourceRepository(db).add_source_snapshot(run.run_id, SourceSnapshot(
                    source_id=later_evidence.source_id, url=later_evidence.video.url, source_type="video",
                    provider={"provider_name": "local-retry-control"},
                    extraction_status="succeeded", video=later_evidence.video,
                ))
                await SearchSourceRepository(db).add_source_evidence(run.run_id, later_evidence)
                await ProductRepository(db).add_canonical_product(run.run_id, CanonicalProduct(name="Local retry candidate"))
                frozen_again = await ResultRepository(db).freeze_legacy_projection(version_id)
                await ResultRepository(db).freeze_run_projections(run.run_id)
                assert frozen_again == frozen
                assert await db.scalar(select(func.count()).select_from(ResultSourceProjectionRecord)) == 2
                await db.commit()
            assert (await client.get(path)).json() == before_retry
    finally:
        await engine.dispose()


def test_local_projection_migration_preserves_existing_sources(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "migration.sqlite3"
    monkeypatch.setenv("CARTCART_DATABASE_PATH", str(database_path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "0004")

    async def seed_local_source() -> None:
        settings = Settings(_env_file=None, database_path=database_path)
        engine = create_database_engine(settings)
        try:
            factory = create_session_factory(engine)
            async with factory() as db:
                shopping_session = await SessionRepository(db).create(
                    original_input=CreateSessionRequest(query="Local migration control"),
                    current_brief=ShoppingBrief(original_query="Local migration control"),
                )
                run = await RunRepository(db).create(shopping_session.session_id)
                evidence = local_evidence()
                assert evidence.video is not None
                await SearchSourceRepository(db).add_source_snapshot(run.run_id, SourceSnapshot(
                    source_id=evidence.source_id, url=evidence.video.url, source_type="video",
                    provider={"provider_name": "local-migration-control"},
                    extraction_status="succeeded", video=evidence.video,
                ))
                await SearchSourceRepository(db).add_source_evidence(run.run_id, evidence)
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed_local_source())
    with sqlite3.connect(database_path) as db:
        before = db.execute("SELECT * FROM source_evidence").fetchall()
        assert len(before) == 1
    command.upgrade(config, "0005")
    with sqlite3.connect(database_path) as db:
        assert db.execute("SELECT * FROM source_evidence").fetchall() == before
        assert db.execute("SELECT count(*) FROM result_source_projections").fetchone() == (0,)
        assert db.execute("PRAGMA foreign_key_list(result_source_projections)").fetchone()[2:5] == (
            "result_versions", "result_version_id", "result_version_id",
        )
