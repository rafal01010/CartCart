from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.agents.context_metrics import measure
from app.agents.research_history import (
    ResearchHistory,
    bounded_cautions,
    complete_excerpt,
    native_item_key,
)


def stage_payload(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    return (
        payload
        if isinstance(payload, dict)
        and ({"brief", "recommendation_bundle"} & payload.keys())
        else None
    )


def preserve_stage_fields(stage: str) -> frozenset[str]:
    return (
        frozenset(
            {
                "canonical_support",
                "evidence",
                "products",
                "listings",
                "trust_assessments",
                "original_source_contexts",
            }
        )
        if "verif" in stage.lower()
        else frozenset()
    )


def protected_stage(
    payload: dict[str, Any], preserve_fields: frozenset[str] = frozenset()
) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key in _PROTECTED
        or key in preserve_fields
        or key.endswith("_id")
        or key.endswith("_ids")
        or key in {"search_plan", "query_plan", "owner_scope", "ownership", "objective"}
    }


def essential_input(
    original: str | list[Any], preserve_fields: frozenset[str] = frozenset()
) -> Any:
    if isinstance(original, str):
        payload = stage_payload(original)
        return (
            protected_stage(payload, preserve_fields)
            if payload is not None
            else original
        )
    result = json.loads(
        json.dumps([item for item in original if item.get("role") == "user"])
    )
    for item in result:
        content = item.get("content")
        if isinstance(content, str):
            payload = stage_payload(content)
            if payload is not None:
                item["content"] = protected_stage(payload, preserve_fields)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    payload = stage_payload(block["text"])
                    if payload is not None:
                        block["text"] = protected_stage(payload, preserve_fields)
    return result


