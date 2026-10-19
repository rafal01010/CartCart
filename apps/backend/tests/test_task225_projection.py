from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import UUID

import httpx
import pytest

from app.core.settings import Settings
from app.db.base import Base
from app.db.models.results import ResultSourceProjectionRecord, ResultVersionRecord
from app.db.repositories.products import ProductRepository
from app.db.repositories.results import ResultRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory, get_db_session
from app.main import create_app
from app.schemas.analysis import ComparisonMatrix, RecommendationBundle
from app.schemas.decision_sources import DecisionSourcePacket, SourceDecisionProjection
from app.schemas.ids import new_id
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.products import CanonicalProduct
from app.schemas.runs import AgentRunRecord, RunStage, RunStatus
from app.schemas.search_sources import SearchResult, SourceEvidence, SourceSnapshot


ROOT = Path(__file__).resolve().parents[3]
PHONE_API = ROOT / "data/artifacts/task221/resume-20261017/phone-attempt4-result-api.json"
PHONE_CHECKPOINT = ROOT / (
    "data/artifacts/source-consultations/37da9a8b-1641-456c-94b4-bcd652c03346/"
    "3bcd0244df8066db5d02113f43ff0dbf6f224548a9eb09de0e4cd84e5c744cb0.json"
)


def source_rows(database_path: Path) -> dict[str, tuple[tuple, ...]]:
    with sqlite3.connect(database_path) as db:
        return {
            table: tuple(db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall())
            for table in ("search_results", "source_snapshots", "source_evidence")
        }


def caption_projection(phone: dict) -> SourceDecisionProjection:
    claims = tuple(SourceEvidence.model_validate(row) for row in phone["source_evidence"])
    source_id = claims[0].source_id
    snapshot = next(row for row in phone["source_snapshots"] if row["source_id"] == str(source_id))
    support = tuple(segment for claim in claims for segment in claim.transcript_support)
    text = "\n".join(claim.claim for claim in claims)
    archived_ids = {row["source_id"] for key in ("source_results", "source_snapshots") for row in phone[key]}
    return SourceDecisionProjection(
        projection_id="offline-phone-final-request",
        selected_source_ids=(source_id,),
        deferred_source_ids=tuple(UUID(item) for item in sorted(archived_ids - {str(source_id)})),
        candidate_coverage=({
            "candidate_name": "Apple iPhone 18 Pro Max",
            "source_ids": (source_id,),
            "buying_questions": ("What camera hardware changed?",),
            "support_kind": "accepted_speech",
        },),
        sources=(DecisionSourcePacket(
            source_id=source_id, url=snapshot["url"], title=snapshot["title"],
            content_kind="accepted_speech", excerpts=tuple(claim.claim for claim in claims),
            candidate_names=("Apple iPhone 18 Pro Max",),
            buying_questions=("What camera hardware changed?",),
            evidence_ids=tuple(claim.evidence_id for claim in claims),
            transcript_support=support,
            material_cautions=("These claims do not measure battery life.",),
            content_sha256=sha256(text.encode()).hexdigest(),
        ),),
        measurements={"raw_unique_sources": len(archived_ids), "selected_unique_sources": 1},
    )


