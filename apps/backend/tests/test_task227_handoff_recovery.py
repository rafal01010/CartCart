import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.context_management import ContextBudget, context_scope
from app.db.base import Base
from app.db.session import create_session_factory
from test_context_decision_fidelity import _owner, _seed
from test_task224_finalization import (
    LocalOwnerRunner,
    SavedSpeechSource,
    LocalResponsesProvider,
    persist_groups_and_read_api,
    response_payload,
)


CONTROL = json.loads(
    (
        Path(__file__).parent / "fixtures/providers/task227_handoff_recovery.json"
    ).read_text()
)
QUERY = CONTROL["original_query"]
REASON = CONTROL["synthetic_descriptive_reason"]


@pytest.mark.parametrize(
    "excerpts", [("Repeated navigation.",), ()], ids=["repeated-excerpts", "notes-only"]
)
def test_source_selection_keeps_distinct_notes_with_repeated_page_excerpts(excerpts):
    from app.agents.decision_sources import select_decision_sources
    from app.schemas.decision_sources import DecisionSourcePacket
    from app.schemas.ids import new_id
    from app.schemas.intake import ShoppingBrief

    def packet(url, note):
        return DecisionSourcePacket(
            source_id=new_id(),
            url=url,
            title="Phone research",
            content_kind="page",
            excerpts=excerpts,
            source_notes=(note,),
            content_sha256="a" * 64,
        )

    first = packet("https://example.org/a", "Phone A lasts a full day.")
    distinct = packet("https://example.org/b", "Phone B has no local warranty.")
    duplicate = packet("https://example.org/c", "Phone A lasts a full day.")
    result = select_decision_sources(
        ShoppingBrief(original_query="Find a phone"), (first, distinct, duplicate)
    )
    assert [note for source in result.sources for note in source.source_notes] == [
        "Phone A lasts a full day.",
        "Phone B has no local warranty.",
    ]
    assert result.deferred_source_ids == (duplicate.source_id,)


def call(name, arguments, call_id):
    result = response_payload(None, output_tokens=20)
    result["output"] = [
        {
            "id": "fc_" + call_id,
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": json.dumps(arguments),
        }
    ]
    return result


def transfer(target):
    def respond(request):
        tool = next(
            tool
            for tool in request["tools"]
            if tool.get("type") == "function"
            and tool["name"].replace("_", "").endswith(target.lower())
        )
        properties = tool["parameters"]["properties"]
        assert set(properties) == {"reason"}
        arguments = {"reason": REASON}
        return call(tool["name"], arguments, target)

    return respond


