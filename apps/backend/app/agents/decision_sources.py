from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import urlsplit

from app.agents.context_metrics import measure
from app.agents.research_history import bounded_cautions, complete_excerpt
from app.agents.research_selection import equivalent_url, terms
from app.schemas.decision_sources import (
    CandidateSourceCoverage,
    DecisionSourcePacket,
    SourceDecisionProjection,
)
from app.schemas.intake import ShoppingBrief
from app.schemas.products import CanonicalProduct
from app.schemas.search_sources import SearchResult, SourceEvidence, SourceSnapshot, SourceType


def source_size(value: Any) -> dict[str, int]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {**measure(text), "utf8_bytes": len(text.encode())}


def _video_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold()
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def _passages(text: str, brief: ShoppingBrief) -> tuple[str, ...]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", text) if part.strip()]
    if not paragraphs:
        return ()
    relevance = terms(brief.original_query + " " + " ".join(p.text for p in brief.preferences))
    ranked = sorted(enumerate(paragraphs), key=lambda row: (
        -int(bool(bounded_cautions(row[1])["material_cautions"])),
        -len(terms(row[1]) & relevance), row[0],
    ))
    retained = []
    remaining = 4000
    for _, passage in ranked:
        excerpt = complete_excerpt(passage, remaining)
        if excerpt:
            retained.append(excerpt)
            remaining -= len(excerpt)
        if not remaining:
            break
    return tuple(retained)


