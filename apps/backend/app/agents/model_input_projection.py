from collections import Counter
from collections.abc import Sequence
import json
from typing import Any

from app.schemas.search_sources import SourceEvidence


def model_input_json(payload: dict[str, Any]) -> str:
    original = json.dumps(payload, sort_keys=True)
    explanations: Counter[str] = Counter()
    fields = {"rationale", "summary", "final_rationale", "warnings", "red_flags"}

    def count(value: Any, field: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                count(child, key)
        elif isinstance(value, (list, tuple)):
            for child in value:
                count(child, field)
        elif isinstance(value, str) and field in fields and len(value) >= 80:
            explanations[value] += 1

    count(payload)
    shared = {
        f"explanation_{index + 1}": text
        for index, (text, count) in enumerate(explanations.items())
        if count > 1
    }
    if not shared:
        return original
    references = {text: key for key, text in shared.items()}

    def project(value: Any, field: str = "") -> Any:
        if isinstance(value, dict):
            return {key: project(child, key) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [project(child, field) for child in value]
        if isinstance(value, str) and field in fields and value in references:
            return {"explanation_ref": references[value]}
        return value

    projected = json.dumps(
        {**project(payload), "shared_explanations": shared}, sort_keys=True
    )
    return projected if len(projected.encode()) < len(original.encode()) else original


def restore_explanations(payload: dict[str, Any]) -> dict[str, Any]:
    explanations = payload.get("shared_explanations", {})

    def restore(value: Any) -> Any:
        if isinstance(value, dict):
            if set(value) == {"explanation_ref"}:
                return explanations[value["explanation_ref"]]
            return {key: restore(child) for key, child in value.items()}
        if isinstance(value, list):
            return [restore(child) for child in value]
        return value

    return restore(
        {key: value for key, value in payload.items() if key != "shared_explanations"}
    )


def evidence_model_fields(evidence: Sequence[SourceEvidence]) -> dict[str, Any]:
    rows = [item.model_dump(mode="json", exclude_none=True) for item in evidence]
    videos = Counter(
        json.dumps(row["video"], sort_keys=True) for row in rows if "video" in row
    )
    shared: dict[str, dict[str, Any]] = {}
    references: dict[str, str] = {}
    for row in rows:
        if "video" not in row:
            continue
        identity = json.dumps(row["video"], sort_keys=True)
        if videos[identity] < 2:
            continue
        if identity not in references:
            reference = f"video_{len(shared) + 1}"
            references[identity] = reference
            shared[reference] = row["video"]
        row.pop("video")
        row["video_metadata_ref"] = references[identity]
    return {
        "evidence": rows,
        **({"video_metadata": shared} if shared else {}),
        **(
            {"evidence_gaps": ["No evidence is assigned to this product."]}
            if not rows
            else {}
        ),
    }


def restore_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    payload = restore_explanations(payload)
    metadata = payload.get("video_metadata", {})
    rows = []
    for item in payload["evidence"]:
        row = dict(item)
        if reference := row.pop("video_metadata_ref", None):
            row["video"] = metadata[reference]
        rows.append(row)
    return rows


def canonical_support_model_fields(
    support: Sequence[dict[str, Any]], evidence: Sequence[SourceEvidence]
) -> dict[str, Any]:
    evidence_by_id = {
        str(item.evidence_id): item.model_dump(mode="json", exclude_none=True)
        for item in evidence
    }
    claims = {key: item["claim"] for key, item in evidence_by_id.items()}
    rows = []
    contexts: dict[str, dict[str, Any]] = {}
    context_references: dict[str, str] = {}
    context_counts = Counter(
        json.dumps(
            {key: value for key, value in record.items() if value is not None},
            sort_keys=True,
        )
        for item in support
        for record in item.get("original_records", ())
        if "marketplace_domain" in record or "official_url" in record
    )
    for item in support:
        row = {key: value for key, value in item.items() if value is not None}
        evidence_id = str(row["evidence_id"])
        if row.get("supporting_text") == claims.get(evidence_id):
            row.pop("supporting_text")
            row["supporting_evidence_id"] = row["evidence_id"]
        records = []
        for original in row.get("original_records", ()):
            record = {
                key: value for key, value in original.items() if value is not None
            }
            if "marketplace_domain" in record or "official_url" in record:
                identity = json.dumps(record, sort_keys=True)
                if context_counts[identity] < 2:
                    records.append(record)
                    continue
                if identity not in context_references:
                    reference = f"context_{len(contexts) + 1}"
                    context_references[identity] = reference
                    contexts[reference] = record
                records.append({"source_context_ref": context_references[identity]})
            elif record.get("claim") == claims.get(evidence_id):
                for key in ("claim", "target", "confidence", "source_quality"):
                    if record.get(key) == evidence_by_id[row["evidence_id"]].get(key):
                        record.pop(key, None)
                record["supporting_evidence_id"] = row["evidence_id"]
                records.append(record)
            else:
                records.append(record)
        if "original_records" in row:
            row["original_records"] = records
        rows.append(row)
    return {
        "canonical_support": rows,
        **({"original_source_contexts": contexts} if contexts else {}),
    }
