"""Local size estimates, deliberately independent of provider tokenizers."""

import json
from hashlib import sha256
from typing import Any


def measure(value: Any) -> dict[str, int]:
    encoded = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {
        "characters": len(encoded),
        "estimated_tokens": (len(encoded.encode()) + 2) // 3,
    }


def input_breakdown(items: list[Any]) -> dict[str, Any]:
    groups: dict[str, int] = {}
    seen: set[str] = set()
    replayed = 0
    for item in items:
        encoded = json.dumps(item, ensure_ascii=False)
        digest = sha256(encoded.encode()).hexdigest()
        if digest in seen:
            replayed += len(encoded)
        seen.add(digest)
        kind = item.get("type", "message")
        label = (
            "tool_results"
            if kind == "function_call_output"
            else "prior_turns_handoffs"
            if kind != "message" or item.get("role") != "user"
            else "brief_state"
        )
        groups[label] = groups.get(label, 0) + len(encoded)
        content = item.get("output", item.get("content"))
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        for key in (
            "brief",
            "original_query",
            "products",
            "listings",
            "evidence",
            "source_evidence",
            "category_analyses",
            "trust_assessments",
            "recommendation_bundle",
            "text",
            "segments",
            "discussion",
            "pages",
            "research_state",
            "quote",
            "warnings",
            "evidence_gaps",
        ):
            if key in payload:
                groups[f"field:{key}"] = (
                    groups.get(f"field:{key}", 0) + measure(payload[key])["characters"]
                )
    return {
        "characters_by_component": groups,
        "identical_item_replay_characters": replayed,
        "field_components_overlap_enclosing_groups": True,
    }