def source_packets(
    brief: ShoppingBrief,
    results: Sequence[SearchResult],
    snapshots: Sequence[SourceSnapshot],
    evidence: Sequence[SourceEvidence],
    products: Sequence[CanonicalProduct] = (),
) -> tuple[DecisionSourcePacket, ...]:
    result_urls = {equivalent_url(str(item.url)): item for item in results}
    results_by_id = {str(item.source_id): item for item in results}

    def source_key(item: SearchResult | SourceSnapshot) -> str:
        linked = item.provider.raw.get("search_result_source_id")
        lead = results_by_id.get(str(linked))
        return equivalent_url(str(lead.url if lead else item.url))

    snapshot_urls: dict[str, SourceSnapshot] = {}
    evidence_sources = {item.source_id for item in evidence if not item.metadata_only}
    for item in snapshots:
        url = source_key(item)
        if url not in snapshot_urls or item.source_id in evidence_sources:
            snapshot_urls[url] = item
    product_names = {str(item.product_id): item.name for item in products}
    packets = []
    for url in dict.fromkeys([*result_urls, *snapshot_urls]):
        lead = result_urls.get(url)
        snapshot = snapshot_urls.get(url)
        identifiers = tuple(dict.fromkeys([*(item.source_id for item in (lead, snapshot) if item), *(item.source_id for item in [*results, *snapshots] if source_key(item) == url)]))
        if not identifiers:
            continue
        claims = [item for item in evidence if item.source_id in identifiers
            or (item.video is not None and equivalent_url(str(item.video.url)) == url)]
        identifiers = tuple(dict.fromkeys([*identifiers, *(item.source_id for item in claims)]))
        speech = [item for item in claims if item.transcript_support and not item.metadata_only]
        video_source = _video_url(url) or any(item.source_type == SourceType.VIDEO for item in (lead, snapshot) if item) or bool(snapshot and snapshot.video)
        content = snapshot.extracted_content.text if snapshot and snapshot.extracted_content else ""
        annotations = [row for item in snapshots if source_key(item) == url for row in item.provider.raw.get("candidate_coverage", [])]
        valid_annotations = [item for item in annotations if isinstance(item, dict)
            and isinstance(item.get("quote"), str) and item["quote"] in content
            and item.get("candidate_names")]
        candidates = list(dict.fromkeys(
            [name for item in valid_annotations for name in item["candidate_names"]]
            + [product_names[str(item.target.product_id)] for item in claims
               if str(item.target.product_id) in product_names and not item.metadata_only]
        ))
        questions = tuple(dict.fromkeys(item.get("buying_question", "") for item in valid_annotations if item.get("buying_question")))
        if speech:
            excerpts = ()
            kind = "accepted_speech"
        elif content and not video_source:
            excerpts = tuple(dict.fromkeys([item["quote"] for item in valid_annotations] + list(_passages(content, brief))))
            kind = "page"
        elif claims and not all(item.metadata_only for item in claims):
            excerpts = tuple(dict.fromkeys(item.claim for item in claims if not item.metadata_only))
            kind = "source_note"
        else:
            excerpts = ((lead.snippet,) if lead and lead.snippet else ())
            kind = "metadata_only" if video_source else "search_lead"
            candidates = []
        support = {segment.segment_id: segment for item in speech for segment in item.transcript_support}
        original = content or "\n".join(dict.fromkeys([*excerpts, *(item.text for item in support.values())]))
        packets.append(DecisionSourcePacket(
            source_id=identifiers[0], equivalent_source_ids=identifiers[1:], url=url,
            title=(lead.title if lead else snapshot.title or url), content_kind=kind,
            excerpts=excerpts, source_notes=tuple(item.claim for item in claims if not item.metadata_only and not item.transcript_support), candidate_names=tuple(candidates), buying_questions=questions, coverage_notes=tuple(valid_annotations),
            findings=tuple(dict.fromkeys(item["finding"] for item in valid_annotations if item.get("finding"))),
            perspective=next((item["perspective"] for item in valid_annotations if item.get("perspective")), None),
            evidence_ids=tuple(item.evidence_id for item in claims if not item.metadata_only),
            evidence=tuple(item.model_copy(update={"transcript_support": (), "video": item.video.model_copy(update={"description": None}) if item.video else None}) for item in claims if not item.metadata_only),
            transcript_support=tuple(support.values()),
            source_quality=snapshot.quality if snapshot else lead.quality, original_content_size=source_size(original),
            material_cautions=tuple(bounded_cautions(original)["material_cautions"]),
            content_sha256=sha256(original.encode()).hexdigest(),
            unreviewed_content=bool(content and "\n".join(excerpts) != content) or any(item.video and item.video.description for item in claims),
        ))
    represented = {identifier for packet in packets for identifier in (packet.source_id, *packet.equivalent_source_ids)}
    orphan_claims: dict[str, list[SourceEvidence]] = {}
    for item in evidence:
        if item.source_id not in represented and not item.metadata_only:
            key = equivalent_url(str(item.video.url)) if item.video else str(item.source_id)
            orphan_claims.setdefault(key, []).append(item)
    for claims in orphan_claims.values():
        identifiers = tuple(dict.fromkeys(item.source_id for item in claims))
        support = {span.segment_id: span for item in claims for span in item.transcript_support}
        video = next((item.video for item in claims if item.video is not None), None)
        original = "\n".join(dict.fromkeys([*(item.claim for item in claims if not item.transcript_support), *(span.text for span in support.values())]))
        packets.append(DecisionSourcePacket(
            source_id=identifiers[0], equivalent_source_ids=identifiers[1:],
            url=equivalent_url(str(video.url)) if video else "", title=video.title or "Review speech" if video else "Saved source note",
            content_kind="accepted_speech" if support else "source_note", source_notes=tuple(item.claim for item in claims if not item.transcript_support),
            candidate_names=tuple(dict.fromkeys(product_names[str(item.target.product_id)] for item in claims if str(item.target.product_id) in product_names)),
            evidence_ids=tuple(item.evidence_id for item in claims),
            evidence=tuple(item.model_copy(update={"transcript_support": (), "video": item.video.model_copy(update={"description": None}) if item.video else None}) for item in claims),
            transcript_support=tuple(support.values()), source_quality=claims[0].source_quality,
            original_content_size=source_size(original), content_sha256=sha256(original.encode()).hexdigest(),
            material_cautions=tuple(bounded_cautions(original)["material_cautions"]),
            unreviewed_content=any(item.video and item.video.description for item in claims),
        ))
    return tuple(packets)


def coverage_pairs(packet: DecisionSourcePacket) -> set[tuple[str, str]]:
    if packet.coverage_notes:
        return {(name, note.buying_question) for note in packet.coverage_notes for name in note.candidate_names}
    return {(name, question) for name in packet.candidate_names for question in (packet.buying_questions or ("general suitability",))}


