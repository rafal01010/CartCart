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
from agents.exceptions import ModelBehaviorError
from agents.handoffs import Handoff
from agents.items import ModelResponse, TResponseInputItem, TResponseStreamEvent
from agents.models.interface import Model, ModelProvider, ModelTracing
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.models.openai_responses import OpenAIResponsesModel
from agents.retry import ModelRetryAdvice, ModelRetryAdviceRequest
from agents.run_config import CallModelData, ModelInputData
from agents.tool import FunctionTool, Tool
from openai.types.responses import (
    ResponseFunctionToolCall,
)
from openai.types.responses.response_prompt_param import ResponsePromptParam
from pydantic import BaseModel

from app.agents.context_metrics import input_breakdown, measure
from app.agents.decision_sources import fit_owner_projection, input_projection, project_owner_sources, source_size
from app.agents.token_policy import (
    CompletionPurpose,
    OWNER_START_TOKENS,
    SOURCE_START_TOKENS,
    completion_purpose,
    scaled_tokens,
)
from app.agents.research_guidance import FINAL_OPTION_SET_GUIDANCE, SHOPPER_ADVICE_GUIDANCE
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


class FinalOutputFailure(ModelBehaviorError):
    """The model did not complete a valid final contract within bounded recovery."""


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
    input_tokens: int = scaled_tokens(19_000)
    total_tokens: int = scaled_tokens(150_000)
    decision_reserve: int = scaled_tokens(24_000)
    verification_reserve: int = scaled_tokens(24_000)
    hosted_reserve: int = scaled_tokens(8_000)
    output_tokens: int = scaled_tokens(5_000)


@dataclass
class CompletionCheckpoint:
    agent: str
    instructions: str
    input: Any
    reservation_tokens: int
    output_tokens: int
    retained_return_input_tokens: int

    @property
    def next_input_ceiling(self) -> int:
        return self.reservation_tokens - self.output_tokens + self.retained_return_input_tokens


@dataclass
class ContextBudget:
    limits: ContextLimits = field(default_factory=ContextLimits)
    spent: int = 0
    reserved: int = 0
    exhausted: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    call_owners: dict[tuple[str, str, str], str] = field(default_factory=dict)
    scope: str = "main"
    transferable: bool = True
    completion_plans: dict[str, int] = field(default_factory=dict)
    completion_checkpoints: dict[str, CompletionCheckpoint] = field(
        default_factory=dict
    )
    final_output_recoveries: set[str] = field(default_factory=set)
    eligible_stages: frozenset[str] = frozenset()
    input_headroom_ratio: float = 1.25

    @property
    def remaining(self) -> int:
        return self.limits.total_tokens - self.spent - self.reserved

    def reserve(self, estimated: int, *, agent: str) -> int:
        if (
            self.exhausted
            or self.spent + self.reserved + estimated > self.limits.total_tokens
        ):
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
_response_envelope: ContextVar[Any] = ContextVar("shopping_response_envelope", default=None)
_recovering_final_output: ContextVar[bool] = ContextVar("shopping_recovering_final_output", default=False)


class EnvelopeResponsesModel(OpenAIResponsesModel):
    async def _fetch_response(self, *args: Any, **kwargs: Any) -> Any:
        response = await super()._fetch_response(*args, **kwargs)
        # The SDK drops envelope status when constructing ModelResponse.
        _response_envelope.set(response)
        return response


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


def funded_scope_limit(scope: str, starting: int) -> int:
    for ledger in reversed(_allowances.get()):
        if getattr(ledger, "scope", None) == scope:
            return ledger.limits.total_tokens
    return starting


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
    return _managed_allowance(function, SOURCE_START_TOKENS, "source")


