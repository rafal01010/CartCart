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

from app.agents.source_spans import source_span


def material_cautions(text: str) -> list[str]:
    return list(
        dict.fromkeys(
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?;])\s+|\n", text)
            if re.search(
                r"warranty|warn|risk|conflict|unverified|uncertain|sponsor|bias|"
                r"unsafe|counterfeit|import|no local|not available|regional|seller|"
                r"caution|gap|unsupported|untested",
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
        r"caution|gap|unsupported|untested",
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
        "coverage": "Other original or omitted passages remain unreviewed. Reread before safety claims.",
    }


class ResearchCoverageError(RuntimeError):
    pass


@dataclass
class ResearchView:
    tool: str
    original: str
    payload: Any
    state: dict[str, Any] | None = None
    receipts: set[str] = field(default_factory=set)


@dataclass
class ResearchHistory:
    scope_id: str = field(default_factory=lambda: uuid4().hex)
    views: dict[str, ResearchView] = field(default_factory=dict)

    def unjustified_safety_claims(
        self, text: str, quotes: Sequence[str], source_ids: Sequence[str]
    ) -> tuple[str, ...]:
        relevant = []
        selected_ids = set(source_ids)

        def scoped(value: Any) -> None:
            if isinstance(value, dict):
                if any(
                    str(value.get(key)) in selected_ids
                    for key in ("source_id", "snapshot_id")
                ):
                    relevant.append(_support_state(value))
                    return
                for child in value.values():
                    scoped(child)
            elif isinstance(value, list):
                for child in value:
                    scoped(child)

        for view in self.views.values():
            scoped(view.payload)
        if not relevant:
            return ()
        broad = re.compile(
            r"\b(?:safe to buy|(?:seller|listing) (?:is )?(?:safe|legitimate|trusted|verified)|"
            r"(?:fully|completely) (?:safe|checked|verified)|"
            r"no (?:hidden )?(?:risks?|warnings?|cautions?|conflicts?|warranty issues?)|"
            r"(?:reputable|legitimate|trusted|verified|authentic|genuine) (?:seller|listing|offer)|"
            r"(?:seller|listing|offer|product) (?:is )?(?:reputable|authentic|genuine|low[- ]risk)|"
            r"(?:buy|purchase) (?:confidently|with confidence)|confident purchase)\b",
            re.IGNORECASE,
        )
        warranty = re.compile(
            r"\b(?:(?:includes?|has|provides?|offers?|with) (?:a |full |valid )?local warranty|"
            r"local warranty (?:is )?(?:included|available|valid|confirmed|covered))\b",
            re.IGNORECASE,
        )
        unsupported = []
        for sentence in re.split(r"(?<=[.!?;])\s+|\n", text):
            if re.match(
                r"^(?:check\s+)?whether\s+(?:this |the )?(?:product|seller|listing|offer)\s+is\s+(?:safe to buy|legitimate|trusted|verified|reputable|authentic|genuine)[.?!]?$",
                sentence.strip(),
                re.IGNORECASE,
            ):
                continue
            sentence = re.sub(
                r"\b(?:not|never)\s+(?:safe to buy|(?:fully|completely) (?:safe|checked|verified))|"
                r"\b(?:check|whether)\s+(?:the\s+)?(?:seller|listing|local warranty)|"
                r"\b(?:may|might|could)\s+(?:be\s+)?(?:safe to buy|legitimate|trusted|verified)",
                "qualified",
                sentence,
                flags=re.IGNORECASE,
            )
            if broad.search(sentence):
                unsupported.append(sentence)
            elif warranty.search(sentence):
                claim = warranty.search(sentence)
                assert claim is not None
                exact_support = any(
                    claim.group(0).casefold() in quote.casefold() for quote in quotes
                )
                deferred_warranty = any(
                    state.get("unreviewed_cautions")
                    and "warranty" in state.get("caution_focus_terms", [])
                    for state in relevant
                )
                conflicting_warranty = any(
                    re.search(
                        r"no local warranty|warranty.*(?:conflict|uncertain|unverified|not covered)|(?:conflict|uncertain|unverified).*warranty",
                        caution,
                        re.IGNORECASE,
                    )
                    for state in relevant
                    for caution in state.get("cautions", [])
                )
                if not exact_support or deferred_warranty or conflicting_warranty:
                    unsupported.append(sentence)
        return tuple(unsupported)

    def register(self, tool: str, output: str) -> str:
        try:
            payload = json.loads(output)
        except (ValueError, TypeError):
            return output
        if not isinstance(payload, dict) or len(output) < 900:
            return output
        if payload.get("status") in {"failed", "budget_exhausted", "invalid_request"}:
            return output
        original = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        digest = sha256((tool + original).encode()).hexdigest()
        view_id = self.scope_id[:12] + ":" + digest[:20]
        view = self.views.setdefault(view_id, ResearchView(tool, original, payload))
        if view.state is not None:
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
        originals = tuple(_strings(view.payload))
        if (
            not 1 <= len(retained_facts) <= 12
            or any(not fact.strip() or len(fact) > 400 for fact in retained_facts)
            or any(
                not any(fact in text for text in originals) for fact in retained_facts
            )
        ):
            return {
                "status": "invalid_request",
                "gap": "Retained facts must be 1 to 12 exact original passages, each at most 400 characters.",
            }
        facts = list(
            dict.fromkeys([*(view.state or {}).get("facts", []), *retained_facts])
        )
        view.state = {"facts": facts, **_support_state(view.payload)}
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
        try:
            span = source_span(view.original, start=start_char, focus=focus, limit=2000)
        except ValueError as exc:
            return {"status": "invalid_request", "gap": str(exc)}
        return {
            "status": "succeeded",
            "view_id": view_id,
            "tool": view.tool,
            "text": span.text,
            "start_char": span.start,
            "total_characters": span.total_characters,
            "content_sha256": span.content_sha256,
            "text_truncated": span.start > 0
            or span.start + len(span.text) < span.total_characters,
            "coverage": "This reread is new and unprocessed. Omitted passages remain unreviewed.",
        }


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
    try:
        payload = json.loads(output)
    except ValueError:
        return output
    if not isinstance(payload, dict):
        return output
    if isinstance(payload.get("view_id"), str):
        view_id = payload["view_id"]
        view = history.views.get(view_id)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if view is not None and encoded in view.receipts:
            return history.retired(view_id) or output
    reference = payload.get("_research_view", {})
    if not isinstance(reference, dict):
        return output
    view_id = reference.get("view_id", "")
    view = history.views.get(view_id)
    if (
        view is None
        or {key: value for key, value in payload.items() if key != "_research_view"}
        != view.payload
    ):
        return output
    retired = history.retired(view_id)
    return retired if retired is not None and len(retired) < len(output) else output


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
        """After interpreting a result, retain exact useful passages before retiring its bulk.

        Snippets remain unverified leads. Record page quotes for factual decisions.
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
        return history.register("read_research_result", output) if history else output

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
                history.register(name, output)
                if history and isinstance(output, str)
                else output
            )

        result.append(replace(tool, on_invoke_tool=invoke))
    if include_controls:
        result.extend(history_tools())
    return tuple(result)
