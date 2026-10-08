from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.context_metrics import measure
from app.agents.research_history import ResearchHistory, bounded_cautions


@dataclass(frozen=True)
class ContextSpan:
    field_id: int
    start: int
    end: int


@dataclass
class ContextField:
    field_id: int
    original: str
    path: tuple[str | int, ...]


@dataclass
class CompactionPlan:
    original: str | list[Any]
    payload: Any = None
    fields: list[ContextField] = field(default_factory=list)
    handles: dict[int, str] = field(default_factory=dict)
    required_spans: list[ContextSpan] = field(default_factory=list)

    def selector_input(self) -> str:
        remaining = 8_000
        chunks = []
        for item in sorted(
            self.fields, key=lambda row: len(row.original), reverse=True
        ):
            if remaining <= 0:
                break
            text = item.original[: min(remaining, 2_000)]
            chunks.append({"field_id": item.field_id, "start": 0, "text": text})
            remaining -= len(text)
        return json.dumps({"chunks": chunks}, ensure_ascii=False, separators=(",", ":"))

    def validate_spans(self, output: str) -> list[ContextSpan]:
        payload = json.loads(output)
        if not isinstance(payload, dict) or set(payload) != {"spans"}:
            raise ValueError("Expected exact span selection.")
        rows = payload["spans"]
        if not isinstance(rows, list) or len(rows) > 12:
            raise ValueError("Too many selected spans.")
        chunks = {
            row["field_id"]: row for row in json.loads(self.selector_input())["chunks"]
        }
        spans = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"field_id", "start", "end"}:
                raise ValueError("Invalid selected span.")
            if any(type(row[key]) is not int for key in row):
                raise ValueError("Offsets must be integers.")
            chunk = chunks.get(row["field_id"])
            if chunk is None or not 0 <= row["start"] < row["end"] <= len(
                chunk["text"]
            ):
                raise ValueError("Selection is outside supplied original text.")
            if row["end"] - row["start"] > 400:
                raise ValueError("Selected passage exceeds its bound.")
            spans.append(ContextSpan(**row))
        return spans

    def render(
        self, limit: int, spans: list[ContextSpan] | None = None
    ) -> str | list[Any]:
        value = json.loads(json.dumps(self.payload))
        fields = {item.path: item for item in self.fields}
        selections: dict[int, list[str]] = {}
        for span in [*self.required_spans, *(spans or ())]:
            item = self.fields[span.field_id]
            selections.setdefault(span.field_id, []).append(
                item.original[span.start : span.end]
            )

        def project(child: Any, path: tuple[str | int, ...] = ()) -> Any:
            item = fields.get(path)
            if item is not None:
                passages = selections.get(item.field_id, [])
                return "\n".join(
                    dict.fromkeys(text for text in [child[:limit], *passages] if text)
                )
            if isinstance(child, dict):
                result = {
                    key: project(text, (*path, key)) for key, text in child.items()
                }
                local = [item for item in self.fields if item.path[:-1] == path]
                if local and child.get("type") not in {
                    "message",
                    "input_text",
                    "output_text",
                    "function_call",
                    "function_call_output",
                }:
                    cautions = bounded_cautions(
                        "\n".join(item.original for item in local)
                    )
                    result["_context_projection"] = {
                        "derived_context": True,
                        "omitted_material_unreviewed": True,
                        "original_view_id": self.handles.get(
                            path[0] if path and isinstance(path[0], int) else -1
                        ),
                        "fields": [str(item.path[-1]) for item in local],
                        **cautions,
                    }
                return result
            if isinstance(child, list):
                return [
                    project(text, (*path, index)) for index, text in enumerate(child)
                ]
            return child

        projected = project(value)
        if isinstance(self.original, str):
            return json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
        for index, item in enumerate(projected):
            for key in ("output", "content"):
                if isinstance(item.get(key), (dict, list)):
                    if key == "content" and isinstance(item[key], list):
                        continue
                    item[key] = json.dumps(
                        item[key], ensure_ascii=False, separators=(",", ":")
                    )
            assistant_fields = [
                field for field in self.fields if field.path[:2] == (index, "content")
            ]
            if item.get("role") == "assistant" and assistant_fields:
                notice = json.dumps(
                    {
                        "derived_context": True,
                        "omitted_material_unreviewed": True,
                        "original_view_id": self.handles.get(index),
                        **bounded_cautions(
                            "\n".join(field.original for field in assistant_fields)
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                if isinstance(item.get("content"), str):
                    item["content"] += "\n" + notice
                else:
                    for block in item.get("content", []):
                        if isinstance(block, dict) and isinstance(
                            block.get("text"), str
                        ):
                            block["text"] += "\n" + notice
                            break
        return projected


_REDUCIBLE = {
    "text",
    "snippet",
    "description",
    "extracted_excerpt",
    "extracted_public_summary",
    "rationale",
    "summary",
    "final_rationale",
    "notes",
    "sponsorship_notes",
}
_PROTECTED = {
    "brief",
    "original_query",
    "prior_answers",
    "answers",
    "buyer_constraints",
    "recommendation_bundle",
}


def plan_compaction(
    original: str | list[Any], history: ResearchHistory
) -> CompactionPlan:
    if isinstance(original, str):
        try:
            payload = json.loads(original)
        except ValueError:
            return CompactionPlan(original)
        if not isinstance(payload, dict):
            return CompactionPlan(original)
        digest_output = json.loads(
            history.register("stage_context", original, force=True)
        )
        handle = digest_output.get("_research_view", {}).get("view_id")
        plan = CompactionPlan(original, payload, handles={-1: handle})
    else:
        payload = json.loads(json.dumps(original))
        plan = CompactionPlan(original, payload)
        for index, item in enumerate(payload):
            if item.get("type") == "function_call" or item.get("type") not in {
                None,
                "message",
                "function_call_output",
            }:
                continue
            key = "output" if item.get("type") == "function_call_output" else "content"
            text = item.get(key)
            if item.get("role") == "assistant":
                registered = json.loads(
                    history.register(
                        "assistant_context", json.dumps({"content": text}), force=True
                    )
                )
                handle = registered.get("_research_view", {}).get("view_id")
                if handle:
                    plan.handles[index] = handle
                if isinstance(text, str) and len(text) > 500:
                    plan.fields.append(
                        ContextField(len(plan.fields), text, (index, key))
                    )
                    continue
                if isinstance(text, list):
                    for block_index, block in enumerate(text):
                        if (
                            isinstance(block, dict)
                            and isinstance(block.get("text"), str)
                            and len(block["text"]) > 500
                        ):
                            plan.fields.append(
                                ContextField(
                                    len(plan.fields),
                                    block["text"],
                                    (index, key, block_index, "text"),
                                )
                            )
                continue
            if not isinstance(text, str):
                continue
            try:
                decoded = json.loads(text)
            except ValueError:
                continue
            if not isinstance(decoded, dict):
                continue
            registered = json.loads(history.register("stage_context", text, force=True))
            handle = registered.get("_research_view", {}).get("view_id")
            if handle:
                plan.handles[index] = handle
            item[key] = decoded

    def scan(
        value: Any, path: tuple[str | int, ...] = (), protected: bool = False
    ) -> None:
        if (
            isinstance(original, list)
            and len(path) == 2
            and isinstance(path[0], int)
            and path[1] == "content"
            and payload[path[0]].get("role") == "user"
            and isinstance(value, list)
        ):
            return
        if isinstance(value, dict):
            for key, child in value.items():
                scan(
                    child,
                    (*path, key),
                    protected or key in _PROTECTED or key == "arguments",
                )
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, (*path, index), protected)
        elif (
            isinstance(value, str)
            and not protected
            and path
            and path[-1] in _REDUCIBLE
            and len(value) > 500
            and path not in {field.path for field in plan.fields}
        ):
            plan.fields.append(ContextField(len(plan.fields), value, path))

    scan(payload)
    if isinstance(original, list):
        focuses: dict[str, str] = {}
        for item in original:
            if item.get("type") != "function_call":
                continue
            try:
                arguments = json.loads(item.get("arguments", "{}"))
            except (TypeError, ValueError):
                continue
            if (
                isinstance(arguments, dict)
                and isinstance(arguments.get("focus"), str)
                and arguments["focus"].strip()
            ):
                focuses[str(item.get("call_id"))] = arguments["focus"]
        for item in plan.fields:
            if not item.path or not isinstance(item.path[0], int):
                continue
            output = original[item.path[0]]
            if output.get("type") != "function_call_output":
                continue
            focus = focuses.get(str(output.get("call_id")))
            if focus is None:
                continue
            match = re.search(re.escape(focus), item.original, re.IGNORECASE)
            if match is None:
                continue
            start = match.start()
            sentence_start = max(
                item.original.rfind("\n", 0, start), item.original.rfind(". ", 0, start)
            )
            if sentence_start >= 0 and start - sentence_start < 100:
                start = sentence_start + (
                    1 if item.original[sentence_start] == "\n" else 2
                )
            plan.required_spans.append(
                ContextSpan(item.field_id, start, min(len(item.original), start + 400))
            )
    return plan


def compact_to_tokens(
    plan: CompactionPlan, tokens: int, spans: list[ContextSpan] | None = None
) -> str | list[Any]:
    if not plan.fields:
        return plan.original
    for limit in (800, 400, 160, 0):
        projected = plan.render(limit, spans)
        if measure(projected)["estimated_tokens"] <= tokens:
            return projected
    return plan.render(0, spans)