async def setup_owner():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    shopping_session, run, brief, sources, _, quotes = await _seed(factory, phone=True)
    brief = brief.model_copy(update={"original_query": QUERY, "category": "phone"})
    owner, request, _ = _owner(factory, run, brief, sources, quotes, phone=True)
    return (
        engine,
        factory,
        shopping_session,
        run,
        brief,
        sources,
        quotes,
        owner,
        request,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "misuse", ["specialist-before-parent", "repeat-parent", "repeat-specialist"]
)
async def test_sdk_handoff_callbacks_reject_hierarchy_misuse(misuse):
    from agents import RunContextWrapper
    from agents.exceptions import UserError

    engine, _, _, _, _, _, _, owner, request = await setup_owner()
    checked = []

    class BoundaryRunner:
        async def run(self, agent, model_input, **kwargs):
            parent = agent.handoffs[0]
            technology = parent._agent_ref()
            specialist = next(
                item
                for item in technology.handoffs
                if item.agent_name == "SmartphoneSpecialistAgent"
            )
            context = RunContextWrapper(context=None)
            arguments = json.dumps({"reason": REASON})
            if misuse != "specialist-before-parent":
                assert (
                    await parent.on_invoke_handoff(context, arguments)
                ).name == "TechnologyDomainAnalystAgent"
            if misuse == "repeat-parent":
                with pytest.raises(UserError, match="depth one"):
                    await parent.on_invoke_handoff(context, arguments)
            else:
                if misuse == "repeat-specialist":
                    assert (
                        await specialist.on_invoke_handoff(context, arguments)
                    ).name == "SmartphoneSpecialistAgent"
                with pytest.raises(UserError, match="declared hierarchy"):
                    await specialist.on_invoke_handoff(context, arguments)
            checked.append(misuse)
            raise RuntimeError("Synthetic stop after SDK boundary checks.")

    owner.model_runner = BoundaryRunner()
    try:
        draft = await owner.run(request)
        assert checked == [misuse]
        assert draft.outcome.value == "insufficient_evidence"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_actual_sdk_budget_failure_after_specialist_handoff_never_recovers():
    from app.agents.context_management import ContextBudgetExceeded

    engine, _, _, _, _, _, _, owner, request = await setup_owner()
    provider = LocalResponsesProvider(
        transfer("TechnologyDomainAnalystAgent"),
        transfer("SmartphoneSpecialistAgent"),
        ContextBudgetExceeded("Synthetic exhausted context boundary."),
    )
    owner.model_runner = LocalOwnerRunner(provider)
    budget = ContextBudget()
    try:
        with context_scope(budget):
            draft = await owner.run(request)
        assert draft.outcome.value == "insufficient_evidence"
        activity = next(
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "general_owner"
        )
        assert activity["output"]["failure_code"] == "context_budget_exceeded"
        assert not any(
            item["tool_name"] == "owner_recovery" for item in owner.workbench_activity
        )
        assert len(provider.calls) == 3
        assert budget.reserved == 0
    finally:
        await provider.client.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_actual_sdk_reason_only_handoffs_keep_buyer_category_and_choices():
    (
        engine,
        factory,
        shopping_session,
        run,
        brief,
        sources,
        quotes,
        owner,
        request,
    ) = await setup_owner()
    authored = {
        "category": "phone",
        "rationale": "Aster Pro offers all-day battery life with weaker low-light photos.",
        "candidates": [
            {
                "name": "Aster Pro 512GB PH",
                "choice_group": "primary",
                "rationale": "Its battery lasts a full day.",
                "tradeoff": "Low-light photos are weaker.",
            }
        ],
        "selected_candidate_name": "Aster Pro 512GB PH",
    }
    provider = LocalResponsesProvider(
        transfer("TechnologyDomainAnalystAgent"),
        transfer("SmartphoneSpecialistAgent"),
        response_payload(json.dumps(authored), output_tokens=200),
    )
    owner.model_runner = LocalOwnerRunner(provider)
    budget = ContextBudget()
    try:
        with context_scope(budget):
            draft = await owner.run(request)
        assert draft.selected_candidate_name == "Aster Pro 512GB PH", (
            owner.workbench_activity
        )
        assert draft.owner_agent_name == "SmartphoneSpecialistAgent"
        edges = [
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "sdk_handoff"
        ]
        assert [(item["output"]["target_agent"], item["status"]) for item in edges] == [
            ("TechnologyDomainAnalystAgent", "completed"),
            ("SmartphoneSpecialistAgent", "completed"),
        ]
        assert edges[0]["input"]["technology_category"] == "phone"
        assert edges[1]["input"]["product_category"] == "phone"
        assert edges[1]["input"]["reason"] == REASON
        await persist_groups_and_read_api(
            factory, shopping_session, run, brief, owner, draft, authored
        )
    finally:
        await provider.client.close()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "success", [True, False], ids=["retained-decision", "charged-failure"]
)
@pytest.mark.parametrize(
    "annotated", [False, True], ids=["unannotated-notes", "candidate-coverage"]
)
async def test_actual_sdk_recovery_closes_tools_and_retains_research_in_saved_api(
    success, annotated
):
    (
        engine,
        factory,
        shopping_session,
        run,
        brief,
        sources,
        quotes,
        owner,
        request,
    ) = await setup_owner()
    authored = json.loads(json.dumps(CONTROL["synthetic_authored_decision"]))
    authored["candidates"][0]["source_ids"] = [str(sources[1].source_id)]
    from app.schemas.search_sources import (
        CommunityDiscussionEvidenceBundle,
        VideoReviewEvidenceBundle,
    )
    from app.agents.live_source_intelligence_manager import SourceManagerResult
    from app.agents.source_consultation import SourceConsultationOutcome
    from app.db.repositories.search_sources import SearchSourceRepository
    from app.schemas.ids import new_id

    community = CommunityDiscussionEvidenceBundle.model_validate(
        CONTROL["synthetic_community_bundle"]
    )
    community_claim = community.evidence[0].claim
    community_warning = community.evidence[0].evidence_quality_warnings[0]
    community_lead = sources[0].model_copy(
        update={
            "source_id": new_id(),
            "url": community.source_references[0].url,
            "title": "Synthetic community phone research",
            "snippet": "Phone discussion metadata only.",
        }
    )
    async with factory() as session:
        await SearchSourceRepository(session).add_search_result(
            run.run_id, community_lead
        )
        await session.commit()

    saved = json.loads(
        (
            Path(__file__).parent
            / "fixtures/providers/task225_saved_caption_checkpoint.json"
        ).read_text()
    )
    bundle = VideoReviewEvidenceBundle.model_validate(
        saved["validated_bundles"]["video_review"]
    )
    segment_ids = {
        identifier
        for evidence in bundle.evidence
        for identifier in evidence.transcript_segment_ids
    }
    speech = [
        segment.model_dump(mode="json")
        for segment in bundle.transcript_segments
        if segment.segment_id in segment_ids
    ]

    class MixedSourceManager(SavedSpeechSource):
        async def run(self, supplied):
            if supplied.allowed_capabilities[0].value == "community_discussion":
                self.calls += 1
                return SourceManagerResult(
                    outcome=SourceConsultationOutcome(status="succeeded"),
                    community_bundles=(community,),
                )
            return await super().run(supplied)

    source_manager = MixedSourceManager(bundle)
    owner.source_intelligence_manager = source_manager
    speech_source_ids = {
        str(item.source_id) for item in bundle.evidence if not item.metadata_only
    }
    expected_selected_ids = (
        {str(source.source_id) for source in sources}
        | speech_source_ids
        | {str(community_lead.source_id)}
    )
    steps = [transfer("TechnologyDomainAnalystAgent")]
    for index, (source, quote) in enumerate(zip(sources, quotes, strict=True)):
        quote_arguments = {"source_id": str(source.source_id), "quote": quote}
        if annotated:
            quote_arguments.update(
                candidate_names=[
                    "Aster Pro imported 256GB" if index == 2 else "Aster Pro 512GB PH"
                ],
                buying_question=("warranty", "battery and camera", "regional variant")[
                    index
                ],
                finding=quote,
            )
        steps.extend(
            [
                call(
                    "fetch_source",
                    {"source_id": str(source.source_id), "focus": quote[:80]},
                    f"fetch{index}",
                ),
                call("record_source_quote", quote_arguments, f"quote{index}"),
            ]
        )
    steps.append(
        call(
            "consult_source_intelligence",
            {
                "capability": "community_discussion",
                "product_name": "Aster Pro 512GB PH",
            },
            "community",
        )
    )
    steps.append(
        call(
            "consult_source_intelligence",
            {"capability": "video_review", "product_name": "Aster Pro 512GB PH"},
            "speech",
        )
    )
    steps.extend(
        [
            transfer("SmartphoneSpecialistAgent"),
            RuntimeError(
                "Synthetic specialist transport failure after retained source research."
            ),
        ]
    )

    recovery_checks = []
    retained_evidence = []

    def recover(request):
        serialized = json.dumps(request["input"])
        useful = (
            QUERY in serialized
            and all(quote in serialized for quote in quotes)
            and all(segment["text"] in serialized for segment in speech)
            and community_claim in serialized
            and community_warning in serialized
        )
        recovery_checks.append(
            {
                "tools": request["tools"],
                "missing": [quote for quote in quotes if quote not in serialized],
                "query": QUERY in serialized,
            }
        )
        if request["tools"] or not useful:
            return call(
                "search_sources",
                {"query": "Synthetic unnecessary research restart"},
                "restart",
            )
        assert request["max_output_tokens"] == 2400
        if not success:
            raise RuntimeError("Synthetic recovery transport failure.")

        def objects(value):
            if isinstance(value, str):
                try:
                    yield from objects(json.loads(value))
                except ValueError:
                    return
            elif isinstance(value, dict):
                yield value
                for child in value.values():
                    yield from objects(child)
            elif isinstance(value, list):
                for child in value:
                    yield from objects(child)

        projection = next(
            item for item in objects(request["input"]) if "selected_source_ids" in item
        )
        assert set(projection["selected_source_ids"]) == expected_selected_ids
        for packet in projection["sources"]:
            retained_evidence.extend(packet["evidence"])
        assert set(CONTROL["retained_quotes"]) <= {
            item["claim"] for item in retained_evidence
        }
        packets = [
            item
            for item in objects(request["input"])
            if item.get("content_kind") == "accepted_speech"
        ]
        assert len(packets) == 1
        spans = packets[0]["transcript_support"]
        for expected in speech:
            span = next(
                item for item in spans if item["segment_id"] == expected["segment_id"]
            )
            for key in (
                "text",
                "video_id",
                "segment_id",
                "start_seconds",
                "end_seconds",
            ):
                assert span[key] == expected[key]
        community_packets = [
            packet
            for packet in projection["sources"]
            if packet["url"] == str(community_lead.url)
        ]
        assert len(community_packets) == 1
        assert community_packets[0]["material_cautions"].count(community_warning) == 1
        details = next(
            json.loads(note)
            for note in community_packets[0]["source_notes"]
            if note.startswith('{"context_source_ids"')
        )
        assert details["context_source_ids"] == [
            str(community.source_references[0].source_id)
        ]
        context_note = next(
            json.loads(note)
            for note in community_packets[0]["source_notes"]
            if note.startswith('{"comment_count"')
        )
        assert context_note == community.discussions[0].model_dump(
            mode="json", exclude_none=True
        )
        assert context_note["community_name"] == "phones"
        assert context_note["posted_at"] == "2026-10-01T00:00:00Z"
        assert context_note["engagement_score"] == 2
        assert context_note["comment_count"] == 3
        assert details["qualitative_signal"] is True
        assert details["recurring_signal"] is False
        assert details["supporting_quotes"] == [
            {
                "source_id": str(community.source_references[0].source_id),
                "quote": community.discussions[0].extracted_public_summary,
            }
        ]
        assert [
            evidence["evidence_id"] for evidence in community_packets[0]["evidence"]
        ] == [str(community.evidence[0].evidence_id)]
        assert not any(
            "bundles" in item or "validated_bundles" in item
            for item in objects(request["input"])
        )
        authored["candidates"][0]["evidence_ids"] = [
            item["evidence_id"]
            for item in retained_evidence
            if item["claim"] in CONTROL["retained_quotes"]
        ]
        return response_payload(json.dumps(authored), output_tokens=300)

    provider = LocalResponsesProvider(*steps, recover, recover)
    owner.model_runner = LocalOwnerRunner(provider)
    budget = ContextBudget(spent=600)
    try:
        with context_scope(budget):
            draft = await owner.run(request)
        recovery = next(
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "owner_recovery"
        )
        assert recovery["status"] == ("completed" if success else "failed"), (
            recovery,
            recovery_checks,
        )
        assert provider.calls[-1]["tools"] == []
        assert provider.calls[-1]["max_output_tokens"] == 2400
        assert len(provider.calls) == 12
        assert source_manager.calls == 2
        assert all(snapshot[0] is budget for snapshot in provider.ledger_snapshots)
        owner_ledgers = [snapshot[1][-1] for snapshot in provider.ledger_snapshots]
        assert all(ledger is owner_ledgers[0] for ledger in owner_ledgers)
        calls = [
            event for event in budget.events if event["tool_name"] == "context_call"
        ]
        paid = [
            event["output"]["actual_total_tokens"]
            for event in calls
            if event["output"].get("actual_total_tokens") is not None
        ]
        failed = [
            event["output"]["charged_tokens"]
            for event in calls
            if event["output"].get("actual_total_tokens") is None
            and event["output"].get("charged_tokens") is not None
        ]
        assert paid == [120] * 10 + ([400] if success else [])
        assert len(failed) == (1 if success else 2)
        assert all(charge > 0 for charge in failed)
        assert budget.spent == 600 + 1200 + (400 if success else 0) + sum(failed)
        assert budget.reserved == owner_ledgers[0].reserved == 0
        activity = next(
            item
            for item in owner.workbench_activity
            if item["tool_name"] == "general_owner"
        )
        assert activity["output"]["accounted_owner_tokens"] == budget.spent - 600
        assert (
            len(
                [
                    item
                    for item in owner.workbench_activity
                    if item["tool_name"] == "fetch_source"
                ]
            )
            == 3
        )
        assert not any(
            item["tool_name"] == "search_sources" for item in owner.workbench_activity
        )
        if success:
            assert draft.owner_agent_name == "TechnologyDomainAnalystAgent"
            assert draft.rationale == authored["rationale"]
            assert [(item.name, item.choice_group) for item in draft.candidates] == [
                ("Aster Pro 512GB PH", "primary"),
                ("Birch Value Phone", "primary"),
                ("Cedar Compact Phone", "runner_up"),
            ]
            assert {
                str(item.evidence_id)
                for item in draft.candidates[0].evidence
                if item.evidence_id
            } == {
                item["evidence_id"]
                for item in retained_evidence
                if item["claim"] in CONTROL["retained_quotes"]
            }
            assert {
                item.quote for item in draft.candidates[0].evidence if item.quote
            } >= set(CONTROL["retained_quotes"])
            assert sources[1].source_id in {
                item.source_id for item in draft.candidates[0].evidence
            }
            api = await persist_groups_and_read_api(
                factory, shopping_session, run, brief, owner, draft, authored
            )
            selection = [
                item["output"]
                for item in owner.workbench_activity
                if item["tool_name"] == "decision_source_selection"
                and item["status"] == "transported"
            ][-1]
            assert api.decision_sources.model_dump(mode="json") == selection
            assert set(selection["selected_source_ids"]) == expected_selected_ids
            assert selection["deferred_source_ids"] == []
            saved_claims = {
                claim.claim
                for packet in api.decision_sources.sources
                for claim in packet.evidence
            }
            assert saved_claims >= set(CONTROL["retained_quotes"])
            saved_spans = [
                span
                for packet in api.decision_sources.sources
                for span in packet.transcript_support
            ]
            assert {span.text for span in saved_spans} == {
                segment["text"] for segment in speech
            }
            assert any(
                "no local warranty" in caution
                for packet in api.decision_sources.sources
                for caution in packet.material_cautions
            )
        else:
            assert draft.outcome.value == "insufficient_evidence"
    finally:
        await provider.client.close()
        await engine.dispose()