@pytest.mark.asyncio
async def test_saved_phone_selection_freezes_exactly_and_legacy_api_stays_exact(tmp_path: Path) -> None:
    original_hashes = {path: sha256(path.read_bytes()).hexdigest() for path in (PHONE_API, PHONE_CHECKPOINT)}
    phone = json.loads(PHONE_API.read_text())
    settings = Settings(_env_file=None, database_path=tmp_path / "task225-projection.sqlite3")
    engine = create_database_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        run_id = UUID(phone["result_version"]["run_id"])
        legacy_version_id = UUID(phone["result_version"]["result_version_id"])
        async with factory() as db:
            brief = ShoppingBrief.model_validate(phone["shopping_brief"])
            shopping_session = await SessionRepository(db).create(
                original_input=CreateSessionRequest(query=brief.original_query), current_brief=brief,
            )
            await RunRepository(db).create(shopping_session.session_id, run_id=run_id)
            sources = SearchSourceRepository(db)
            for row in phone["source_results"]:
                await sources.add_search_result(run_id, SearchResult.model_validate(row))
            for row in phone["source_snapshots"]:
                await sources.add_source_snapshot(run_id, SourceSnapshot.model_validate(row))
            for row in phone["source_evidence"]:
                await sources.add_source_evidence(run_id, SourceEvidence.model_validate(row))
            for row in phone["products"]:
                await ProductRepository(db).add_canonical_product(run_id, CanonicalProduct.model_validate(row))
            results = ResultRepository(db)
            bundle = RecommendationBundle.model_validate(phone["recommendation_bundle"])
            matrix_id = UUID(phone["result_version"]["comparison_matrix_id"])
            await results.add_comparison_matrix(
                run_id, ComparisonMatrix.model_validate(phone["comparison_matrix"]), matrix_id=matrix_id,
            )
            await results.add_recommendation_bundle(run_id, bundle, comparison_matrix_id=matrix_id)
            db.add(ResultVersionRecord(
                result_version_id=str(legacy_version_id), run_id=str(run_id),
                version=phone["result_version"]["version"],
                recommendation_bundle_id=str(bundle.bundle_id), comparison_matrix_id=str(matrix_id),
                created_at="2026-10-17T00:00:00Z",
            ))
            await db.flush()
            legacy_payload = {
                key: phone[key] for key in (
                    "source_results", "source_snapshots", "source_evidence", "products", "listings",
                    "shortlist", "considered_products", "trust_assessments", "category_analyses", "agent_records",
                )
            }
            db.add(ResultSourceProjectionRecord(result_version_id=str(legacy_version_id), payload=legacy_payload))
            await RunRepository(db).append_event(
                run_id, stage=RunStage.COMPLETE, status=RunStatus.SUCCEEDED, message="Offline copied phone result.",
            )
            await db.commit()
        raw_before = source_rows(settings.database_path)
        assert {table: len(rows) for table, rows in raw_before.items()} == {
            "search_results": 16, "source_snapshots": 18, "source_evidence": 3,
        }
        app = create_app(settings)

        async def local_session():
            async with factory() as db:
                yield db

        app.dependency_overrides[get_db_session] = local_session
        prefix = f"/api/sessions/{shopping_session.session_id}/results"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
            legacy = await client.get(f"{prefix}/{legacy_version_id}")
            assert legacy.status_code == 200
            assert legacy.json() == phone
            assert "decision_sources" not in legacy.json()
            selection = caption_projection(phone)
            exact_selection = selection.model_dump(mode="json")
            async with factory() as db:
                saved = await ResultRepository(db).save_result_bundle(
                    run_id, trust_assessments=(), category_analyses=(),
                    agent_records=(AgentRunRecord(
                        run_id=run_id, agent_name="OfflineDecisionSourceOwner", stage=RunStage.GENERAL_OWNER,
                        status=RunStatus.SUCCEEDED, started_at="2026-10-17T12:00:00Z",
                        ended_at="2026-10-17T12:00:00Z",
                        tool_activity=(
                            {"tool_name": "decision_source_selection", "status": "transported", "output": {
                                "projection_id": "superseded-before-transport", "selected_source_ids": [],
                                "deferred_source_ids": [],
                            }},
                            {"tool_name": "decision_source_selection", "status": "transported", "output": exact_selection},
                            {"tool_name": "decision_source_selection", "status": "prepared", "output": {
                                "projection_id": "failed-before-transport", "selected_source_ids": [],
                                "deferred_source_ids": [],
                            }},
                        ),
                    ),),
                    recommendation_bundle=RecommendationBundle(
                        primary_product_ids=(UUID(phone["products"][0]["product_id"]),),
                        final_rationale="Offline exact projection control.",
                    ),
                )
                await db.commit()
            selected_path = f"{prefix}/{saved.result_version.result_version_id}"
            first = await client.get(selected_path)
            assert first.status_code == 200
            first_json = first.json()
            assert first_json["decision_sources"] == exact_selection
            assert first_json["decision_sources"]["selected_source_ids"] == ["ee69aaf2-48c2-4dd9-8b9d-275ee330c473"]
            assert first_json["source_evidence"] == phone["source_evidence"]
            assert len(first_json["source_results"]) == 16
            assert len(first_json["source_snapshots"]) == 18
            for key in ("source_results", "source_snapshots"):
                assert {row["source_id"]: row for row in first_json[key]} == {
                    row["source_id"]: row for row in phone[key]
                }
            assert source_rows(settings.database_path) == raw_before

            async with factory() as db:
                later_source = SearchResult.model_validate({
                    **phone["source_results"][0], "source_id": str(new_id()),
                    "url": "https://offline.example/new-alternative", "title": "Later offline alternative",
                })
                await SearchSourceRepository(db).add_search_result(run_id, later_source)
                later_selection = SourceDecisionProjection(
                    projection_id="later-offline-request", selected_source_ids=(later_source.source_id,),
                    deferred_source_ids=selection.selected_source_ids + selection.deferred_source_ids,
                )
                later = await ResultRepository(db).save_result_bundle(
                    run_id, trust_assessments=(), category_analyses=(),
                    agent_records=(AgentRunRecord(
                        run_id=run_id, agent_name="LaterOfflineDecisionOwner", stage=RunStage.GENERAL_OWNER,
                        status=RunStatus.SUCCEEDED, started_at="2026-10-17T13:00:00Z",
                        ended_at="2026-10-17T13:00:00Z",
                        tool_activity=(
                            {"tool_name": "decision_source_selection", "status": "transported", "output": later_selection.model_dump(mode="json")},
                            {"tool_name": "decision_source_selection", "status": "prepared", "output": {
                                "projection_id": "later-untransported", "selected_source_ids": [],
                                "deferred_source_ids": [],
                            }},
                        ),
                    ),),
                    recommendation_bundle=RecommendationBundle(
                        primary_product_ids=(UUID(phone["products"][1]["product_id"]),),
                        final_rationale="Later offline decision.",
                    ),
                )
                await db.commit()
            latest = await client.get(f"{prefix}/{later.result_version.result_version_id}")
            assert latest.status_code == 200
            assert latest.json()["decision_sources"] == later_selection.model_dump(mode="json")
            assert latest.json()["decision_sources"]["selected_source_ids"] == [str(later_source.source_id)]
            assert len(latest.json()["source_results"]) == 17
            assert (await client.get(selected_path)).json() == first_json
            assert (await client.get(f"{prefix}/{legacy_version_id}")).json() == phone
            async with factory() as db:
                legacy_record = await db.get(ResultSourceProjectionRecord, str(legacy_version_id))
                frozen_record = await db.get(ResultSourceProjectionRecord, str(saved.result_version.result_version_id))
                assert legacy_record.payload == legacy_payload
                assert frozen_record.payload["decision_sources"] == exact_selection
            raw_after = source_rows(settings.database_path)
            for table, rows in raw_before.items():
                assert set(rows) <= set(raw_after[table])
        assert {path: sha256(path.read_bytes()).hexdigest() for path in original_hashes} == original_hashes
    finally:
        await engine.dispose()