def project_stage_text(
    text: str,
    history: ResearchHistory,
    tokens: int,
    preserve_fields: frozenset[str] = frozenset(),
) -> str:
    payload = stage_payload(text)
    if payload is None:
        return text
    protected = protected_stage(payload, preserve_fields)
    handle = history.archive("stage_context", payload)
    available = max(0, tokens - measure(protected)["estimated_tokens"])
    projected = json.dumps(
        {
            **protected,
            "_context_projection": history.checkpoint(
                handle, characters=min(6000, max(500, available * 2))
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        projected
        if measure(projected)["estimated_tokens"] < measure(text)["estimated_tokens"]
        else text
    )


def restore_source_views(
    items: list[Any],
    originals: list[Any],
    history: ResearchHistory,
    *,
    characters: int = 2000,
    excluded_domains: set[str] | None = None,
) -> list[Any]:
    calls = {
        str(item.get("call_id")): item.get("name")
        for item in originals
        if item.get("type") == "function_call"
    }
    retained = {
        str(item.get("call_id"))
        for item in items
        if item.get("type") == "function_call_output"
    }
    urls: dict[str, str] = {}

    def source_urls(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("url"), str):
                for key in ("source_id", "snapshot_id"):
                    if value.get(key) is not None:
                        urls[str(value[key])] = value["url"]
            for child in value.values():
                source_urls(child)
        elif isinstance(value, list):
            for child in value:
                source_urls(child)

    payloads = {}
    for item in originals:
        if item.get("type") == "function_call_output" and isinstance(
            item.get("output"), str
        ):
            try:
                payload = json.loads(item["output"])
            except ValueError:
                continue
            payloads[str(item.get("call_id"))] = payload
            source_urls(payload)
    replacements = {}
    domains = set()
    for item in reversed(originals):
        call_id = str(item.get("call_id"))
        if (
            item.get("type") != "function_call_output"
            or call_id not in retained
            or calls.get(call_id)
            not in {
                "fetch_source",
                "read_source_snapshot",
                "read_run_evidence",
                "read_research_result",
                "read_video_transcript",
                "read_community_discussion",
            }
        ):
            continue
        payload = payloads.get(call_id)
        spans = []
        remaining = characters

        def collect(value: Any, identities: dict[str, str] | None = None) -> None:
            nonlocal remaining
            if remaining <= 0:
                return
            if isinstance(value, dict):
                identities = {
                    key: str(value[key])
                    for key in ("source_id", "snapshot_id")
                    if value.get(key) is not None
                } or identities
                if (
                    identities
                    and isinstance(value.get("text"), str)
                    and value["text"].strip()
                ):
                    text = value["text"][:remaining]
                    spans.append(
                        {
                            **identities,
                            "text": text,
                            **{
                                key: value[key]
                                for key in ("start_char", "content_sha256")
                                if key in value
                            },
                        }
                    )
                    remaining -= len(text)
                for key, child in value.items():
                    if key not in {
                        "_context_projection",
                        "_research_view",
                        "material_cautions",
                        "cautions",
                    }:
                        collect(child, identities)
            elif isinstance(value, list):
                for child in value:
                    collect(child, identities)

        collect(payload)
        if not spans:
            continue
        source_id = next(
            str(spans[0][key])
            for key in ("source_id", "snapshot_id")
            if key in spans[0]
        )
        url = urls.get(source_id, "")
        domain = (urlsplit(url).hostname or source_id).removeprefix("www.")
        if domain in domains or domain in (excluded_domains or set()):
            continue
        domains.add(domain)
        handle = history.archive("capture_source_view", payload)
        envelope = {
            "status": payload.get("status", "succeeded")
            if isinstance(payload, dict)
            else "succeeded",
            "source_spans": spans,
            "_context_projection": history.checkpoint(handle, characters=1000),
        }
        if url:
            envelope["url"] = url
        replacements[call_id] = json.dumps(
            envelope, ensure_ascii=False, separators=(",", ":")
        )
        if len(replacements) == 2:
            break
    return [
        {**item, "output": replacements[str(item.get("call_id"))]}
        if item.get("type") == "function_call_output"
        and str(item.get("call_id")) in replacements
        else item
        for item in items
    ]


@dataclass(frozen=True)
class CompletedExchange:
    call_id: str
    call_index: int
    output_index: int


@dataclass(frozen=True)
class CompletedResponseBatch:
    start: int
    end: int
    exchanges: tuple[CompletedExchange, ...]
    native_keys: tuple[str, ...] = ()


def _completed_response_batches(
    items: list[Any], history: ResearchHistory
) -> list[CompletedResponseBatch]:
    outputs = {
        str(item.get("call_id")): index
        for index, item in enumerate(items)
        if item.get("type") == "function_call_output"
    }
    positions = {
        native_item_key(item): index
        for index, item in enumerate(items)
        if item.get("type") != "function_call_output"
    }
    recorded = [
        group
        for group in history.native_response_groups
        if any(key in positions for key in group)
    ]
    if recorded:
        batches = []
        for group in recorded:
            if any(key not in positions for key in group):
                continue
            indices = [positions[key] for key in group]
            if any(
                items[index].get("status") in {"in_progress", "incomplete", "searching"}
                for index in indices
            ):
                continue
            calls = [
                (str(items[index]["call_id"]), index)
                for index in indices
                if items[index].get("type") == "function_call"
            ]
            if any(
                call_id not in outputs or outputs[call_id] <= index
                for call_id, index in calls
            ):
                continue
            exchanges = tuple(
                CompletedExchange(call_id, index, outputs[call_id])
                for call_id, index in calls
            )
            batches.append(
                CompletedResponseBatch(
                    min(indices),
                    max([*indices, *(pair.output_index for pair in exchanges)]) + 1,
                    exchanges,
                    group,
                )
            )
        return sorted(batches, key=lambda batch: batch.start)
    call_groups: list[list[tuple[str, int]]] = []
    group_end = -1
    for index, item in enumerate(items):
        if item.get("type") != "function_call":
            continue
        call_id = str(item.get("call_id"))
        if not call_groups or index > group_end:
            call_groups.append([])
        call_groups[-1].append((call_id, index))
        group_end = max(group_end, outputs.get(call_id, len(items)))
    batches = []
    for call_group in call_groups:
        if any(
            call_id not in outputs or outputs[call_id] <= index
            for call_id, index in call_group
        ):
            continue
        start = call_group[0][1]
        while start > 0:
            preceding = items[start - 1]
            if preceding.get("type") == "function_call_output" or preceding.get(
                "role"
            ) in {"user", "system", "developer"}:
                break
            start -= 1
        batches.append(
            CompletedResponseBatch(
                start,
                max(outputs[call_id] for call_id, _ in call_group) + 1,
                tuple(
                    CompletedExchange(call_id, index, outputs[call_id])
                    for call_id, index in call_group
                ),
            )
        )
    return batches


def rotate_exchanges(
    items: list[Any], history: ResearchHistory, *, originals: list[Any], recent: int = 2
) -> tuple[list[Any], str | None, int]:
    batches = _completed_response_batches(items, history)
    retiring = batches[:-recent] if recent else batches
    if not retiring:
        return items, None, 0
    removed = {
        index
        for batch in retiring
        for index in range(batch.start, batch.end)
        if items[index].get("role") not in {"user", "system", "developer"}
    }
    retired_ids = {pair.call_id for batch in retiring for pair in batch.exchanges}
    retired_groups = {batch.native_keys for batch in retiring if batch.native_keys}
    original_batches = _completed_response_batches(originals, history)
    original_removed = {
        index
        for batch in original_batches
        if (
            batch.native_keys in retired_groups
            if batch.native_keys
            else {pair.call_id for pair in batch.exchanges} <= retired_ids
        )
        for index in range(batch.start, batch.end)
        if originals[index].get("role") not in {"user", "system", "developer"}
    }
    exact = [item for index, item in enumerate(originals) if index in original_removed]
    prior_checkpoints = [
        item
        for index, item in enumerate(items)
        if item.get("role") == "assistant"
        and isinstance(item.get("content"), str)
        and item["content"] in history.checkpoint_messages
    ]
    removed.update(
        index for index, item in enumerate(items) if item in prior_checkpoints
    )
    handle = history.archive(
        "sdk_exchanges", {"exchanges": exact, "prior_checkpoints": prior_checkpoints}
    )
    checkpoint = {
        "role": "assistant",
        "content": json.dumps(
            history.checkpoint(handle), ensure_ascii=False, separators=(",", ":")
        ),
    }
    history.checkpoint_messages.add(checkpoint["content"])
    retained = [item for index, item in enumerate(items) if index not in removed]
    position = next(
        (
            index
            for index, item in enumerate(retained)
            if item.get("role") not in {"user", "system", "developer"}
        ),
        len(retained),
    )
    retained.insert(position, checkpoint)
    return retained, handle, sum(max(1, len(batch.exchanges)) for batch in retiring)


def bound_original_views(
    original: str | list[Any],
    history: ResearchHistory,
    tokens: int,
    preserve_fields: frozenset[str] = frozenset(),
) -> str | list[Any]:
    if isinstance(original, str):
        return project_stage_text(original, history, tokens, preserve_fields)
    result = json.loads(json.dumps(original))
    for item in result:
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            item["content"] = project_stage_text(
                content, history, tokens, preserve_fields
            )
        elif isinstance(content, list):
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "input_text"
                    and isinstance(block.get("text"), str)
                ):
                    block["text"] = project_stage_text(
                        block["text"], history, tokens, preserve_fields
                    )
    candidates = [
        index
        for index, item in enumerate(result)
        if item.get("type") == "function_call_output"
        or (item.get("role") == "assistant" and item.get("type") in {None, "message"})
    ]
    for index in sorted(
        candidates,
        key=lambda index: measure(result[index])["estimated_tokens"],
        reverse=True,
    ):
        if measure(result)["estimated_tokens"] <= tokens:
            break
        item = result[index]
        key = "output" if item.get("type") == "function_call_output" else "content"
        value = item.get(key)
        try:
            decoded = json.loads(value) if isinstance(value, str) else value
        except ValueError:
            decoded = {"text": value}
        handle = history.archive(
            "sdk_output" if key == "output" else "assistant_context", decoded
        )
        envelope = history.checkpoint(
            handle,
            characters=4000
            if isinstance(decoded, dict) and "quote" in decoded
            else 1800,
        )
        if isinstance(decoded, dict) and isinstance(decoded.get("status"), str):
            envelope["status"] = decoded["status"]
        projected = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        if measure(projected)["estimated_tokens"] < measure(value)["estimated_tokens"]:
            if key == "content" and isinstance(value, list):
                block = next(
                    (
                        block
                        for block in value
                        if isinstance(block, dict)
                        and block.get("type") in {"input_text", "output_text"}
                        and isinstance(block.get("text"), str)
                    ),
                    None,
                )
                if block is not None:
                    replacement = {**block, "text": projected}
                    if "annotations" in replacement:
                        replacement["annotations"] = []
                    replacement.pop("logprobs", None)
                    item[key] = [replacement]
            else:
                item[key] = projected
                if (
                    key == "content"
                    and isinstance(value, str)
                    and value in history.checkpoint_messages
                ):
                    history.checkpoint_messages.add(projected)
    return result


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
                    dict.fromkeys(
                        text
                        for text in [complete_excerpt(child, limit), *passages]
                        if text
                    )
                )
            if isinstance(child, dict):
                result = {
                    key: project(text, (*path, key)) for key, text in child.items()
                }
                local = [item for item in self.fields if item.path[:-1] == path]
                serialized_body = isinstance(self.original, str) or (
                    len(path) >= 2
                    and isinstance(path[0], int)
                    and path[1] in {"content", "output"}
                    and isinstance(value[path[0]].get(path[1]), dict)
                )
                if (
                    local
                    and serialized_body
                    and child.get("type")
                    not in {
                        "message",
                        "input_text",
                        "output_text",
                        "function_call",
                        "function_call_output",
                    }
                ):
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
            if item.get("role") == "assistant" and assistant_fields and not isinstance(self.payload[index].get("content"), dict):
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
                    for block_index, block in enumerate(item.get("content", [])):
                        if isinstance(block, dict) and any(
                            field.path[:3] == (index, "content", block_index)
                            for field in assistant_fields
                        ):
                            if "annotations" in block:
                                block["annotations"] = []
                            block.pop("logprobs", None)
                    for block in item.get("content", []):
                        if isinstance(block, dict) and isinstance(
                            block.get("text"), str
                        ):
                            block["text"] += "\n" + notice
                            if "annotations" in block:
                                block["annotations"] = []
                            block.pop("logprobs", None)
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
    "search_plan",
    "query_plan",
    "owner_scope",
    "ownership",
    "objective",
    "saved_source_notes",
    "source_notes",
}


