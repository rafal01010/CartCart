from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import Any
from uuid import uuid4

from agents import FunctionTool, function_tool
from pydantic import BaseModel

from app.agents.source_spans import source_span


def material_cautions(text: str) -> list[str]:
    return list(
        dict.fromkeys(
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?;])\s+|\n", text)
            if re.search(
                r"warranty|warn|risk|conflict|unverified|uncertain|sponsor|bias|"
                r"unsafe|counterfeit|import|no local|not available|regional|seller|"
                r"caution|gap|unsupported|untested|variant|incompatib|contradict",
                sentence,
                re.IGNORECASE,
            )
        )
    )


def bounded_cautions(
    text: str,
    *,
    max_count: int = 6,
    max_characters: int = 300,
    extra_passages: Sequence[str] = (),
) -> dict[str, Any]:
    originals = list(
        dict.fromkeys(
            [
                *material_cautions(text),
                *(
                    caution
                    for passage in extra_passages
                    for caution in (material_cautions(passage) or [passage])
                ),
            ]
        )
    )
    pattern = re.compile(
        r"warranty|warn|risk|conflict|unverified|uncertain|sponsor|bias|"
        r"unsafe|counterfeit|import|no local|not available|regional|seller|"
        r"caution|gap|unsupported|untested|variant|incompatib|contradict",
        re.IGNORECASE,
    )
    previews = []
    truncated = False
    for passage in originals[:max_count]:
        if len(passage) > max_characters:
            match = pattern.search(passage)
            start = max(0, (match.start() if match else 0) - max_characters // 4)
            passage = passage[start : start + max_characters]
            truncated = True
        previews.append(passage)
    deferred = max(0, len(originals) - max_count)
    terms = list(
        dict.fromkeys(match.group(0).casefold() for match in pattern.finditer(text))
    )
    terms.extend(
        passage[:80]
        for passage in extra_passages[:max_count]
        if not pattern.search(passage) and passage[:80] not in terms
    )
    return {
        "material_cautions": previews,
        **(
            {
                "deferred_caution_count": deferred,
                "cautions_truncated": truncated,
                "caution_focus_terms": terms,
                "unreviewed_cautions": True,
            }
            if deferred or truncated
            else {}
        ),
    }


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _support_state(payload: Any) -> dict[str, Any]:
    identities: dict[str, list[str]] = {}
    cautions: list[str] = []
    gaps: list[str] = []
    references: list[dict[str, Any]] = []
    deferred = 0
    truncated = False
    focus_terms: list[str] = []

    def visit(value: Any, key: str = "", *, in_gap: bool = False) -> None:
        nonlocal deferred, truncated
        in_gap = in_gap or "gap" in key
        if isinstance(value, dict):
            deferred += value.get("deferred_caution_count", 0)
            truncated |= bool(
                value.get("cautions_truncated") or value.get("unreviewed_cautions")
            )
            focus_terms.extend(value.get("caution_focus_terms", []))
            if any(name.endswith("_id") for name in value):
                reference = {
                    name: item
                    for name, item in value.items()
                    if (
                        name.endswith("_id")
                        or name
                        in {
                            "title",
                            "name",
                            "product_name",
                            "url",
                            "source_type",
                            "provider_source_type",
                            "content_sha256",
                            "official_url",
                            "country_code",
                            "marketplace_domain",
                            "marketplace_country_code",
                            "listing_url",
                            "product_title",
                            "variant_label",
                            "seller_name",
                            "seller_type",
                            "fulfilled_by",
                            "fulfillment",
                            "ships_to_region_code",
                            "ships_to_region",
                            "delivery_area",
                            "availability",
                            "product_code",
                            "asin",
                            "price",
                            "sponsorship_disclosed",
                            "affiliate_links_disclosed",
                            "sponsorship_notes",
                            "affiliate_bias_risk",
                            "summary",
                            "reason",
                        }
                    )
                    and item is not None
                }
                if (
                    any(not name.endswith("_id") for name in reference)
                    and reference not in references
                ):
                    references.append(reference)
            for name, item in value.items():
                visit(item, name, in_gap=in_gap)
        elif isinstance(value, list):
            for item in value:
                visit(item, key, in_gap=in_gap)
        elif isinstance(value, str):
            if key in {"caution_scope", "caution_focus_terms"}:
                return
            if key.endswith("_id") or key.endswith("_ids"):
                identities.setdefault(key, []).append(value)
            if any(
                word in key
                for word in (
                    "warning",
                    "caution",
                    "red_flag",
                    "bias_notes",
                    "sponsorship_notes",
                )
            ):
                cautions.append(value)
            elif in_gap and not key.endswith("_id") and not key.endswith("_ids"):
                gaps.append(value)
            elif key in {
                "text",
                "snippet",
                "description",
                "claim",
                "quote",
                "extracted_excerpt",
            }:
                cautions.extend(material_cautions(value))

    visit(payload)
    unique_cautions = list(dict.fromkeys(cautions))
    caution_state = bounded_cautions(
        "\n".join(unique_cautions), extra_passages=unique_cautions
    )
    previews = caution_state["material_cautions"]
    deferred += caution_state.get("deferred_caution_count", 0)
    truncated |= bool(caution_state.get("cautions_truncated"))
    return {
        "identities": {
            key: list(dict.fromkeys(vals))
            for key, vals in identities.items()
            if not all(
                any(identifier == row.get(key) for row in references)
                for identifier in vals
            )
        },
        **({"cautions": previews} if previews else {}),
        **(
            {
                "deferred_caution_count": deferred,
                "cautions_truncated": truncated,
                "caution_focus_terms": list(
                    dict.fromkeys(
                        [*focus_terms, *caution_state.get("caution_focus_terms", [])]
                    )
                ),
                "unreviewed_cautions": True,
            }
            if deferred or truncated
            else {}
        ),
        **({"gaps": list(dict.fromkeys(gaps))} if gaps else {}),
        "references": references,
        "coverage": "Original and omitted passages remain available. Cautions are advisory context for model judgment.",
    }


@dataclass
class ResearchView:
    tool: str
    original: str
    payload: Any
    state: dict[str, Any] | None = None
    receipts: set[str] = field(default_factory=set)


def native_item_key(item: dict[str, Any]) -> str:
    if item.get("type") == "function_call" and item.get("call_id"):
        return "call:" + str(item["call_id"])
    if item.get("id"):
        return "item:" + str(item["id"])
    return (
        "content:"
        + sha256(
            json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    )


@dataclass
class ResearchHistory:
    scope_id: str = field(default_factory=lambda: uuid4().hex)
    views: dict[str, ResearchView] = field(default_factory=dict)
    projections: dict[str, str] = field(default_factory=dict)
    compacted_sources: set[str] = field(default_factory=set)
    transported_text: dict[str, list[str]] = field(default_factory=dict)
    native_response_groups: list[tuple[str, ...]] = field(default_factory=list)
    checkpoint_messages: set[str] = field(default_factory=set)

    def record_response(self, items: Sequence[Any]) -> None:
        group = tuple(
            native_item_key(
                item.model_dump(exclude_unset=True)
                if isinstance(item, BaseModel)
                else item
            )
            for item in items
        )
        if group and group not in self.native_response_groups:
            self.native_response_groups.append(group)

    def archive(self, tool: str, payload: Any) -> str:
        original = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        digest = sha256((tool + original).encode()).hexdigest()
        view_id = self.scope_id[:12] + ":" + digest[:20]
        self.views.setdefault(
            view_id, ResearchView(tool, original, json.loads(original))
        )
        return view_id

    def checkpoint(self, view_id: str, *, characters: int = 6000) -> dict[str, Any]:
        view = self.views[view_id]
        payload = view.payload

        def decode(value: Any, key: str = "") -> Any:
            if isinstance(value, str) and key in {"output", "arguments", "content"}:
                try:
                    return decode(json.loads(value))
                except ValueError:
                    return value
            if isinstance(value, dict):
                return {name: decode(child, name) for name, child in value.items()}
            if isinstance(value, list):
                return [decode(child) for child in value]
            return value

        decoded = decode(payload)
        support = _support_state(decoded)
        result: dict[str, Any] = {
            "derived_context": True,
            "original_view_id": view_id,
            "original_characters": len(view.original),
            "omitted_material_unreviewed": True,
            "unreviewed_cautions": True,
            "coverage": "Saved originals remain available through read_research_result. Retained notes and cautions inform the owner model.",
        }
        quotes: list[dict[str, Any]] = []
        source_notes: list[dict[str, Any]] = []
        model_notes: list[dict[str, Any]] = []
        excerpt_limit = max(120, min(700, characters // 6))

        for handle, original in reversed(tuple(self.views.items())):
            facts = (original.state or {}).get("facts", ())
            for fact in facts:
                note = {"view_id": handle, "facts_are_model_notes": True, "fact": fact}
                if note not in model_notes:
                    model_notes.append(note)

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                for note in value.get("model_notes", ()):
                    if isinstance(note, dict) and note not in model_notes:
                        model_notes.append(note)
                if isinstance(value.get("view_id"), str):
                    facts = value.get("facts", value.get("retained", {}).get("facts", ()))
                    for fact in facts:
                        if isinstance(fact, str):
                            note = {"view_id": value["view_id"], "facts_are_model_notes": True, "fact": fact}
                            if note not in model_notes:
                                model_notes.append(note)
                for field, kind in (
                    ("source_excerpt", value.get("kind", "source_note")),
                    ("text", "page_excerpt"),
                    ("snippet", "search_snippet"),
                ):
                    text = value.get(field)
                    if not isinstance(text, str) or not text.strip():
                        continue
                    if not any(
                        value.get(key) for key in ("source_id", "snapshot_id", "url")
                    ):
                        continue
                    text = " ".join(text.split())
                    note = {
                        **{
                            key: value[key]
                            for key in (
                                "source_id",
                                "snapshot_id",
                                "url",
                                "title",
                                "published_date",
                            )
                            if value.get(key) is not None
                        },
                        "kind": kind,
                        "source_excerpt": text[:excerpt_limit],
                        "truncated": bool(
                            value.get("truncated")
                            or value.get("text_truncated")
                            or value.get("snippet_truncated")
                            or len(text) > excerpt_limit
                        ),
                    }
                    if note not in source_notes:
                        source_notes.append(note)
                if value.get("status") == "succeeded" and isinstance(
                    value.get("quote"), str
                ):
                    quotes.append(
                        {
                            key: child
                            for key, child in value.items()
                            if key.endswith("_id")
                            or key in {"status", "quote", "claim"}
                        }
                    )
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(decoded)
        identities = [
            {"kind": key, "id": identity}
            for key, values in support["identities"].items()
            for identity in values
        ]
        identities.extend(
            {"kind": key, "id": identity}
            for row in support["references"]
            for key, identity in row.items()
            if key.endswith("_id")
        )
        for key, rows in (
            ("recorded_quotes", reversed(quotes)),
            ("model_notes", model_notes),
            ("cautions", support.get("cautions", [])),
            (
                "source_notes",
                sorted(source_notes, key=lambda note: note["kind"] != "page_excerpt"),
            ),
            ("identities", identities),
            ("references", reversed(support.get("references", []))),
            ("gaps", support.get("gaps", [])),
        ):
            retained: list[Any] = []
            result[key] = retained
            for row in rows:
                if len(retained) >= 12:
                    break
                retained.append(row)
                if (
                    len(json.dumps(result, ensure_ascii=False)) > characters
                    or key == "model_notes"
                    and len(json.dumps(retained, ensure_ascii=False)) > characters // 3
                ):
                    retained.pop()
        return result

    def source_text(self, items: Any) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}

        def visit(value: Any, source_ids: tuple[str, ...] = ()) -> None:
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    return
            if isinstance(value, dict):
                if (
                    value.get("type") == "function_call"
                    or value.get("role") == "assistant"
                ):
                    return
                source_ids = (
                    tuple(
                        str(value[key])
                        for key in ("source_id", "snapshot_id")
                        if value.get(key) is not None
                    )
                    or source_ids
                )
                if source_ids and isinstance(value.get("text"), str):
                    for source_id in source_ids:
                        result.setdefault(source_id, []).append(value["text"])
                for key, child in value.items():
                    if key not in {
                        "_context_projection",
                        "material_cautions",
                        "cautions",
                        "_research_view",
                    }:
                        visit(child, source_ids)
            elif isinstance(value, list):
                for child in value:
                    visit(child, source_ids)

        visit(items)
        return result

    def record_transport(self, items: Any, *, originals: Any = None) -> None:
        if originals is not None:
            original_text = self.source_text(originals)
            transported_text = self.source_text(items)
            self.compacted_sources.update(
                source_id
                for source_id, texts in original_text.items()
                if texts != transported_text.get(source_id, [])
            )
            if isinstance(originals, list) and isinstance(items, list):
                outputs = {
                    str(item.get("call_id")): item.get("output")
                    for item in items
                    if item.get("type") == "function_call_output"
                }
                for item in originals:
                    original = item.get("output")
                    projected = outputs.get(str(item.get("call_id")))
                    if (
                        item.get("type") == "function_call_output"
                        and isinstance(original, str)
                        and isinstance(projected, str)
                        and len(projected) < len(original)
                    ):
                        self.projections[original] = projected
        for source_id, texts in self.source_text(items).items():
            observed = self.transported_text.setdefault(source_id, [])
            observed.extend(text for text in texts if text not in observed)

    def register(
        self, tool: str, output: str, *, force: bool = False, fresh: bool = False
    ) -> str:
        try:
            payload = json.loads(output)
        except (ValueError, TypeError):
            return output
        if not isinstance(payload, dict) or (len(output) < 900 and not force):
            return output
        if not force and payload.get("status") in {
            "failed",
            "budget_exhausted",
            "invalid_request",
        }:
            return output
        original = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        digest = sha256((tool + original).encode()).hexdigest()
        view_id = self.scope_id[:12] + ":" + digest[:20]
        view = self.views.setdefault(view_id, ResearchView(tool, original, payload))
        if view.state is not None and not fresh:
            retired = self.retired(view_id)
            if retired is not None and len(retired) < len(original):
                return retired
        return json.dumps(
            {**payload, "_research_view": {"view_id": view_id, "tool": tool}},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def complete(self, view_id: str, retained_facts: list[str]) -> dict[str, Any]:
        view = self.views.get(view_id)
        if view is None:
            return {
                "status": "unknown_view",
                "gap": "Original is unavailable in this shopping invocation.",
            }
        if not 1 <= len(retained_facts) <= 12 or any(
            not fact.strip() or len(fact) > 400 for fact in retained_facts
        ):
            return {
                "status": "invalid_request",
                "gap": "Retained notes must be 1 to 12 nonblank passages, each at most 400 characters.",
            }
        facts = list(
            dict.fromkeys([*(view.state or {}).get("facts", []), *retained_facts])
        )
        view.state = {
            "facts": facts,
            "facts_are_model_notes": True,
            **_support_state(view.payload),
        }
        return {
            "status": "processed",
            "view_id": view_id,
            "facts": facts,
            "coverage": "Other original support remains retrievable and unreviewed.",
        }

    def retired(self, view_id: str) -> str | None:
        view = self.views.get(view_id)
        if view is None or view.state is None:
            return None
        output = json.dumps(
            {
                "status": "processed",
                "view_id": view_id,
                "tool": view.tool,
                "retained": view.state,
                "original_characters": len(view.original),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        view.receipts.add(output)
        return output

    def read(
        self, view_id: str, *, start_char: int = 0, focus: str | None = None
    ) -> dict[str, Any]:
        view = self.views.get(view_id)
        if view is None:
            return {
                "status": "unknown_view",
                "gap": "Original is unavailable in this shopping invocation.",
            }
        payload = view.payload
        if view.tool == "sdk_exchanges":

            def decode_outputs(value: Any) -> Any:
                if isinstance(value, dict):
                    result = {
                        key: decode_outputs(child) for key, child in value.items()
                    }
                    if value.get("type") == "function_call_output" and isinstance(
                        value.get("output"), str
                    ):
                        try:
                            result["output"] = json.loads(value["output"])
                        except ValueError:
                            pass
                    return result
                if isinstance(value, list):
                    return [decode_outputs(child) for child in value]
                return value

            payload = decode_outputs(payload)
        readable = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            encoded_focus = (
                json.dumps(focus, ensure_ascii=False)[1:-1]
                if focus is not None
                else None
            )
            span = source_span(
                readable, start=start_char, focus=encoded_focus, limit=2000
            )
        except ValueError as exc:
            return {"status": "invalid_request", "gap": str(exc)}
        source_spans = self._read_source_spans(
            view, span.start, span.start + len(span.text), payload=payload
        )
        return {
            "status": "succeeded",
            "view_id": view_id,
            "tool": view.tool,
            "text": span.text,
            "start_char": span.start,
            "total_characters": span.total_characters,
            "content_sha256": span.content_sha256,
            **(
                {
                    "serialized_sdk_outputs_decoded": True,
                    "original_content_sha256": sha256(
                        view.original.encode()
                    ).hexdigest(),
                    "original_characters": len(view.original),
                }
                if view.tool == "sdk_exchanges"
                else {}
            ),
            **({"source_spans": source_spans} if source_spans else {}),
            "text_truncated": span.start > 0
            or span.start + len(span.text) < span.total_characters,
            "coverage": "This reread is new and unprocessed. Omitted passages remain unreviewed.",
        }

    def _read_source_spans(
        self, view: ResearchView, start: int, end: int, *, payload: Any = None
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        cursor = 0

        def walk(
            value: Any, source_ids: dict[str, str], key: str = "", support: bool = True
        ) -> None:
            nonlocal cursor
            if isinstance(value, dict):
                source_ids = {
                    name: str(value[name])
                    for name in ("source_id", "snapshot_id")
                    if value.get(name) is not None
                } or source_ids
                cursor += 1
                for index, (name, child) in enumerate(value.items()):
                    cursor += (
                        bool(index) + len(json.dumps(name, ensure_ascii=False)) + 1
                    )
                    walk(
                        child,
                        source_ids,
                        name,
                        support
                        and name
                        not in {
                            "_context_projection",
                            "material_cautions",
                            "cautions",
                            "_research_view",
                        },
                    )
                cursor += 1
            elif isinstance(value, list):
                cursor += 1
                for index, child in enumerate(value):
                    cursor += bool(index)
                    walk(child, source_ids, key, support)
                cursor += 1
            else:
                encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                if support and key == "text" and isinstance(value, str) and source_ids:
                    position = cursor + 1
                    first = last = None
                    for offset, character in enumerate(value):
                        width = len(json.dumps(character, ensure_ascii=False)) - 2
                        if start <= position and position + width <= end:
                            if first is None:
                                first = offset
                            last = offset + 1
                        position += width
                        if position > end:
                            break
                    if first is not None and last is not None:
                        result.append(
                            {
                                **source_ids,
                                "text": value[first:last],
                                "start_char": first,
                            }
                        )
                cursor += len(encoded)

        walk(view.payload if payload is None else payload, {})
        return result


_history: ContextVar[ResearchHistory | None] = ContextVar(
    "shopping_research_history", default=None
)


@contextmanager
def history_scope(*, fresh: bool = False):
    if _history.get() is not None and not fresh:
        yield _history.get()
        return
    token = _history.set(ResearchHistory())
    try:
        yield _history.get()
    finally:
        _history.reset(token)


def active_history() -> ResearchHistory | None:
    return _history.get()


def retired_output(output: str) -> str:
    history = _history.get()
    if history is None:
        return output
    automatic = history.projections.get(output, output)
    try:
        payload = json.loads(output)
    except ValueError:
        return automatic
    if not isinstance(payload, dict):
        return automatic
    if isinstance(payload.get("view_id"), str):
        view_id = payload["view_id"]
        view = history.views.get(view_id)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if view is not None and encoded in view.receipts:
            return history.retired(view_id) or automatic
    reference = payload.get("_research_view", {})
    if not isinstance(reference, dict):
        return automatic
    view_id = reference.get("view_id", "")
    view = history.views.get(view_id)
    if (
        view is None
        or {key: value for key, value in payload.items() if key != "_research_view"}
        != view.payload
    ):
        return automatic
    retired = history.retired(view_id)
    if retired is not None:
        return retired if len(retired) < len(output) else output
    return automatic


def processed_view_id(output: str) -> str | None:
    history = _history.get()
    if history is None:
        return None
    try:
        payload = json.loads(output)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    view_id = payload.get("view_id")
    view = history.views.get(view_id) if isinstance(view_id, str) else None
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return view_id if view is not None and encoded in view.receipts else None


def history_tools() -> tuple[FunctionTool, FunctionTool]:
    @function_tool
    async def complete_research_result(view_id: str, retained_facts: list[str]) -> str:
        """After interpreting a result, retain useful notes before retiring its bulk.

        Keep snippets and page text labeled. These notes may paraphrase the original.
        Unreviewed original passages cannot establish safety. Keep conflicts and gaps.
        """
        history = _history.get()
        return json.dumps(
            history.complete(view_id, retained_facts)
            if history
            else {"status": "unknown_view"},
            ensure_ascii=False,
        )

    @function_tool
    async def read_research_result(
        view_id: str, start_char: int = 0, focus: str | None = None
    ) -> str:
        """Reread a bounded original tool view from this invocation. Use source tools for full pages."""
        history = _history.get()
        output = json.dumps(
            history.read(view_id, start_char=start_char, focus=focus)
            if history
            else {"status": "unknown_view"},
            ensure_ascii=False,
        )
        return (
            history.register("read_research_result", output, fresh=True)
            if history
            else output
        )

    return complete_research_result, read_research_result


def tracked_tools(
    tools: Sequence[FunctionTool], *, include_controls: bool = True
) -> tuple[FunctionTool, ...]:
    result = []
    for tool in tools:
        callback = tool.on_invoke_tool
        name = tool.name

        async def invoke(context: Any, arguments: str, *, callback=callback, name=name):
            output = await callback(context, arguments)
            history = _history.get()
            return (
                history.register(
                    name,
                    output,
                    fresh=name
                    in {
                        "fetch_source",
                        "read_source_snapshot",
                        "read_run_evidence",
                        "read_research_result",
                        "read_video_transcript",
                        "read_community_discussion",
                    },
                )
                if history and isinstance(output, str)
                else output
            )

        result.append(replace(tool, on_invoke_tool=invoke))
    if include_controls:
        result.extend(history_tools())
    return tuple(result)