def select_decision_sources(
    brief: ShoppingBrief, sources: Sequence[DecisionSourcePacket]
) -> SourceDecisionProjection:
    relevance = terms(brief.original_query + " " + " ".join(p.text for p in brief.preferences))
    pending = list(sources)
    retained = []
    deferred = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...], str]] = set()
    seen_urls: set[str] = set()
    covered: set[tuple[str, str]] = set()
    findings: set[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], str | None]] = set()
    while pending:
        pending.sort(key=lambda packet: (
            -len(coverage_pairs(packet) - covered),
            -int(bool(packet.material_cautions)),
            -int(packet.content_kind == "accepted_speech"),
            -({"strong": 3, "adequate": 2, "mixed": 1}.get(packet.source_quality.level.value, 0) if packet.source_quality else 0),
            -len(packet.candidate_names),
            -len(terms(" ".join(packet.excerpts)) & relevance), packet.url,
        ))
        packet = pending.pop(0)
        buyer_relevant = bool(packet.coverage_notes or packet.evidence or (terms(packet.title + " " + " ".join([*packet.excerpts, *packet.source_notes, *packet.buying_questions])) & relevance))
        meaningful = packet.content_kind not in {"metadata_only", "search_lead"} and bool(packet.excerpts or packet.evidence) and buyer_relevant
        useful_lead = packet.content_kind == "search_lead" and bool(terms(" ".join(packet.excerpts)) & relevance)
        identity = (tuple(sorted(packet.candidate_names)), tuple(sorted(packet.buying_questions)), (" ".join(packet.excerpts).casefold() if packet.content_kind != "accepted_speech" else json.dumps([row.model_dump(mode="json") for row in packet.evidence], sort_keys=True)) + (str(packet.source_id) if not packet.url else ""))
        contribution = (tuple(sorted(packet.candidate_names)), tuple(sorted(packet.buying_questions)), tuple(sorted(packet.findings)), packet.perspective)
        repeated_finding = bool(packet.findings and packet.candidate_names and contribution in findings)
        if not (meaningful or useful_lead) or (packet.url and packet.url in seen_urls) or identity in seen or (repeated_finding and not packet.material_cautions and packet.content_kind != "accepted_speech"):
            deferred.append(packet.source_id)
            continue
        retained.append(packet)
        seen.add(identity)
        findings.add(contribution)
        covered.update(coverage_pairs(packet))
        seen_urls.add(packet.url)
    coverage = []
    for candidate in dict.fromkeys(name for packet in retained for name in packet.candidate_names):
        for kind in ("page", "accepted_speech", "source_note"):
            supporting = [packet for packet in retained if candidate in packet.candidate_names and packet.content_kind == kind]
            if supporting:
                coverage.append(CandidateSourceCoverage(
                    candidate_name=candidate, source_ids=tuple(packet.source_id for packet in supporting),
                    buying_questions=tuple(dict.fromkeys(question for packet in supporting for question in (tuple(note.buying_question for note in packet.coverage_notes if candidate in note.candidate_names) if packet.coverage_notes else packet.buying_questions))),
                    support_kind=kind,
                ))
    selected = tuple(packet.source_id for packet in retained)
    identity = json.dumps([packet.model_dump(mode="json") for packet in retained], sort_keys=True)
    return SourceDecisionProjection(
        projection_id=sha256(identity.encode()).hexdigest(), selected_source_ids=selected,
        deferred_source_ids=tuple(deferred), candidate_coverage=tuple(coverage), sources=tuple(retained),
        measurements={
            "raw_unique_sources": len(sources), "selected_unique_sources": len(retained),
            "deferred_unique_sources": len(deferred), "meaningful_candidate_count": len({item.candidate_name for item in coverage}),
            "raw_source_content": {key: sum(packet.original_content_size.get(key, 0) for packet in sources) for key in ("characters", "utf8_bytes", "estimated_tokens")},
            "packet_input_content": source_size([packet.model_dump(mode="json") for packet in sources]),
            "selected_source_content": source_size(json.loads(identity)),
            "token_estimator": "utf8_bytes_divided_by_three", "provider_source_only_tokens_known": False,
            "source_content_scope": "loaded_archive_text_or_observed_passages", "complete_archive_size_known": False,
        },
    )