def plan_compaction(
    original: str | list[Any],
    history: ResearchHistory,
    preserve_fields: frozenset[str] = frozenset(),
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
                if isinstance(text, str) and text in history.checkpoint_messages:
                    continue
                registered = json.loads(
                    history.register(
                        "assistant_context", json.dumps({"content": text}), force=True
                    )
                )
                handle = registered.get("_research_view", {}).get("view_id")
                if handle:
                    plan.handles[index] = handle
                if isinstance(text, str):
                    try:
                        structured = json.loads(text)
                    except ValueError:
                        structured = None
                    if isinstance(structured, dict):
                        item[key] = structured
                        continue
                    if isinstance(structured, list):
                        continue
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
                            try:
                                json.loads(block["text"])
                            except ValueError:
                                pass
                            else:
                                continue
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
            if item.get("role") == "user" and stage_payload(text) is None:
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
            protected = protected or "segment_id" in value or "quote" in value
            for key, child in value.items():
                scan(
                    child,
                    (*path, key),
                    protected
                    or key in _PROTECTED
                    or key == "arguments"
                    or (
                        key in preserve_fields
                        and (
                            not path
                            if isinstance(original, str)
                            else len(path) == 2
                            and isinstance(path[0], int)
                            and path[1] == "content"
                            and payload[path[0]].get("role") == "user"
                        )
                    ),
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
            try:
                structured = json.loads(value)
            except ValueError:
                structured = None
            if isinstance(structured, (dict, list)):
                return
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
            ending = re.search(r"[.!?](?:\s|$)|\n", item.original[match.end() :])
            end = match.end() + ending.end() if ending else len(item.original)
            if end - start <= 400:
                plan.required_spans.append(ContextSpan(item.field_id, start, end))
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
