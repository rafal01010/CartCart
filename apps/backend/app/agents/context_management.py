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
from app.agents.research_guidance import SHOPPER_ADVICE_GUIDANCE
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
    """Expose bounded saved source context with optional associations."""
    payload = bundle.model_dump(mode="json")
    deferred = []
    if "transcript_segments" in payload:
        cited = {
            segment_id
            for evidence in payload.get("evidence", [])
            for segment_id in evidence.get("transcript_segment_ids", [])
        }
        segments = payload["transcript_segments"]
        relevant = [segment for segment in segments if segment["segment_id"] in cited]
        for segment in segments:
            if segment in relevant:
                continue
            if any(
                evidence.get("video_id") == segment["video_id"]
                and any(
                    timestamp["start_seconds"] <= (
                        segment.get("end_seconds") or segment["start_seconds"]
                    )
                    and (timestamp.get("end_seconds") or timestamp["start_seconds"])
                    >= segment["start_seconds"]
                    for timestamp in evidence.get("timestamp_references", [])
                )
                for evidence in payload.get("evidence", [])
            ):
                relevant.append(segment)
        payload["transcript_segments"] = relevant or segments[:2]
        if len(payload["transcript_segments"]) < len(segments):
            deferred.append("transcript_segments")
            payload["unreviewed_content"] = True
    for discussion in payload.get("discussions", []):
        if "extracted_public_summary" in discussion:
            discussion["extracted_public_summary"] = discussion[
                "extracted_public_summary"
            ][:2000]
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
        recovery_margin = 12_000
        spending_finalizing = bool(tools or handoffs) and (
            remaining < reserve + 24_000
            or source_remaining < 24_000
            or remaining < estimate + output_limit + hosted + reserve + recovery_margin
            or source_remaining < estimate + output_limit + hosted + recovery_margin
        )
        context_pressure_finalizing = estimate > affordable_input
        finalizing = spending_finalizing or context_pressure_finalizing
        phase = "complete" if finalizing else "research"
        if finalizing:
            tools = []
            handoffs = []
            system_instructions = (system_instructions or "") + (
                "\nFurther research is closed. Finish from available saved snippets, pages, "
                "source notes and buyer preferences. Recommend by default with concise reasons, "
                "tradeoffs. Keep unknowns and diagnostic warnings in internal fields. Sources and reviews are optional. Weigh actual "
                "adverse findings with their scope. Missing quotations, seller details or prices "
                "do not alone exclude a product. Do not invent current facts, prices, links or "
                "quotations. Source notes may paraphrase originals. "
                "A technical inability to finish is a retryable failure, not a buying judgment."
                + " " + SHOPPER_ADVICE_GUIDANCE
            )
            model_settings = replace(
                model_settings, tool_choice=None, parallel_tool_calls=False
            )
            estimate, hosted, affordable_input = allocation()
            fixed = (
                parts["instructions"]["estimated_tokens"]
                + parts["schemas"]["estimated_tokens"]
            )
            prepared, compaction = await self._shorten(
                prepared, fixed, affordable_input, before
            )
            estimate, hosted, affordable_input = allocation()
        requested_reservation = estimate + output_limit + hosted
        block_reason = (
            "input_limit"
            if estimate > limits.input_tokens
            else "shared_downstream_reserve"
            if requested_reservation + reserve > remaining
            else "owner_allowance"
            if requested_reservation > source_remaining
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
                "active_output_limit": output_limit,
                "output_limit": output_limit,
                "requested_reservation": requested_reservation,
                "owner_remaining_tokens": source_remaining,
                "shared_remaining_tokens": remaining,
                "downstream_reserve_tokens": reserve,
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