def input_projection(value: Any) -> SourceDecisionProjection | None:
    if isinstance(value, str):
        try:
            return input_projection(json.loads(value))
        except ValueError:
            return None
    if isinstance(value, dict):
        if isinstance(value.get("decision_sources"), dict):
            return SourceDecisionProjection.model_validate(value["decision_sources"])
        for key, child in value.items():
            if isinstance(child, str) and key not in {"output", "content"} and not (
                key == "text" and value.get("type") in {"input_text", "output_text"}
            ):
                continue
            projection = input_projection(child)
            if projection is not None:
                return projection
    if isinstance(value, list):
        for child in reversed(value):
            if isinstance(child, str):
                continue
            projection = input_projection(child)
            if projection is not None:
                return projection
    return None


def project_owner_sources(original: Any) -> tuple[Any, SourceDecisionProjection | None]:
    existing = input_projection(original)
    if existing is not None and not (isinstance(original, list) and any(item.get("type") == "function_call_output" for item in original)):
        return original, existing
    decoded: list[dict[str, Any]] = []
    from app.agents.research_history import active_history

    history = active_history()
    restored_views: set[str] = set()
    names = {str(item.get("call_id")): item.get("name") for item in original if item.get("type") == "function_call"} if isinstance(original, list) else {}

    def collect(value: Any, *, decode_string: bool = False, bundle_span: bool = False) -> None:
        if isinstance(value, str):
            if not decode_string:
                return
            try:
                collect(json.loads(value), bundle_span=bundle_span)
            except ValueError:
                return
        elif isinstance(value, dict):
            decoded.append(value)
            view_id = value.get("archive_view_id")
            if history is not None and isinstance(view_id, str) and view_id not in restored_views:
                view = history.views.get(view_id)
                if view is not None and view.tool == "decision_source_original":
                    restored_views.add(view_id)
                    collect(view.payload)
            for key, child in value.items():
                if key not in {"_research_view", "_context_projection"}:
                    collect(child, decode_string=key in {"output", "content"} or (bundle_span and key == "text") or (
                        key == "text" and value.get("type") in {"input_text", "output_text"}
                    ), bundle_span=key == "output" and names.get(str(value.get("call_id"))) == "read_source_bundle")
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(original, decode_string=True)
    brief_row = next((row["brief"] for row in decoded if isinstance(row.get("brief"), dict)), None)
    if brief_row is None:
        return original, None
    brief = ShoppingBrief.model_validate(brief_row)
    records: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    product_names: dict[str, str] = {}
    for row in decoded:
        product_names.update(row.get("candidate_names_by_product_id", {}))
        if row.get("product_id") and row.get("name"):
            product_names[str(row["product_id"])] = row["name"]
        if row.get("source_id") and row.get("url"):
            key = equivalent_url(str(row["url"]))
            video_source = _video_url(key) or row.get("source_type") == SourceType.VIDEO or bool(row.get("video"))
            aliases[str(row["source_id"])] = key
            if row.get("snapshot_id"):
                aliases[str(row["snapshot_id"])] = key
            records.setdefault(key, {"source_id": row["source_id"], "url": key, "title": row.get("title") or key,
                                     "excerpts": [], "candidate_names": [], "buying_questions": [], "evidence_ids": [],
                                     "transcript_support": [], "content_kind": "metadata_only" if video_source else "search_lead", "material_cautions": []})
            if video_source:
                records[key]["content_kind"] = "metadata_only"
    segments = {str(row["segment_id"]): row for row in decoded if row.get("segment_id") and isinstance(row.get("text"), str)}
    videos = {str(row["video_id"]): row for row in decoded if row.get("video_id") and row.get("url")}
    for row in decoded:
        source_id = str(row.get("source_id", ""))
        if not source_id:
            continue
        key = aliases.get(source_id)
        if key is None and row.get("video_id") in videos:
            video = videos[row["video_id"]]
            key = equivalent_url(str(video["url"]))
            records.setdefault(key, {"source_id": source_id, "url": key, "title": video.get("title") or key,
                "excerpts": [], "candidate_names": [], "buying_questions": [], "evidence_ids": [],
                "transcript_support": [], "content_kind": "metadata_only", "material_cautions": []})
        if key not in records:
            continue
        record = records[key]
        identifiers = record.setdefault("equivalent_source_ids", [])
        identifiers.extend(identifier for identifier in (row.get("source_id"), row.get("snapshot_id"))
            if identifier and identifier != record["source_id"] and identifier not in identifiers)
        text = row.get("text") or row.get("page_text") or row.get("source_note") or row.get("quote")
        if isinstance(text, str) and text.strip():
            record["excerpts"].extend(_passages(text, brief))
            if record["content_kind"] != "metadata_only":
                record["content_kind"] = "page" if row.get("text") or row.get("page_text") else "source_note"
        support = row.get("transcript_support", [])
        for segment_id in row.get("transcript_segment_ids", []):
            segment = segments.get(str(segment_id))
            if segment and not any(str(item.get("segment_id")) == str(segment_id) for item in support):
                support = [*support, {**{key: segment[key] for key in ("segment_id", "video_id", "start_seconds", "end_seconds", "text") if key in segment},
                    "content_sha256": sha256(segment["text"].encode()).hexdigest()}]
        if support and not row.get("metadata_only"):
            record["content_kind"] = "accepted_speech"
            video = videos.get(str(row.get("video_id")), row.get("video"))
            if video and row.get("target") and row.get("confidence") and row.get("source_quality"):
                from app.schemas.search_sources import EvidenceType
                accepted = {key: row[key] for key in ("evidence_id", "source_id", "target", "claim", "confidence", "source_quality", "timestamp_references", "transcript_segment_ids") if key in row}
                accepted.update(evidence_type=EvidenceType.VIDEO_CLAIM, transcript_support=support,
                    video={key: video[key] for key in ("video_id", "url", "title", "channel_id", "channel_name", "transcript_availability", "sponsorship_disclosed", "affiliate_links_disclosed", "affiliate_bias_risk", "bias_notes") if key in video})
                record.setdefault("evidence", []).append(accepted)
            else:
                record["transcript_support"].extend(support)
            if row.get("claim") and not record.get("evidence"):
                record["excerpts"].append(row["claim"])
            if row.get("evidence_id"):
                record["evidence_ids"].append(row["evidence_id"])
            product_id = str(row.get("target", {}).get("product_id") or row.get("product_id", ""))
            if product_id in product_names:
                record["candidate_names"].append(product_names[product_id])
        if row.get("candidate_names") and text:
            if row.get("evidence_id") and row.get("buying_question") and row.get("finding"):
                record.setdefault("coverage_notes", []).append({key: row[key] for key in ("candidate_names", "buying_question", "finding", "quote", "evidence_id", "perspective") if key in row})
            record["candidate_names"].extend(row["candidate_names"])
            if row.get("buying_question"):
                record["buying_questions"].append(row["buying_question"])
            if row.get("finding"):
                record.setdefault("findings", []).append(row["finding"])
            if row.get("perspective"):
                record["perspective"] = row["perspective"]
        record["material_cautions"].extend(row.get("material_cautions", []))
        if isinstance(row.get("source_quality"), dict):
            record["source_quality"] = row["source_quality"]
        elif isinstance(row.get("source_quality"), str):
            record["source_quality"] = {"level": row["source_quality"], "score": row.get("source_quality_score")}
    packets = list(existing.sources) if existing is not None else []
    for record in records.values():
        for key in ("excerpts", "candidate_names", "buying_questions", "evidence_ids", "material_cautions"):
            record[key] = list(dict.fromkeys(record[key]))
        for evidence_row in record.get("evidence", []):
            record["transcript_support"].extend(evidence_row.get("transcript_support", []))
            evidence_row["transcript_support"] = []
            if evidence_row.get("video", {}).get("description"):
                evidence_row["video"]["description"] = None
                record["unreviewed_content"] = True
        record["transcript_support"] = list({str(row["segment_id"]): row for row in record["transcript_support"]}.values())
        content = "\n".join(dict.fromkeys([*record["excerpts"], *(segment["text"] for segment in record["transcript_support"])]))
        record["content_sha256"] = sha256(content.encode()).hexdigest()
        record["original_content_size"] = source_size(content)
        packets.append(DecisionSourcePacket.model_validate(record))
    if not packets:
        return original, None
    packets = list({packet.url or str(packet.source_id): packet for packet in packets}.values())
    projection = select_decision_sources(brief, packets)
    if not isinstance(original, list):
        return original, projection
    source_tools = {"search_sources", "read_search_results", "fetch_source", "read_source_snapshot", "read_run_evidence", "read_research_result", "read_source_bundle", "read_video_transcript", "read_community_discussion", "record_source_quote", "consult_source_intelligence"}
    projected = []
    for item in original:
        if item.get("type") == "function_call_output" and names.get(str(item.get("call_id"))) in source_tools:
            output = item.get("output", "")
            try:
                payload = json.loads(output) if isinstance(output, str) else output
            except ValueError:
                payload = {}
            if names.get(str(item.get("call_id"))) == "read_source_bundle" and isinstance(payload, dict) and isinstance(payload.get("text"), str):
                try:
                    json.loads(payload["text"])
                except ValueError:
                    projected.append(item)
                    continue
            receipt = {key: payload[key] for key in ("status", "source_id", "snapshot_id", "evidence_id", "gap", "next_start_char", "total_characters") if isinstance(payload, dict) and key in payload}
            if history is not None:
                receipt["archive_view_id"] = history.archive("decision_source_original", payload)
                receipt["reload_tool"] = "read_research_result"
            receipt["decision_projection_id"] = projection.projection_id
            receipt["omitted_material_unreviewed"] = True
            projected.append({**item, "output": json.dumps(receipt)})
        else:
            projected.append(item)
    if existing is not None:
        projected = replace_input_projection(projected, projection.model_dump(mode="json"))
    else:
        projected.append({"role": "user", "content": json.dumps({"decision_sources": projection.model_dump(mode="json")})})
    return projected, projection