def managed_owner_context(
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    return _managed_allowance(function, OWNER_START_TOKENS, "owner")


def managed_decision_context(
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    return _managed_allowance(
        function, ContextLimits().decision_reserve, "decision", transferable=False
    )


def managed_verification_context(
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    return _managed_allowance(
        function,
        ContextLimits().verification_reserve,
        "verification",
        transferable=False,
    )


def _managed_allowance(
    function: Callable[P, Awaitable[R]],
    total: int,
    scope: str,
    *,
    transferable: bool = True,
) -> Callable[P, Awaitable[R]]:
    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with context_scope():
            input_data = args[1] if len(args) > 1 else kwargs.get("input_data")
            shared = getattr(input_data, "source_allowance", None) if scope == "source" else None
            allowance = shared or ContextBudget(
                limits=ContextLimits(total_tokens=total),
                scope=scope,
                transferable=transferable,
            )
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


def completion_instructions(
    instructions: str | None, purpose: CompletionPurpose
) -> str:
    if instructions is not None and "\nFurther research is closed. " in instructions:
        return instructions
    guidance = (
        "Finish the source evidence output from retrieved metadata, relevant speech and interpreted notes. "
        "Preserve video/source/segment identifiers, timestamps, provenance and material cautions. "
        "Distinguish retrieval never attempted due to funding from provider unavailability. "
        "Return accurate gaps for omitted unreviewed material. Do not give buying advice."
        if purpose == CompletionPurpose.SOURCE
        else "Finish the source consultation summary from validated returned bundles. Explain unattempted "
        "sources honestly. Technical funding gaps are retryable and do not establish provider unavailability."
        if purpose == CompletionPurpose.SOURCE_MANAGER
        else "Finish the requested structured output from retained reviewed information. Preserve constraints, "
        "facts, uncertainties and provenance. Do not change the responsibility of this stage."
        if purpose == CompletionPurpose.STRUCTURED
        else "Finish from saved facts, snippets, source notes and the complete buyer brief. "
        + (FINAL_OPTION_SET_GUIDANCE if FINAL_OPTION_SET_GUIDANCE not in (instructions or "") else "")
        + (SHOPPER_ADVICE_GUIDANCE if SHOPPER_ADVICE_GUIDANCE not in (instructions or "") else "")
    )
    return (
        (instructions or "")
        + "\nFurther research is closed. "
        + guidance
        + (
            " Do not invent facts, prices, links or quotations. Omitted material remains unreviewed. "
            "A technical inability to finish is a retryable failure, not a buying judgment."
        )
    )


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
        ratio = self.budget.input_headroom_ratio
        hard_target = max(0, int((affordable_input - 256) / ratio) - fixed)
        preserve_fields = preserve_stage_fields(f"{_stage.get()} {_agent.get()}")
        essential = measure(essential_input(prepared, preserve_fields))[
            "estimated_tokens"
        ]
        target = min(
            hard_target,
            max(essential, int((affordable_input * 0.60 - 256) / ratio) - fixed),
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
        shortened = fit_owner_projection(shortened, hard_target)
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
        allowances = _allowances.get()
        ledgers = (self.budget, *allowances)
        holder = ledgers[-1]
        purpose = completion_purpose(
            agent, output_schema.json_schema().get("title") if output_schema else None
        )
        source_input_before = prepared
        source_request_before = {"model": self.model_name, "model_settings": str(model_settings), "instructions": system_instructions, "input": prepared, "schemas": _schema_payload(tools, output_schema, handoffs), "prompt": prompt}
        if purpose == CompletionPurpose.OWNER:
            prepared, _ = project_owner_sources(prepared)
        source_input_selected = prepared
        plan_key = (
            purpose.value
            if purpose == CompletionPurpose.OWNER
            else purpose.value + ":" + agent
        )
        reserve = sum(
            value
            for name, value in (
                ("comparison_decision", limits.decision_reserve),
                ("verification", limits.verification_reserve),
            )
            if name in self.budget.eligible_stages and name != stage
        )
        remaining = self.budget.remaining
        parts: dict[str, dict[str, int]] = {}
        compaction: dict[str, Any] | None = None
        compaction_steps: list[dict[str, Any]] = []
        ratio = self.budget.input_headroom_ratio

        def request_parts(
            instructions: str | None,
            value: Any,
            eligible_tools: list[Tool],
            eligible_handoffs: list[Handoff],
        ) -> tuple[int, dict[str, dict[str, int]]]:
            components = {
                "instructions": measure(instructions or ""),
                "schemas": measure(
                    _schema_payload(eligible_tools, output_schema, eligible_handoffs)
                ),
                "input": measure(value),
            }
            return ceil(
                sum(part["estimated_tokens"] for part in components.values()) * ratio
            ) + 256, components

        def protected(index: int, own_completion: int = 0) -> int:
            return (
                (reserve if index == 0 else 0)
                + own_completion
                + sum(
                    tokens
                    for ledger in ledgers[index:]
                    for key, tokens in ledger.completion_plans.items()
                    if not (ledger is holder and key == plan_key)
                )
            )

        def available_input(hosted_tokens: int = 0, own_completion: int = 0) -> int:
            return max(
                0,
                min(
                    limits.input_tokens,
                    *(
                        ledger.remaining
                        - protected(index, own_completion)
                        - output_limit
                        - hosted_tokens
                        for index, ledger in enumerate(ledgers)
                        if index == 0 or not ledger.transferable
                    ),
                ),
            )

        def can_fund(request: int, own_completion: int = 0) -> bool:
            return all(
                not ledger.exhausted
                and (
                    ledger.transferable
                    and index > 0
                    or request + protected(index, own_completion) <= ledger.remaining
                )
                for index, ledger in enumerate(ledgers)
            )

        async def clean(
            value: Any, components: dict[str, dict[str, int]], affordable: int
        ) -> Any:
            nonlocal compaction
            original_size = measure(value)["estimated_tokens"]
            fixed = (
                components["instructions"]["estimated_tokens"]
                + components["schemas"]["estimated_tokens"]
            )
            try:
                value, compaction = await self._shorten(
                    value, fixed, affordable, before
                )
            except Exception as exc:
                history = active_history()
                compaction = {
                    "status": "optional_cleanup_failed",
                    "error_type": type(exc).__name__,
                    "paid_selector_enabled": False,
                }
                if history is not None:
                    target = max(0, int((affordable - 256) / ratio) - fixed)
                    value = bound_original_views(
                        value, history, target, preserve_stage_fields(stage)
                    )
                    compaction["fallback"] = "saved_original_checkpoint"
                    compaction["omitted_material_unreviewed"] = (
                        measure(value)["estimated_tokens"] < original_size
                    )
            compaction_steps.append(dict(compaction))
            return value

        previous_checkpoint = holder.completion_checkpoints.get(plan_key)
        checkpoint_recovery = False
        closure_instructions = completion_instructions(system_instructions, purpose)
        closure_input = prepared
        closure_estimate, closure_parts = request_parts(
            closure_instructions, closure_input, [], []
        )
        closure_affordable = available_input()
        if previous_checkpoint is not None and previous_checkpoint.agent == agent and plan_key in holder.completion_plans and not can_fund(closure_estimate + output_limit):
            closure_affordable = min(closure_affordable, previous_checkpoint.next_input_ceiling)
        if closure_estimate > closure_affordable * 0.75:
            closure_input = await clean(
                closure_input, closure_parts, closure_affordable
            )
            closure_estimate, closure_parts = request_parts(
                closure_instructions, closure_input, [], []
            )
        closure_reservation = closure_estimate + output_limit
        retained_return_input_tokens = min(
            output_limit, max(0, limits.input_tokens - closure_estimate)
        )
        completion_tokens = closure_reservation + retained_return_input_tokens
        if (
            (closure_estimate > closure_affordable or not can_fund(closure_reservation))
            and previous_checkpoint is not None
            and previous_checkpoint.agent == agent
            and previous_checkpoint.output_tokens == output_limit
            and essential_input(previous_checkpoint.input) == essential_input(prepared)
        ):
            history = active_history()
            if history is not None:
                handle = history.archive("completion_return", before)
                candidate = previous_checkpoint.input
                if isinstance(candidate, str):
                    candidate = [{"role": "user", "content": candidate}]
                candidate = [
                    *candidate,
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            history.checkpoint(handle, characters=6000),
                            ensure_ascii=False,
                        ),
                    },
                ]
                candidate_estimate, candidate_parts = request_parts(
                    closure_instructions, candidate, [], []
                )
                if candidate_estimate > closure_affordable:
                    candidate = await clean(
                        candidate, candidate_parts, closure_affordable
                    )
                    candidate_estimate, candidate_parts = request_parts(
                        closure_instructions, candidate, [], []
                    )
                if candidate_estimate <= closure_affordable and can_fund(
                    candidate_estimate + output_limit
                ):
                    closure_input, closure_estimate, closure_parts = (
                        candidate,
                        candidate_estimate,
                        candidate_parts,
                    )
                    closure_reservation = closure_estimate + output_limit
                    completion_tokens = closure_reservation
                    retained_return_input_tokens = 0
                    checkpoint_recovery = True
                    compaction = {
                        "status": "funded_completion_checkpoint",
                        "archive_view_id": handle,
                        "omitted_material_unreviewed": True,
                        "paid_selector_enabled": False,
                    }

        def allocation() -> tuple[int, int, int]:
            estimated, components = request_parts(
                system_instructions, prepared, tools, handoffs
            )
            parts.clear()
            parts.update(components)
            hosted_tokens = (
                limits.hosted_reserve
                if any(tool.name == "web_search" for tool in tools)
                else 0
            )
            affordable = available_input(
                hosted_tokens, completion_tokens if tools or handoffs else 0
            )
            return estimated, hosted_tokens, max(0, affordable)

        estimate, hosted, affordable_input = allocation()
        if estimate > affordable_input * 0.75:
            prepared = await clean(prepared, parts, affordable_input)
            estimate, hosted, affordable_input = allocation()
        hosted_disabled = False
        if hosted and (
            estimate > affordable_input
            or not can_fund(estimate + output_limit + hosted, completion_tokens)
        ):
            tools = [tool for tool in tools if tool.name != "web_search"]
            hosted_disabled = True
            model_settings = replace(
                model_settings, tool_choice="auto" if tools or handoffs else None
            )
            estimate, hosted, affordable_input = allocation()
            if estimate > affordable_input * 0.75:
                prepared = await clean(prepared, parts, affordable_input)
                estimate, hosted, affordable_input = allocation()
        spending_finalizing = bool(tools or handoffs) and (
            closure_estimate > closure_affordable
            or not can_fund(closure_reservation)
            or not can_fund(estimate + output_limit + hosted, completion_tokens)
        )
        context_pressure_finalizing = estimate > affordable_input or checkpoint_recovery
        finalizing = spending_finalizing or context_pressure_finalizing or _recovering_final_output.get()
        phase = "complete" if finalizing else "research"
        if finalizing:
            tools = []
            handoffs = []
            system_instructions = closure_instructions
            prepared = closure_input
            model_settings = replace(
                model_settings, tool_choice=None, parallel_tool_calls=False
            )
            estimate, hosted, affordable_input = allocation()
            prepared = await clean(prepared, parts, affordable_input)
            estimate, hosted, affordable_input = allocation()
        requested_reservation = estimate + output_limit + hosted
        holding = completion_tokens if tools or handoffs else 0
        transfers = []
        block_reason = (
            "input_limit"
            if estimate > limits.input_tokens
            else "completion_funding"
            if not can_fund(requested_reservation, holding)
            else None
        )
        if block_reason is None:
            for index, ledger in enumerate(ledgers[1:], 1):
                needed = requested_reservation + protected(index, holding)
                if needed > ledger.remaining:
                    old = ledger.limits.total_tokens
                    new = ledger.spent + ledger.reserved + needed
                    ledger.limits = replace(ledger.limits, total_tokens=new)
                    transfers.append(
                        {
                            "scope": ledger.scope,
                            "tokens": new - old,
                            "before": old,
                            "after": new,
                            "main_limit": limits.total_tokens,
                        }
                    )
            if holding:
                holder.completion_plans[plan_key] = holding
                holder.completion_checkpoints[plan_key] = CompletionCheckpoint(
                    agent,
                    closure_instructions,
                    closure_input,
                    closure_reservation,
                    output_limit,
                    retained_return_input_tokens,
                )
        source_remaining = min(
            (ledger.remaining for ledger in ledgers), default=remaining
        )
        if compaction is not None:
            compaction = {
                **compaction,
                "omitted_material_unreviewed": bool(
                    compaction.get("omitted_material_unreviewed")
                )
                or any(
                    step.get("omitted_material_unreviewed") for step in compaction_steps
                ),
                "steps": compaction_steps,
            }
        event: dict[str, Any] = {
            "tool_name": "context_call",
            "status": "prepared",
            "input": {"agent": agent, "stage": stage},
            "output": {
                "model": self.model_name,
                "completion_purpose": purpose.value,
                "completion_request_tokens": closure_reservation,
                "completion_retained_return_input_tokens": retained_return_input_tokens,
                "completion_input_ceiling": closure_estimate + retained_return_input_tokens,
                "completion_hold_tokens": holding,
                "protected_completion_tokens": protected(0, holding),
                "allocation_transfers": transfers,
                "scopes": [
                    {
                        "scope": ledger.scope,
                        "funded_tokens": ledger.limits.total_tokens,
                        "spent_tokens": ledger.spent,
                        "reserved_tokens": ledger.reserved,
                        "remaining_tokens": ledger.remaining,
                        "completion_plans": dict(ledger.completion_plans),
                        "transferable": ledger.transferable,
                    }
                    for ledger in ledgers
                ],
                "hosted_search_disabled": hosted_disabled,
                "input_headroom_ratio": ratio,
                "hosted_expansion_reservation": hosted,
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
            holder.completion_plans.pop(plan_key, None)
            raise ContextBudgetExceeded(
                f"Model transport cannot fit safely: {block_reason}. "
                f"Input {estimate}, output {output_limit}, reservation {requested_reservation}, "
                f"owner remaining {source_remaining}, shared remaining {remaining}, "
                f"downstream reserve {reserve}."
            )
        reservation = self.budget.reserve(requested_reservation, agent=agent)
        for allowance in allowances:
            allowance.reserve(reservation, agent=agent)

        def settle(actual: int | None, *, paid_completion: bool = False) -> None:
            error = None
            exceeded = []
            for ledger in (self.budget, *allowances):
                try:
                    ledger.settle(reservation, actual)
                except ContextBudgetExceeded as exc:
                    error = exc
                    exceeded.append(ledger.scope)
            event["output"].update(
                charged_tokens=actual if actual is not None else reservation,
                shared_spent_tokens=self.budget.spent,
                exceeded_scopes=exceeded,
            )
            if error is not None:
                event["status"] = (
                    "completed_actual_overage"
                    if paid_completion
                    else "blocked_actual_usage"
                )
                if not paid_completion:
                    holder.completion_plans.pop(plan_key, None)
                    raise error

        selection_event = None
        envelope_token = _response_envelope.set(None)
        try:
            history = active_history()
            if history is not None:
                history.record_transport(prepared, originals=before)
            projection = input_projection(prepared)
            if projection is not None and purpose == CompletionPurpose.OWNER:
                projection = projection.model_copy(update={"measurements": {
                    **projection.measurements,
                    "input_before_selection": source_size(source_input_before),
                    "input_after_selection": source_size(source_input_selected),
                    "input_after_compaction": source_size(prepared),
                    "complete_request_before_selection": source_size(source_request_before),
                    "complete_request_after_selection": source_size({**source_request_before, "input": source_input_selected}),
                    "measurement_level": "model_interface_serialized_local_estimate",
                    "complete_request": source_size({"model": self.model_name, "model_settings": str(model_settings), "prompt": prompt, "previous_response_id": None, "conversation_id": None, "instructions": system_instructions, "input": prepared,
                        "schemas": _schema_payload(tools, output_schema, handoffs)}),
                }})
                selection_event = {"tool_name": "decision_source_selection", "status": "prepared",
                    "input": {"agent": agent, "stage": stage}, "output": projection.model_dump(mode="json")}
                self.budget.events.append(selection_event)
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
            if selection_event is not None:
                selection_event["status"] = "transported"
            envelope = _response_envelope.get()
        except BaseException as exc:
            event["status"] = (
                "cancelled_reserved"
                if type(exc).__name__ == "CancelledError"
                else "failed_reserved"
            )
            holder.completion_plans.pop(plan_key, None)
            settle(None)
            raise
        finally:
            _response_envelope.reset(envelope_token)
        usage = response.usage
        actual = (
            usage.total_tokens or usage.input_tokens + usage.output_tokens
        ) or None
        event["output"].update(
            actual_input_tokens=usage.input_tokens if actual is not None else None,
            actual_output_tokens=usage.output_tokens if actual is not None else None,
            actual_total_tokens=actual,
            response_status=getattr(envelope, "status", None),
            incomplete_reason=getattr(getattr(envelope, "incomplete_details", None), "reason", None),
            reasoning_tokens=getattr(
                getattr(getattr(envelope, "usage", None), "output_tokens_details", None),
                "reasoning_tokens", None,
            ),
        )
        output_failure = None
        message_items = [item for item in response.output if getattr(item, "type", "") == "message"]
        function_calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
        if (envelope is not None and getattr(envelope, "status", None) != "completed") or any(getattr(item, "status", None) not in {None, "completed"} for item in response.output):
            output_failure = FinalOutputFailure("The model response did not complete; no partial output was accepted.")
        elif output_schema is not None and not output_schema.is_plain_text() and not function_calls:
            text = "".join(
                content.text for item in message_items for content in item.content
                if getattr(content, "type", "") == "output_text"
            )
            try:
                output_schema.validate_json(text)
            except ModelBehaviorError as exc:
                output_failure = FinalOutputFailure(str(exc))
        event["status"] = "completed" if actual is not None else "completed_estimated"
        paid_completion = (
            output_failure is None
            and bool(response.output)
            and all(
                getattr(item, "type", "") != "function_call" for item in response.output
            )
            and any(
                getattr(item, "type", "") == "message"
                and getattr(item, "status", "") == "completed"
                for item in response.output
            )
        )
        settle(actual, paid_completion=paid_completion)
        base = sum(part["estimated_tokens"] for part in parts.values())
        if actual is not None and base:
            event["output"]["actual_to_base_input_ratio"] = usage.input_tokens / base
            event["output"]["actual_input_over_estimate"] = (
                usage.input_tokens > estimate
            )
            event["output"]["actual_input_over_bound"] = (
                usage.input_tokens > limits.input_tokens
            )
            hosted_executed = any(
                getattr(item, "type", "") == "web_search_call"
                for item in response.output
            )
            if not hosted_executed:
                self.budget.input_headroom_ratio = min(
                    2.0, max(ratio, usage.input_tokens / base * 1.1)
                )
            else:
                event["output"]["hosted_input_expansion_unmeasured"] = True
        event["output"]["shared_spent_tokens"] = self.budget.spent
        if output_failure is not None:
            event["status"] = "rejected_final_output"
            event["output"]["final_output_error"] = str(output_failure)[:2000]
            recovery_key = purpose.value
            if (
                purpose != CompletionPurpose.OWNER
                or output_schema is None
                or output_schema.json_schema().get("title") != "GeneralModelOutput"
                or recovery_key in holder.final_output_recoveries
                or any(ledger.exhausted for ledger in ledgers)
            ):
                raise output_failure
            holder.final_output_recoveries.add(recovery_key)
            event["output"]["final_output_recovery"] = "one_tool_free_completion"
            recovery_input = [{"role": "user", "content": prepared}] if isinstance(prepared, str) else list(prepared)
            recovery_input.append({
                "role": "user",
                "content": "The previous final response was incomplete or invalid and was rejected. Return the complete requested final JSON contract. Research is closed. Reuse the retained research and complete buyer brief. Preserve the useful selected option set and its benefits and tradeoffs. Do not emit tool arguments or invent missing facts.",
            })
            recovery_token = _recovering_final_output.set(True)
            try:
                recovered = await self.get_response(
                    closure_instructions, recovery_input,
                    replace(model_settings, tool_choice=None, parallel_tool_calls=False),
                    [], output_schema, [], tracing,
                    previous_response_id=None, conversation_id=None, prompt=prompt,
                )
                recovered.usage.add(usage)
                return recovered
            except ContextBudgetExceeded:
                raise
            except Exception as exc:
                raise FinalOutputFailure("The bounded owner completion failed; no partial advice was accepted.") from exc
            finally:
                _recovering_final_output.reset(recovery_token)
        disallowed = {
            getattr(item, "name", None)
            for item in response.output
            if getattr(item, "type", "") == "function_call"
        }
        enabled = {tool.name for tool in tools} | {item.tool_name for item in handoffs}
        unadmitted_hosted = any(getattr(item, "type", "") == "web_search_call" for item in response.output) and "web_search" not in enabled
        if disallowed - enabled or unadmitted_hosted:
            event["status"] = "blocked_closed_research"
            holder.completion_plans.pop(plan_key, None)
            raise ContextBudgetExceeded(
                "The model requested research after its spending or tool budget closed."
            )
        if history is not None:
            history.record_response(response.output)
        if not disallowed:
            holder.completion_plans.pop(plan_key, None)
            holder.completion_checkpoints.pop(plan_key, None)
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
        model = self.provider.get_model(model_name)
        if isinstance(model, OpenAIChatCompletionsModel) or (
            isinstance(model, OpenAIResponsesModel) and type(model) is not OpenAIResponsesModel
        ):
            raise ContextBudgetExceeded("This OpenAI transport does not preserve response completion status safely.")
        if type(model) is OpenAIResponsesModel:
            model = EnvelopeResponsesModel(
                model.model, model._get_client(), model_is_explicit=model._model_is_explicit
            )
        return BudgetedModel(
            model, self.budget, model_name
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
