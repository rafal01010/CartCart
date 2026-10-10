"""Bound model inputs and spending at the SDK transport boundary.

Canonical evidence remains in SQLite. This module never creates scratch files,
rewrites factual claims, or counts the SDK's nested aggregate usage a second time.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from functools import wraps
from hashlib import sha256
from math import ceil
from typing import Any, ParamSpec, TypeVar
from urllib.parse import urlsplit

from agents import Agent, ModelSettings, RunConfig, Runner
from agents.agent_output import AgentOutputSchemaBase
from agents.handoffs import Handoff
from agents.items import ModelResponse, TResponseInputItem, TResponseStreamEvent
from agents.models.interface import Model, ModelProvider, ModelTracing
from agents.retry import ModelRetryAdvice, ModelRetryAdviceRequest
from agents.run_config import CallModelData, ModelInputData
from agents.tool import FunctionTool, Tool
from openai.types.responses import (
    ResponseFunctionToolCall,
)
from openai.types.responses.response_prompt_param import ResponsePromptParam
from pydantic import BaseModel

from app.agents.context_metrics import input_breakdown, measure
from app.agents.research_history import (
    active_history,
    history_scope,
    history_tools,
    processed_view_id,
    retired_output,
)
from app.agents.request_compaction import (
    bound_original_views,
    compact_to_tokens,
    essential_input,
    plan_compaction,
    preserve_stage_fields,
    rotate_exchanges,
    restore_source_views,
)


CONTEXT_RESEARCH_LIMITATION = (
    "Research was limited because the available material was too large to review fully."
)


class ContextBudgetExceeded(RuntimeError):
    """A safe continuation is impossible; this is not a buying judgment."""


def context_budget_failure(error: BaseException) -> ContextBudgetExceeded | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ContextBudgetExceeded):
            return current
        current = current.__cause__ or current.__context__
    return None


@dataclass(frozen=True)
class ContextLimits:
    input_tokens: int = 19_000
    total_tokens: int = 150_000
    decision_reserve: int = 24_000
    verification_reserve: int = 24_000
    hosted_reserve: int = 8_000
    output_tokens: int = 5_000


@dataclass
class ContextBudget:
    limits: ContextLimits = field(default_factory=ContextLimits)
    spent: int = 0
    reserved: int = 0
    exhausted: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    call_owners: dict[tuple[str, str, str], str] = field(default_factory=dict)
    capture_calls: dict[tuple[str, tuple[int, ...]], int] = field(default_factory=dict)
    capture_fetches: dict[tuple[str, tuple[int, ...]], int] = field(
        default_factory=dict
    )
    capture_sources: dict[tuple[str, tuple[int, ...]], set[str]] = field(
        default_factory=dict
    )

    def reserve(self, estimated: int, *, agent: str) -> int:
        if (
            self.exhausted
            or self.spent + self.reserved + estimated > self.limits.total_tokens
        ):
            self.exhausted = True
            raise ContextBudgetExceeded(
                "Shared shopping token budget cannot safely fund another call."
            )
        self.reserved += estimated
        return estimated

    def settle(self, reservation: int, actual: int | None) -> None:
        self.reserved -= reservation
        # Unknown/failed requests keep the entire reservation. No free retries.
        self.spent += actual if actual is not None else reservation
        if self.spent + self.reserved > self.limits.total_tokens:
            self.exhausted = True
            raise ContextBudgetExceeded(
                "Actual shopping usage exceeded its reserved budget."
            )


_budget: ContextVar[ContextBudget | None] = ContextVar(
    "shopping_context_budget", default=None
)
_agent: ContextVar[str] = ContextVar("shopping_context_agent", default="unknown")
_stage: ContextVar[str] = ContextVar("shopping_context_stage", default="standalone")
_before_size: ContextVar[dict[str, int] | None] = ContextVar(
    "shopping_context_before", default=None
)
_allowances: ContextVar[tuple[ContextBudget, ...]] = ContextVar(
    "shopping_context_allowances", default=()
)


@contextmanager
def context_scope(budget: ContextBudget | None = None):
    current = _budget.get()
    if current is not None and (budget is None or budget is current):
        yield current
        return
    token = _budget.set(budget or ContextBudget())
    stage_token = _stage.set("standalone")
    agent_token = _agent.set("unknown")
    size_token = _before_size.set(None)
    allowance_token = _allowances.set(())
    try:
        with history_scope(fresh=True):
            yield _budget.get()
    finally:
        _budget.reset(token)
        _stage.reset(stage_token)
        _agent.reset(agent_token)
        _before_size.reset(size_token)
        _allowances.reset(allowance_token)


def active_budget() -> ContextBudget | None:
    return _budget.get()


def context_events(start: int) -> tuple[dict[str, Any], ...]:
    current = _budget.get()
    return tuple(current.events[start:]) if current else ()


def set_context_stage(stage: str) -> None:
    _stage.set(stage)


P = ParamSpec("P")
R = TypeVar("R")


def managed_context(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with context_scope(ContextBudget()):
            return await function(*args, **kwargs)

    return wrapped


def managed_source_context(
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    return _managed_allowance(function, 30_000)


def managed_owner_context(
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    return _managed_allowance(function, 90_000)


def _managed_allowance(
    function: Callable[P, Awaitable[R]], total: int
) -> Callable[P, Awaitable[R]]:
    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with context_scope():
            allowance = ContextBudget(limits=ContextLimits(total_tokens=total))
            token = _allowances.set((*_allowances.get(), allowance))
            try:
                return await function(*args, **kwargs)
            finally:
                _allowances.reset(token)

    return wrapped


def compact_json(text: str) -> str:
    """Remove JSON whitespace and identical list records, preserving every value."""
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return text
    record_fields = {
        "products",
        "listings",
        "evidence",
        "source_evidence",
        "category_analyses",
        "trust_assessments",
        "deduplication_decisions",
        "user_added_products",
        "source_snapshots",
    }
    identity_fields = {
        "product_id",
        "listing_id",
        "evidence_id",
        "candidate_id",
        "decision_id",
        "source_id",
    }

    def dedupe(value: Any, field_name: str = "") -> Any:
        if isinstance(value, dict):
            return {key: dedupe(item, key) for key, item in value.items()}
        if isinstance(value, list):
            # Only identical structured records. Scalar order/repetitions may be meaningful.
            seen: set[str] = set()
            result = []
            for item in value:
                item = dedupe(item)
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                record = (
                    isinstance(item, dict)
                    and field_name in record_fields
                    and identity_fields.intersection(item)
                )
                if record and key in seen:
                    continue
                seen.add(key)
                result.append(item)
            return result
        return value

    return json.dumps(dedupe(payload), ensure_ascii=False, separators=(",", ":"))


def source_bundle_context(bundle: BaseModel) -> dict[str, Any]:
    """Expose validated exact claims and provenance, leaving raw support canonical."""
    payload = bundle.model_dump(mode="json")
    deferred = []
    if "transcript_segments" in payload:
        payload.pop("transcript_segments")
        deferred.append("transcript_segments")
    for discussion in payload.get("discussions", []):
        if "extracted_public_summary" in discussion:
            discussion.pop("extracted_public_summary")
            discussion["text_deferred"] = True
    if "discussions" in payload:
        deferred.append("discussions.extracted_public_summary")
    if deferred:
        payload["deferred_fields"] = deferred
    return payload


def prepare_history(items: list[TResponseInputItem]) -> list[TResponseInputItem]:
    """Retain all call pairs, handoffs, arguments, quotes, warnings and exact brief.

    Defer only fully quoted bodies or byte-identical repeated reads. Partial
    quotes cannot authorize dropping the rest of a read. The most recent
    duplicate remains exact, and every distinct unprocessed passage survives.
    Explicit processing can replace canonical tool views with exact retained
    facts, cautions and unresolved coverage plus bounded original lookup.
    """
    calls = {
        item.get("call_id"): item.get("name")
        for item in items
        if item.get("type") == "function_call"
    }
    reads = [
        index
        for index, item in enumerate(items)
        if item.get("type") == "function_call_output"
        and calls.get(item.get("call_id"))
        in {
            "fetch_source",
            "read_source_snapshot",
            "read_run_evidence",
            "read_research_result",
            "read_video_transcript",
            "read_community_discussion",
        }
    ]
    quoted_sources: dict[Any, list[tuple[int, str]]] = {}
    latest_reads: dict[str, int] = {}
    duplicate_reads: dict[int, str] = {}
    payloads: dict[int, dict[str, Any]] = {}
    for position, item in enumerate(items):
        output = item.get("output")
        if item.get("type") != "function_call_output" or not isinstance(output, str):
            continue
        try:
            payload = json.loads(output)
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        if calls.get(item.get("call_id")) == "record_source_quote":
            quote = payload.get("quote")
            if payload.get("status") == "succeeded" and isinstance(quote, str):
                quoted_sources.setdefault(payload.get("source_id"), []).append(
                    (position, quote)
                )
        if position in reads:
            payloads[position] = payload
            identity = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            key = str(calls.get(item.get("call_id"))) + identity
            if key in latest_reads:
                duplicate_reads[latest_reads[key]] = str(item.get("call_id"))
            latest_reads[key] = position
    result = []
    retained_views: set[str] = set()
    for index, original in enumerate(items):
        projected: Any = dict(original)
        if projected.get("type") == "function_call_output" and isinstance(
            projected.get("output"), str
        ):
            retired = (
                projected["output"]
                if index in reads
                else retired_output(projected["output"])
            )
            view_id = processed_view_id(retired)
            if view_id in retained_views:
                retired = json.dumps(
                    {"status": "processed_unchanged", "view_id": view_id},
                    separators=(",", ":"),
                )
            elif view_id is not None:
                retained_views.add(view_id)
            payload = payloads.get(index) if retired == projected["output"] else None
            projected["output"] = retired
            if payload is not None:
                bodies = [payload]
                bodies.extend(payload.get("segments", []))
                if isinstance(payload.get("discussion"), dict):
                    bodies.append(payload["discussion"])
                for body in bodies:
                    if not isinstance(body, dict):
                        continue
                    key = "text" if "text" in body else "extracted_public_summary"
                    text = body.get(key)
                    if not isinstance(text, str) or not text:
                        continue
                    fully_quoted = any(
                        position > index and quote == text
                        for position, quote in quoted_sources.get(
                            payload.get("source_id"), []
                        )
                    )
                    if not fully_quoted and index not in duplicate_reads:
                        continue
                    body.pop(key)
                    body["deferred_text"] = {
                        "sha256": sha256(text.encode()).hexdigest(),
                        "characters": len(text),
                        "tool": calls[projected["call_id"]],
                        "retained_call_id": duplicate_reads.get(index),
                    }
                projected["output"] = json.dumps(payload)
            projected["output"] = compact_json(projected["output"])
        elif projected.get("role") == "user" and isinstance(
            projected.get("content"), str
        ):
            projected["content"] = compact_json(projected["content"])
        elif projected.get("type") == "function_call" and isinstance(
            projected.get("arguments"), str
        ):
            projected["arguments"] = compact_json(projected["arguments"])
        result.append(projected)
    return result


def filter_input(data: CallModelData[Any]) -> ModelInputData:
    if isinstance(data.agent.model, Model):
        raise ValueError("Shopping models must resolve through the bounded provider.")
    _agent.set(data.agent.name)
    _before_size.set(measure(data.model_data.input))
    return ModelInputData(
        input=data.model_data.input,
        instructions=data.model_data.instructions,
    )


def _schema_payload(
    tools: list[Tool], output: AgentOutputSchemaBase | None, handoffs: list[Handoff]
) -> dict[str, Any]:
    return {
        "output": output.json_schema() if output else {},
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.params_json_schema,
            }
            if isinstance(tool, FunctionTool)
            else {"type": tool.name}
            for tool in tools
        ],
        "handoffs": [
            {
                "name": item.tool_name,
                "description": item.tool_description,
                "parameters": item.input_json_schema,
            }
            for item in handoffs
        ],
    }


def _source_state(
    items: str | list[TResponseInputItem],
) -> tuple[dict[str, str], set[str], set[str]]:
    domains: dict[str, str] = {}
    quoted: set[str] = set()
    fetched: set[str] = set()
    if isinstance(items, str):
        return domains, quoted, fetched
    calls = {
        item.get("call_id"): item
        for item in items
        if item.get("type") == "function_call"
    }

    def sources(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("url"), str):
                domain = (urlsplit(value["url"]).hostname or "").removeprefix("www.")
                for key in ("source_id",):
                    if domain and value.get(key) is not None:
                        domains[str(value[key])] = domain
            for child in value.values():
                sources(child)
        elif isinstance(value, list):
            for child in value:
                sources(child)

    for item in items:
        body = item.get("output", item.get("content"))
        if not isinstance(body, str):
            continue
        try:
            payload = json.loads(body)
        except ValueError:
            continue
        sources(payload)
        call = calls.get(item.get("call_id"), {})
        if call.get("name") == "fetch_source":
            try:
                arguments = json.loads(call.get("arguments", "{}"))
            except ValueError:
                arguments = {}
            if arguments.get("source_id") is not None:
                fetched.add(str(arguments["source_id"]))
        if (
            call.get("name") == "record_source_quote"
            and isinstance(payload, dict)
            and payload.get("status") == "succeeded"
            and payload.get("source_id") is not None
        ):
            quoted.add(str(payload["source_id"]))
    return domains, quoted, fetched


def _quote_sources(
    items: Any, domains: dict[str, str], quoted_domains: set[str]
) -> set[str]:
    history = active_history()
    text = history.source_text(items) if history else {}
    return {
        source_id
        for source_id, spans in text.items()
        if source_id in domains
        and domains[source_id] not in quoted_domains
        and any(span.strip() for span in spans)
    }


def _source_choices(tool: Tool, source_ids: set[str]) -> Tool:
    if not isinstance(tool, FunctionTool) or not source_ids:
        return tool
    schema = json.loads(json.dumps(tool.params_json_schema))
    field = schema.get("properties", {}).get("source_id")
    if isinstance(field, dict):
        field["enum"] = sorted(source_ids)
    return replace(tool, params_json_schema=schema)


class BudgetedModel(Model):
    def __init__(self, model: Model, budget: ContextBudget, model_name: str | None):
        self.model = model
        self.budget = budget
        self.model_name = model_name

    async def close(self) -> None:
        await self.model.close()

    def get_retry_advice(
        self, request: ModelRetryAdviceRequest
    ) -> ModelRetryAdvice | None:
        # Do not recommend an SDK replay. Failed requests consume their reservation.
        return None

    async def _shorten(
        self,
        prepared: str | list[TResponseInputItem],
        fixed: int,
        affordable_input: int,
        originals: str | list[TResponseInputItem],
        *,
        preserve_sources: bool = False,
    ) -> tuple[str | list[TResponseInputItem], dict[str, Any]]:
        history = active_history()
        if history is None:
            return prepared, {"status": "unavailable"}
        hard_target = max(0, int((affordable_input - 256) / 1.25) - fixed)
        preserve_fields = preserve_stage_fields(f"{_stage.get()} {_agent.get()}")
        essential = measure(essential_input(prepared, preserve_fields))[
            "estimated_tokens"
        ]
        target = min(
            hard_target,
            max(essential, int((affordable_input * 0.60 - 256) / 1.25) - fixed),
        )
        working = prepared
        handle = None
        rotated = 0
        if isinstance(working, list) and isinstance(originals, list):
            working, handle, rotated = rotate_exchanges(
                working, history, originals=originals
            )
        plan = plan_compaction(working, history, preserve_fields)
        shortened = compact_to_tokens(plan, target)
        if measure(shortened)["estimated_tokens"] > target:
            shortened = bound_original_views(
                shortened, history, target, preserve_fields
            )
        if (
            measure(shortened)["estimated_tokens"] > hard_target
            and isinstance(working, list)
            and isinstance(originals, list)
        ):
            working, emergency_handle, emergency_rotated = rotate_exchanges(
                working, history, originals=originals, recent=0
            )
            if emergency_handle is not None:
                handle = emergency_handle
                rotated += emergency_rotated
            emergency_plan = plan_compaction(working, history, preserve_fields)
            shortened = compact_to_tokens(emergency_plan, hard_target)
            if measure(shortened)["estimated_tokens"] > hard_target:
                shortened = bound_original_views(
                    shortened, history, hard_target, preserve_fields
                )
        if (
            preserve_sources
            and isinstance(shortened, list)
            and isinstance(originals, list)
        ):
            domains, quoted, _ = _source_state(originals)
            for characters in (2000, 1000, 500):
                restored = restore_source_views(
                    shortened,
                    originals,
                    history,
                    characters=characters,
                    excluded_domains={
                        domains[source_id]
                        for source_id in quoted
                        if source_id in domains
                    },
                )
                if measure(restored)["estimated_tokens"] <= hard_target:
                    shortened = restored
                    break
        changed = (
            measure(shortened)["estimated_tokens"]
            < measure(prepared)["estimated_tokens"]
        )
        return shortened if changed else prepared, {
            "status": "rotated_exact_exchanges"
            if rotated
            else "deterministic_projection"
            if changed
            else "irreducible",
            "fields": len(plan.fields),
            "rotated_exchanges": rotated,
            "archive_view_id": handle,
            "original_handles": list(dict.fromkeys(plan.handles.values()))[:8],
            "omitted_material_unreviewed": changed,
            "target_input_tokens": target,
            "paid_selector_enabled": False,
        }

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> ModelResponse:
        if previous_response_id or conversation_id:
            raise ContextBudgetExceeded(
                "Hidden remote history cannot be measured safely."
            )
        agent = _agent.get()
        stage = _stage.get()
        limits = self.budget.limits
        before = input
        prepared = (
            compact_json(input) if isinstance(input, str) else prepare_history(input)
        )
        exhausted = set()
        if not isinstance(prepared, str):
            call_names = {
                i.get("call_id"): i.get("name")
                for i in prepared
                if i.get("type") == "function_call"
            }
            call_owners = {
                i.get("call_id"): self.budget.call_owners.get(
                    (
                        str(i.get("call_id")),
                        str(i.get("name")),
                        compact_json(str(i.get("arguments", "{}"))),
                    )
                )
                for i in prepared
                if i.get("type") == "function_call"
            }
            for item in prepared:
                output = item.get("output")
                if item.get("type") != "function_call_output" or not isinstance(
                    output, str
                ):
                    continue
                try:
                    result = json.loads(output)
                except ValueError:
                    continue
                if (
                    isinstance(result, dict)
                    and result.get("status") == "budget_exhausted"
                    and call_owners.get(item.get("call_id")) == agent
                ):
                    exhausted.add(call_names.get(item.get("call_id")))
            tools = [tool for tool in tools if tool.name not in exhausted]
        output_limit = min(
            model_settings.max_tokens or limits.output_tokens, limits.output_tokens
        )
        reserve = 0 if "Verifier" in agent else limits.verification_reserve
        if "Comparison" not in agent and "Verifier" not in agent:
            reserve += limits.decision_reserve
        remaining = limits.total_tokens - self.budget.spent - self.budget.reserved
        allowances = _allowances.get()
        source_remaining = min(
            (a.limits.total_tokens - a.spent - a.reserved for a in allowances),
            default=remaining,
        )
        owner_key = (agent, tuple(id(allowance) for allowance in allowances))
        capture_calls = self.budget.capture_calls.get(owner_key, 0)
        evidence_tools = {
            "record_source_quote",
            "read_research_result",
            "read_source_snapshot",
            "complete_research_result",
            "read_run_evidence",
        }
        parts: dict[str, dict[str, int]] = {}

        def allocation() -> tuple[int, int, int]:
            parts.update(
                instructions=measure(system_instructions or ""),
                schemas=measure(_schema_payload(tools, output_schema, handoffs)),
                input=measure(prepared),
            )
            estimated = (
                ceil(sum(part["estimated_tokens"] for part in parts.values()) * 1.25)
                + 256
            )
            hosted_tokens = (
                limits.hosted_reserve
                if any(tool.name == "web_search" for tool in tools)
                else 0
            )
            affordable = min(
                limits.input_tokens,
                remaining - reserve - output_limit - hosted_tokens,
                source_remaining - output_limit - hosted_tokens,
            )
            return estimated, hosted_tokens, max(0, affordable)

        estimate, hosted, affordable_input = allocation()
        compaction: dict[str, Any] | None = None
        if estimate > affordable_input * 0.75:
            fixed = (
                parts["instructions"]["estimated_tokens"]
                + parts["schemas"]["estimated_tokens"]
            )
            prepared, compaction = await self._shorten(
                prepared, fixed, affordable_input, before
            )
            estimate, hosted, affordable_input = allocation()
        source_domains, quoted_sources, fetched_sources = _source_state(before)
        quoted_domains = {
            source_domains[source_id]
            for source_id in quoted_sources
            if source_id in source_domains
        }
        fresh_sources = {
            source_id
            for source_id, domain in source_domains.items()
            if domain not in quoted_domains and source_id not in fetched_sources
        }
        recovery_margin = 24_000 if fresh_sources and not quoted_sources else 12_000
        spending_finalizing = bool(tools or handoffs) and (
            remaining < reserve + 24_000
            or source_remaining < 24_000
            or remaining < estimate + output_limit + hosted + reserve + recovery_margin
            or source_remaining < estimate + output_limit + hosted + recovery_margin
            or owner_key in self.budget.capture_calls
        )
        context_pressure_finalizing = estimate > affordable_input
        finalizing = spending_finalizing or context_pressure_finalizing
        phase = "research"
        capture_action = None
        capture_read_tools: list[Tool] = []
        quote_followup_reservation = 0
        quote_source_ids: set[str] = set()
        completion_reservation = 0
        completion_parts: dict[str, dict[str, int]] | None = None
        completion_prepared = prepared
        completion_compaction: dict[str, Any] | None = None
        completion_output_limit = output_limit
        completion_instructions = system_instructions
        if finalizing:
            closed_instructions = (system_instructions or "") + (
                "\nFurther research is closed. Finish from existing exact evidence and quotes. "
                "Preserve conflicts, uncertainty, source gaps and seller risks. Do not invent "
                "support or silently turn a technical limitation into a no-strong-buy judgment. "
                "Omitted originals are unreviewed. Explain missing evidence separately from "
                "technical research limitations. For a buying decision, retain named candidates "
                "whose product identity and relevant facts have exact recorded support. "
                "A product-only suggestion can use trusted official support; independent reviews "
                "are optional unless needed for a comparative claim. Qualify unverified performance, "
                "current-generation or upcoming-release status, regional compatibility, prices, "
                "stock and warranty separately. Those unknowns alone do not erase a supported "
                "candidate. Never imply a verified listing or an established comparative verdict "
                "when that support is absent."
            )
            completion_instructions = (
                closed_instructions
                + " Capture is now closed. Synthesize the supported facts into the requested "
                "decision now, including a named product-only choice where supported, with clear "
                "qualifications for unanswered claims. Keep exact evidence references, source "
                "cautions and seller risks; use only support already recorded."
            )
            completion_parts = {
                "instructions": measure(completion_instructions),
                "schemas": measure(_schema_payload([], output_schema, [])),
                "input": measure(completion_prepared),
            }
            completion_affordable = max(
                0,
                min(
                    limits.input_tokens,
                    remaining - reserve - completion_output_limit,
                    source_remaining - completion_output_limit,
                ),
            )
            completion_fixed = (
                completion_parts["instructions"]["estimated_tokens"]
                + completion_parts["schemas"]["estimated_tokens"]
            )
            completion_prepared, completion_compaction = await self._shorten(
                completion_prepared, completion_fixed, completion_affordable, before
            )
            completion_parts["input"] = measure(completion_prepared)
            completion_estimate = (
                ceil(
                    sum(part["estimated_tokens"] for part in completion_parts.values())
                    * 1.25
                )
                + 256
            )
            completion_reservation = completion_estimate + completion_output_limit
            phase = (
                "capture"
                if "Verifier" not in agent
                and capture_calls < 4
                and len(quoted_sources) < 2
                and (
                    not quoted_sources
                    or bool(_quote_sources(before, source_domains, quoted_domains))
                )
                and any(tool.name in evidence_tools for tool in tools)
                else "complete"
            )
            capture_tools = evidence_tools | {"fetch_source"}
            tools = [
                tool
                for tool in tools
                if phase == "capture" and tool.name in capture_tools
            ]
            if phase == "capture":
                self.budget.capture_sources[owner_key] = fresh_sources
                for tool in tools:
                    if tool.name != "fetch_source" or not isinstance(
                        tool, FunctionTool
                    ):
                        continue
                    callback = tool.on_invoke_tool
                    if getattr(callback, "_capture_fetch_guard", False):
                        continue

                    async def fetch_existing_source(
                        context: Any, arguments: str, *, callback=callback
                    ) -> str:
                        budget = active_budget()
                        current_key = (
                            _agent.get(),
                            tuple(id(allowance) for allowance in _allowances.get()),
                        )
                        if budget is not None and current_key in budget.capture_calls:
                            try:
                                source_id = str(
                                    json.loads(arguments).get("source_id", "")
                                )
                            except ValueError:
                                source_id = ""
                            if source_id not in budget.capture_sources.get(
                                current_key, set()
                            ):
                                return json.dumps(
                                    {
                                        "status": "invalid_request",
                                        "gap": "Capture must use an unfetched source from a domain whose support is not recorded. Choose an allowed existing source ID.",
                                    }
                                )
                            if budget.capture_fetches.get(current_key, 0) >= 2:
                                return json.dumps(
                                    {
                                        "status": "budget_exhausted",
                                        "gap": "The two bounded capture fetch attempts are used. Complete from recorded support.",
                                    }
                                )
                            budget.capture_fetches[current_key] = (
                                budget.capture_fetches.get(current_key, 0) + 1
                            )
                            budget.capture_sources[current_key].discard(source_id)
                        return await callback(context, arguments)

                    fetch_existing_source._capture_fetch_guard = True
                    tool.on_invoke_tool = fetch_existing_source
            handoffs = []
            if phase == "capture":
                history = active_history()
                if (
                    history is not None
                    and isinstance(prepared, list)
                    and isinstance(before, list)
                ):
                    prepared = restore_source_views(
                        prepared, before, history, excluded_domains=quoted_domains
                    )
                capture_read_tools = [
                    tool
                    for tool in tools
                    if tool.name
                    in {
                        "read_source_snapshot",
                        "read_run_evidence",
                        "read_research_result",
                    }
                ]
                output_limit = min(output_limit, 2000)
                quote_source_ids = _quote_sources(
                    prepared, source_domains, quoted_domains
                )
                quote_tools = [
                    tool for tool in tools if tool.name == "record_source_quote"
                ]
                fetch_tools = [tool for tool in tools if tool.name == "fetch_source"]
                if quote_source_ids and quote_tools:
                    tools = [
                        _source_choices(tool, quote_source_ids) for tool in quote_tools
                    ]
                    capture_action = "record_quotes"
                    system_instructions = closed_instructions + (
                        " Record exact useful product support from the unquoted source IDs supplied here. "
                        "Record complementary passages together. Navigation, setup and shipping text "
                        "cannot support product identity or performance. Fetched text is not recorded evidence. "
                        "Official support can justify a product-only suggestion; qualify unsupported comparisons."
                    )
                elif (
                    fresh_sources
                    and fetch_tools
                    and self.budget.capture_fetches.get(owner_key, 0) < 2
                    and capture_calls < 3
                ):
                    tools = [
                        _source_choices(tool, fresh_sources) for tool in fetch_tools
                    ]
                    capture_action = "fetch_missing_source"
                    system_instructions = closed_instructions + (
                        " Fetch one strongest already-discovered source for exact missing product facts from "
                        "the allowed unfetched source IDs now. Prefer a trusted manufacturer announcement or "
                        "specification page; use an available substantive review for comparative claims. "
                        "A failed page permits one alternative existing source. Next record exact useful support. "
                        "Independent reviews are optional; retain supported official candidates."
                    )
                    quote_fixed = (
                        measure(
                            closed_instructions
                            + " Record exact useful quotes from the newly fetched source."
                        )["estimated_tokens"]
                        + measure(_schema_payload(quote_tools, output_schema, []))[
                            "estimated_tokens"
                        ]
                    )
                    quote_packet, _ = await self._shorten(
                        completion_prepared,
                        quote_fixed,
                        min(
                            limits.input_tokens,
                            max(
                                0,
                                (
                                    min(remaining - reserve, source_remaining)
                                    - completion_reservation
                                    - 2 * output_limit
                                )
                                // 2,
                            ),
                        ),
                        before,
                    )
                    # Reserve the fitted quote packet plus a bounded future 2k source span and envelope.
                    quote_followup_reservation = (
                        ceil(
                            (
                                quote_fixed
                                + measure(quote_packet)["estimated_tokens"]
                                + measure(
                                    {
                                        "source_id": "0" * 36,
                                        "snapshot_id": "0" * 36,
                                        "text": "𐀀" * 2000,
                                        "metadata": "𐀀" * 1000,
                                    }
                                )["estimated_tokens"]
                            )
                            * 1.25
                        )
                        + 256
                        + output_limit
                    )
                elif (
                    capture_read_tools
                    and capture_calls < 3
                    and _quote_sources(before, source_domains, quoted_domains)
                ):
                    tools = [
                        _source_choices(
                            tool, _quote_sources(before, source_domains, quoted_domains)
                        )
                        for tool in capture_read_tools
                    ]
                    capture_action = "read_for_quote"
                    system_instructions = (
                        closed_instructions
                        + " Read one bounded useful source span from an unquoted domain. Do not repeat failed or already-quoted source bodies."
                    )
                else:
                    phase = "complete"
                    tools = []
                    prepared = completion_prepared
                    system_instructions = completion_instructions
                    compaction = completion_compaction
                    completion_reservation = 0
                    output_limit = completion_output_limit
            else:
                system_instructions = completion_instructions
                prepared = completion_prepared
                compaction = completion_compaction
                completion_reservation = 0
            model_settings = replace(
                model_settings, tool_choice=None, parallel_tool_calls=phase == "capture"
            )
            estimate, hosted, affordable_input = allocation()
            if phase == "capture":
                affordable_input = min(
                    affordable_input,
                    max(
                        0,
                        min(
                            remaining
                            - reserve
                            - output_limit
                            - completion_reservation
                            - quote_followup_reservation,
                            source_remaining
                            - output_limit
                            - completion_reservation
                            - quote_followup_reservation,
                        ),
                    ),
                )

        if finalizing and estimate > affordable_input * 0.75:
            fixed = (
                parts["instructions"]["estimated_tokens"]
                + parts["schemas"]["estimated_tokens"]
            )
            prepared, compaction = await self._shorten(
                prepared,
                fixed,
                affordable_input,
                before,
                preserve_sources=phase == "capture",
            )
            estimate, hosted, final_affordable = allocation()
            affordable_input = min(affordable_input, final_affordable)
        if phase == "capture" and capture_action == "record_quotes":
            final_quote_sources = _quote_sources(
                prepared, source_domains, quoted_domains
            )
            if final_quote_sources:
                tools = [_source_choices(tool, final_quote_sources) for tool in tools]
                estimate, hosted, final_affordable = allocation()
                affordable_input = min(affordable_input, final_affordable)
                model_settings = replace(
                    model_settings,
                    tool_choice="record_source_quote",
                    parallel_tool_calls=True,
                )
            else:
                if capture_calls < 2 and capture_read_tools:
                    tools = capture_read_tools
                    capture_action = "read_for_quote"
                    system_instructions = (
                        closed_instructions
                        + " Reread one bounded already available source span for the missing source role now. The next funded turn must record its exact useful quote."
                    )
                    model_settings = replace(
                        model_settings,
                        tool_choice="required",
                        parallel_tool_calls=False,
                    )
                    estimate, hosted, affordable_input = allocation()
                    affordable_input = min(
                        affordable_input,
                        max(
                            0,
                            min(remaining - reserve, source_remaining)
                            - output_limit
                            - completion_reservation,
                        ),
                    )
                    if estimate > affordable_input * 0.75:
                        fixed = (
                            parts["instructions"]["estimated_tokens"]
                            + parts["schemas"]["estimated_tokens"]
                        )
                        prepared, compaction = await self._shorten(
                            prepared, fixed, affordable_input, before
                        )
                        estimate, hosted, final_affordable = allocation()
                        affordable_input = min(affordable_input, final_affordable)
                else:
                    phase = "complete"
                    tools = []
                    prepared = completion_prepared
                    system_instructions = completion_instructions
                    compaction = completion_compaction
                    completion_reservation = 0
                    output_limit = completion_output_limit
                    model_settings = replace(
                        model_settings, tool_choice=None, parallel_tool_calls=False
                    )
                    estimate, hosted, affordable_input = allocation()
        elif phase == "capture" and capture_action == "fetch_missing_source":
            model_settings = replace(
                model_settings, tool_choice="fetch_source", parallel_tool_calls=False
            )
        elif phase == "capture" and capture_action == "read_for_quote":
            model_settings = replace(
                model_settings, tool_choice="required", parallel_tool_calls=False
            )
        if phase == "capture" and estimate > affordable_input:
            phase = "complete"
            tools = []
            output_limit = completion_output_limit
            system_instructions = completion_instructions
            prepared = completion_prepared
            compaction = completion_compaction
            completion_reservation = 0
            quote_followup_reservation = 0
            model_settings = replace(
                model_settings, tool_choice=None, parallel_tool_calls=False
            )
            estimate, hosted, affordable_input = allocation()
        requested_reservation = estimate + output_limit + hosted
        block_reason = (
            "input_limit"
            if estimate > limits.input_tokens
            else "shared_downstream_reserve"
            if requested_reservation
            + reserve
            + completion_reservation
            + quote_followup_reservation
            > remaining
            else "owner_allowance"
            if requested_reservation
            + completion_reservation
            + quote_followup_reservation
            > source_remaining
            else "exhausted_allowance"
            if any(a.exhausted for a in allowances)
            else None
        )
        event: dict[str, Any] = {
            "tool_name": "context_call",
            "status": "prepared",
            "input": {"agent": agent, "stage": stage},
            "output": {
                "model": self.model_name,
                "components": parts,
                "before_input": _before_size.get() or measure(before),
                "after_input": measure(prepared),
                "estimated_input_tokens": estimate,
                "base_input_tokens": sum(
                    part["estimated_tokens"] for part in parts.values()
                ),
                "headroom_tokens": estimate
                - sum(part["estimated_tokens"] for part in parts.values()),
                "actual_input_tokens": None,
                "input_breakdown": input_breakdown(prepared)
                if not isinstance(prepared, str)
                else {},
                "actual_output_tokens": None,
                "finalizing": finalizing,
                "spending_finalizing": spending_finalizing,
                "context_pressure_finalizing": context_pressure_finalizing,
                "compaction": compaction,
                "shared_spent_tokens": self.budget.spent,
                "phase": phase,
                "capture_fetches_used": self.budget.capture_fetches.get(owner_key, 0),
                "capture_action": capture_action,
                "quoted_domain_count": len(quoted_domains),
                "active_output_limit": output_limit,
                "output_limit": output_limit,
                "requested_reservation": requested_reservation,
                "owner_remaining_tokens": source_remaining,
                "shared_remaining_tokens": remaining,
                "downstream_reserve_tokens": reserve,
                "completion_reserve_tokens": completion_reservation,
                "quote_followup_reserve_tokens": quote_followup_reservation,
                "capture_source_choices": len(fresh_sources),
                "completion_components": completion_parts,
                "completion_output_limit": completion_output_limit,
                "completion_compaction": completion_compaction,
                "affordable_input_tokens": affordable_input,
                "block_reason": block_reason,
            },
        }
        self.budget.events.append(event)
        if block_reason is not None:
            event["status"] = "blocked"
            raise ContextBudgetExceeded(
                f"Model transport cannot fit safely: {block_reason}. "
                f"Input {estimate}, output {output_limit}, reservation {requested_reservation}, "
                f"owner remaining {source_remaining}, shared remaining {remaining}, "
                f"downstream reserve {reserve}."
            )
        if finalizing:
            self.budget.capture_calls[owner_key] = (
                capture_calls + 1 if phase == "capture" else 4
            )
        reservation = self.budget.reserve(requested_reservation, agent=agent)
        for allowance in allowances:
            allowance.reserve(reservation, agent=agent)

        def settle(actual: int | None) -> None:
            error = None
            for ledger in (self.budget, *allowances):
                try:
                    ledger.settle(reservation, actual)
                except ContextBudgetExceeded as exc:
                    error = exc
            if error is not None:
                event["status"] = "blocked_actual_usage"
                raise error

        try:
            history = active_history()
            if history is not None:
                history.record_transport(prepared, originals=before)
            response = await self.model.get_response(
                system_instructions,
                prepared,
                replace(model_settings, max_tokens=output_limit),
                tools,
                output_schema,
                handoffs,
                tracing,
                previous_response_id=None,
                conversation_id=None,
                prompt=prompt,
            )
        except BaseException as exc:
            event["status"] = (
                "cancelled_reserved"
                if type(exc).__name__ == "CancelledError"
                else "failed_reserved"
            )
            settle(None)
            raise
        usage = response.usage
        actual = (
            usage.total_tokens or usage.input_tokens + usage.output_tokens
        ) or None
        event["output"].update(
            actual_input_tokens=usage.input_tokens if actual is not None else None,
            actual_output_tokens=usage.output_tokens if actual is not None else None,
        )
        event["status"] = "completed" if actual is not None else "completed_estimated"
        settle(actual)
        event["output"]["shared_spent_tokens"] = self.budget.spent
        disallowed = {
            getattr(item, "name", None)
            for item in response.output
            if getattr(item, "type", "") == "function_call"
        }
        enabled = {tool.name for tool in tools} | {item.tool_name for item in handoffs}
        if disallowed - enabled and (finalizing or exhausted):
            event["status"] = "blocked_closed_research"
            raise ContextBudgetExceeded(
                "The model requested research after its spending or tool budget closed."
            )
        if history is not None:
            history.record_response(response.output)
        for response_item in response.output:
            if isinstance(response_item, ResponseFunctionToolCall):
                self.budget.call_owners[
                    (
                        response_item.call_id,
                        response_item.name,
                        compact_json(response_item.arguments),
                    )
                ] = agent
        return response

    def stream_response(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[TResponseStreamEvent]:
        raise ContextBudgetExceeded(
            "Streaming is not used by the bounded shopping workflow."
        )


class BudgetedProvider(ModelProvider):
    def __init__(self, provider: ModelProvider, budget: ContextBudget):
        self.provider, self.budget = provider, budget

    def get_model(self, model_name: str | None) -> Model:
        return BudgetedModel(
            self.provider.get_model(model_name), self.budget, model_name
        )


class BoundedRunner:
    @staticmethod
    async def run(
        agent: Agent[Any], model_input: str, *, run_config: RunConfig, max_turns: int
    ) -> Any:
        with context_scope() as budget:
            assert budget is not None
            if isinstance(agent.model, Model) or isinstance(run_config.model, Model):
                raise ValueError(
                    "Shopping models must resolve through the bounded provider."
                )
            if run_config.call_model_input_filter is not None:
                raise ValueError("Shopping input filters must be composed explicitly.")
            configured = replace(
                run_config,
                call_model_input_filter=filter_input,
                model_provider=BudgetedProvider(run_config.model_provider, budget),
            )
            history = active_history()
            needs_lookup = not agent.tools or bool(
                history and plan_compaction(model_input, history).fields
            )
            if needs_lookup and not any(
                tool.name == "read_research_result" for tool in agent.tools
            ):
                agent = agent.clone(tools=[*agent.tools, history_tools()[1]])
            return await Runner.run(
                agent, model_input, run_config=configured, max_turns=max_turns
            )