def fit_owner_projection(value: Any, tokens: int) -> Any:
    projection = input_projection(value)
    if projection is None or measure(value)["estimated_tokens"] <= tokens:
        return value
    packets = list(projection.sources)
    deferred = list(projection.deferred_source_ids)

    while packets:
        removed = packets.pop()
        deferred.append(removed.source_id)
        retained = {packet.source_id for packet in packets}
        coverage = [row.model_copy(update={"source_ids": tuple(identifier for identifier in row.source_ids if identifier in retained)})
            for row in projection.candidate_coverage if retained.intersection(row.source_ids)]
        payload = [packet.model_dump(mode="json") for packet in packets]
        revised = projection.model_copy(update={
            "projection_id": sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "sources": tuple(packets), "selected_source_ids": tuple(packet.source_id for packet in packets),
            "deferred_source_ids": tuple(dict.fromkeys(deferred)), "candidate_coverage": tuple(coverage),
            "measurements": {**projection.measurements, "selected_unique_sources": len(packets),
                "deferred_unique_sources": len(set(deferred)), "selected_source_content": source_size(payload),
                "meaningful_candidate_count": len({row.candidate_name for row in coverage}),
                "existing_context_budget_selection": True, "omitted_material_unreviewed": True},
        })
        candidate = replace_input_projection(value, revised.model_dump(mode="json"))
        if measure(candidate)["estimated_tokens"] <= tokens:
            return candidate
    return value


def replace_input_projection(item: Any, replacement: dict[str, Any], *, decode_string: bool = True) -> Any:
    if isinstance(item, str):
        if not decode_string:
            return item
        try:
            decoded = json.loads(item)
        except ValueError:
            return item
        projected = replace_input_projection(decoded, replacement)
        return json.dumps(projected, ensure_ascii=False) if projected != decoded else item
    if isinstance(item, dict):
        return {key: replacement if key == "decision_sources" else replace_input_projection(child, replacement,
            decode_string=key in {"output", "content"} or (
                key == "text" and item.get("type") in {"input_text", "output_text"}
            ))
            for key, child in item.items()}
    if isinstance(item, list):
        return [replace_input_projection(child, replacement, decode_string=False) for child in item]
    return item

