import json

from app.agents.decision_sources import project_owner_sources
from app.agents.research_history import active_history, history_scope
from app.schemas.ids import new_id
from test_live_verifier_critic_agent import _verification_input


def test_projected_source_receipts_preserve_scoped_original_and_deferred_lookup_across_turns():
    source_id, deferred_id, batch_id = (str(new_id()) for _ in range(3))
    payload = {
        "status": "succeeded",
        "sources": [{"source_id": source_id, "url": "https://example.com/monitor", "title": "Desk monitor", "snippet": "A desk monitor with clear text."}],
        "search_result_id": batch_id,
        "deferred_source_ids": [deferred_id],
        "next_offset": 4,
    }
    original = [
        {"role": "user", "content": json.dumps({"brief": _verification_input().brief.model_dump(mode="json")})},
        {"type": "function_call", "name": "search_sources", "call_id": "search-one", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "search-one", "output": json.dumps(payload)},
    ]
    with history_scope(fresh=True):
        first, _ = project_owner_sources(original)
        initial_receipt = json.loads(first[2]["output"])
        for _ in range(3):
            first, _ = project_owner_sources(first)
            receipt = json.loads(first[2]["output"])
            assert receipt["archive_view_id"] == initial_receipt["archive_view_id"]
            assert receipt["search_result_id"] == batch_id
            assert receipt["deferred_source_ids"] == [deferred_id]
            assert receipt["next_offset"] == 4
            assert receipt["reload_tool"] == "read_research_result"
            history = active_history()
            assert history is not None
            reread = history.read(receipt["archive_view_id"])
            assert json.loads(reread["text"]) == payload
        forged = {**receipt, "deferred_source_ids": [str(new_id())]}
        changed = [{**item} for item in first]
        changed[2] = {**changed[2], "output": json.dumps(forged)}
        projected, _ = project_owner_sources(changed)
        rejected_identity = json.loads(projected[2]["output"])
        assert rejected_identity["archive_view_id"] != initial_receipt["archive_view_id"]
        assert history.views[initial_receipt["archive_view_id"]].payload == payload
    with history_scope(fresh=True):
        projected, _ = project_owner_sources(first)
        foreign_receipt = json.loads(projected[2]["output"])
        assert foreign_receipt["archive_view_id"] != initial_receipt["archive_view_id"]


def test_nonvideo_source_note_ids_keep_their_original_source_associations():
    source_ids = [str(new_id()) for _ in range(3)]
    snapshot_ids = [str(new_id()) for _ in range(3)]
    evidence_ids = [str(new_id()) for _ in range(3)]
    notes = ["The monitor is clear for reading. The monitor is clear for reading. The monitor is clear for reading. Confirm local warranty.", "The stand adjusts for desk work.", "The imported seller does not offer local warranty."]
    items = [{"role": "user", "content": json.dumps({"brief": _verification_input().brief.model_dump(mode="json")})}]
    for index in range(3):
        fetched = {"status": "succeeded", "source_id": source_ids[index], "snapshot_id": snapshot_ids[index], "url": f"https://example.com/monitor-{index}", "title": f"Monitor source {index}", "text": notes[index]}
        note = {"status": "succeeded", "source_id": snapshot_ids[index], "evidence_id": evidence_ids[index], "quote": notes[index]}
        for tool, payload in (("fetch_source", fetched), ("record_source_quote", note)):
            call_id = f"{tool}-{index}"
            items.extend([
                {"type": "function_call", "name": tool, "call_id": call_id, "arguments": "{}"},
                {"type": "function_call_output", "call_id": call_id, "output": json.dumps(payload)},
            ])
    with history_scope(fresh=True):
        for _ in range(3):
            items, projection = project_owner_sources(items)
            assert projection is not None
            assert {str(identifier) for packet in projection.sources for identifier in packet.evidence_ids} == set(evidence_ids)
            for index in range(3):
                packet = next(packet for packet in projection.sources if str(packet.source_id) == source_ids[index])
                assert tuple(str(identifier) for identifier in packet.evidence_ids) == (evidence_ids[index],)
                assert notes[index] in packet.excerpts
                assert snapshot_ids[index] in {str(identifier) for identifier in packet.equivalent_source_ids}
    metadata_only = {"status": "succeeded", "source_id": snapshot_ids[0], "evidence_id": str(new_id()), "quote": "A video title is not reviewed speech.", "metadata_only": True}
    original = [
        {"role": "user", "content": json.dumps({"brief": _verification_input().brief.model_dump(mode="json")})},
        {"type": "function_call", "name": "fetch_source", "call_id": "fetch", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "fetch", "output": json.dumps({"source_id": source_ids[0], "snapshot_id": snapshot_ids[0], "url": "https://example.com/monitor", "title": "Monitor"})},
        {"type": "function_call", "name": "record_source_quote", "call_id": "metadata", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "metadata", "output": json.dumps(metadata_only)},
    ]
    with history_scope(fresh=True):
        _, projection = project_owner_sources(original)
        assert projection is not None
        assert all(metadata_only["evidence_id"] not in {str(identifier) for identifier in packet.evidence_ids} for packet in projection.sources)


def test_consecutive_navigation_dedup_keeps_exact_spans_and_qualified_context():
    from app.agents.decision_sources import _passages

    brief = _verification_input().brief
    claim = "The monitor is clear for reading. Its stand adjusts for desk work."
    navigation = "Catalogue navigation, accessory compatibility and shipping terms."
    qualifier = "The imported offer does not include local warranty."
    original = claim + " " + (navigation + " ") * 120 + qualifier
    passages = _passages(original, brief)
    assert all(span in original for span in passages)
    assert any(claim in span for span in passages)
    assert any(qualifier in span for span in passages)
    assert sum(span.count(navigation) for span in passages) == 1
    assert sum(map(len, passages)) < 300
    ordinary = "The monitor supports USB-C. The imported offer may lack local warranty. Confirm the exact seller."
    assert _passages(ordinary, brief) == (ordinary,)
    nonconsecutive = "The monitor is clear. The imported version has a different warranty. The monitor is clear."
    assert _passages(nonconsecutive, brief) == (nonconsecutive,)
    different_qualifier = "Warranty applies to local stock. Warranty does not apply to imported stock."
    assert _passages(different_qualifier, brief) == (different_qualifier,)


def test_two_repeated_short_sentences_are_preserved():
    from app.agents.decision_sources import _passages
    original = "Dr. Dr. Example reviewed the monitor."
    assert _passages(original, _verification_input().brief) == (original,)
