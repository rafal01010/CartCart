import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from agents import Agent, ModelSettings, RunConfig, function_tool, handoff
from agents.items import ModelResponse
from agents.models.interface import Model, ModelProvider
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from app.agents.context_management import (
    BoundedRunner,
    ContextBudget,
    ContextBudgetExceeded,
    ContextLimits,
    active_budget,
    compact_json,
    context_scope,
    prepare_history,
)
from app.agents.context_metrics import measure
from app.agents.source_spans import source_span
from app.agents.contracts import (
    ComparisonDecisionAgentInput,
    VerificationAgentInput,
    VerificationReport,
)
from app.agents.live_comparison_decision import LiveComparisonDecisionAgent
from app.agents.live_verifier_critic import LiveVerifierCriticAgent
from app.agents.workbench import (
    _scenario_comparison_monitor_shortlist,
    _scenario_verifier_approved,
)
from app.core.settings import Settings
from app.schemas.analysis import (
    ComparisonCriterion,
    ComparisonMatrix,
    ComparisonRow,
    RecommendationBundle,
)


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/context_research.json").read_text()
)


def message(text: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id="message",
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )


class ScriptModel(Model):
    def __init__(self, steps: list[Any], *, actual: int | None = None):
        self.steps = list(steps)
        self.inputs: list[Any] = []
        self.actual = actual

    async def get_response(
        self,
        instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        **kwargs,
    ):
        self.inputs.append(input)
        step = self.steps.pop(0)
        if callable(step):
            step = step(input, tools)
        if isinstance(step, BaseException):
            raise step
        output = [message(step)] if isinstance(step, str) else step
        tokens = (
            self.actual
            or measure(input)["estimated_tokens"]
            + measure(instructions or "")["estimated_tokens"]
            + 500
        )
        return ModelResponse(
            output=output,
            usage=Usage(
                requests=1,
                input_tokens=tokens,
                output_tokens=100,
                total_tokens=tokens + 100,
            ),
            response_id=None,
        )

    def stream_response(self, *args, **kwargs):
        raise AssertionError("No streaming in these offline tests.")


class ScriptProvider(ModelProvider):
    def __init__(self, models: dict[str, ScriptModel]):
        self.models = models

    def get_model(self, model_name):
        return self.models[model_name]


def call(name: str, call_id: str, **args) -> list[ResponseFunctionToolCall]:
    return [
        ResponseFunctionToolCall(
            id=call_id,
            call_id=call_id,
            type="function_call",
            name=name,
            arguments=json.dumps(args),
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["phone", "generic", "refinement"])
async def test_sdk_replay_retrieves_bounded_support_and_retains_handoffs(
    scenario: str,
) -> None:
    quotes = [
        FIXTURE[k]
        for k in (
            "official_quote",
            "review_quote",
            "conflict_quote",
            "seller_warning",
            "launch_warning",
            "source_gap",
        )
    ]
    if scenario != "phone":
        quotes += [
            FIXTURE["generic_quote"],
            "Separate premium offer costs PHP 4999.00.",
        ]
    recorded = []
    canonical = {
        str(i): ("Navigation and unrelated prose. " * 350) + quote
        for i, quote in enumerate(quotes)
    }

    @function_tool
    async def fetch_source(source_id: str) -> str:
        return json.dumps(
            {
                "source_id": source_id,
                "snapshot_id": source_id,
                "text": source_span(
                    canonical[source_id], focus=quotes[int(source_id)], limit=1600
                ).text,
                "gap": None,
                "status": "succeeded",
                "url": "https://example.org/review",
            }
        )

    @function_tool
    async def record_source_quote(source_id: str, quote: str) -> str:
        assert quote in canonical[source_id]
        recorded.append(quote)
        return json.dumps(
            {
                "source_id": source_id,
                "evidence_id": f"e{source_id}",
                "quote": quote,
                "status": "succeeded",
            }
        )

    expected = (
        FIXTURE["phone_decision"]
        if scenario == "phone"
        else FIXTURE["generic_decision"]
    )

    def finish(input, tools):
        text = json.dumps(input)
        assert all(quote in text for quote in quotes)
        assert (
            FIXTURE["original_query"] in text if scenario == "phone" else "3000" in text
        )
        return [message(expected)]

    steps = []
    for i, quote in enumerate(quotes):
        steps.extend(
            (
                call("fetch_source", f"read{i}", source_id=str(i)),
                call("record_source_quote", f"quote{i}", source_id=str(i), quote=quote),
            )
        )
    steps.append(finish)
    model = ScriptModel(steps)
    phone = Agent(
        name="SmartphoneSpecialistAgent"
        if scenario == "phone"
        else "GenericProductAnalystAgent",
        model="research",
        tools=[fetch_source, record_source_quote],
        model_settings=ModelSettings(max_tokens=1500),
    )
    if scenario == "phone":
        tech_handoff = handoff(phone)
        tech = Agent(
            name="TechnologyDomainAnalystAgent",
            model="technology",
            handoffs=[tech_handoff],
        )
        general_handoff = handoff(tech)
        agent = Agent(
            name="GeneralShoppingAgent", model="general", handoffs=[general_handoff]
        )
        models = {
            "general": ScriptModel([call(general_handoff.tool_name, "handoff1")]),
            "technology": ScriptModel([call(tech_handoff.tool_name, "handoff2")]),
            "research": model,
        }
    else:
        agent, models = phone, {"research": model}
    input = json.dumps(
        {
            "original_query": FIXTURE["original_query"]
            if scenario == "phone"
            else FIXTURE["generic_query"],
            "region": "PH",
            "budget": None
            if scenario == "phone"
            else {"amount": "3000", "mode": "hard_cap"},
            "prior_region": "US" if scenario == "refinement" else None,
        }
    )
    budget = ContextBudget()
    with context_scope(budget):
        result = await BoundedRunner.run(
            agent,
            input,
            run_config=RunConfig(
                model_provider=ScriptProvider(models), tracing_disabled=True
            ),
            max_turns=25,
        )
    assert result.final_output == expected
    assert recorded == quotes
    assert budget.spent < 90_000
    assert max(e["output"]["estimated_input_tokens"] for e in budget.events) < 16_000
    assert sum(len(text) for text in canonical.values()) > 60_000
    assert budget.events[-1]["output"]["after_input"]["characters"] < 25_000
    assert canonical["0"].endswith(FIXTURE["official_quote"])
    if scenario == "phone":
        assert result.last_agent.name == "SmartphoneSpecialistAgent"
        assert [e["input"]["agent"] for e in budget.events[:2]] == [
            "GeneralShoppingAgent",
            "TechnologyDomainAnalystAgent",
        ]


@pytest.mark.asyncio
async def test_nested_sdk_agent_calls_are_charged_once() -> None:
    child = Agent(name="YouTubeReviewIntelligenceAgent", model="child")
    parent = Agent(
        name="SourceIntelligenceManagerAgent",
        model="parent",
        tools=[
            child.as_tool(
                tool_name="consult_video", tool_description="Read video evidence."
            )
        ],
    )
    parent_model = ScriptModel(
        [
            call("consult_video", "nested", input="Check exact review support."),
            "Cited video caveat retained.",
        ],
        actual=400,
    )
    child_model = ScriptModel(
        ["Exact timestamped caveat, with sponsorship warning."], actual=600
    )
    budget = ContextBudget()
    with context_scope(budget):
        result = await BoundedRunner.run(
            parent,
            "Need phone reviews.",
            run_config=RunConfig(
                model_provider=ScriptProvider(
                    {"parent": parent_model, "child": child_model}
                ),
                tracing_disabled=True,
            ),
            max_turns=4,
        )
    assert result.final_output == "Cited video caveat retained."
    assert budget.spent == 1700
    assert [event["input"]["agent"] for event in budget.events] == [
        "SourceIntelligenceManagerAgent",
        "YouTubeReviewIntelligenceAgent",
        "SourceIntelligenceManagerAgent",
    ]


@pytest.mark.asyncio
async def test_oversized_exact_input_blocks_transport() -> None:
    model = ScriptModel(["must not be used"])
    budget = ContextBudget()
    with (
        context_scope(budget),
        pytest.raises(ContextBudgetExceeded, match="Model input"),
    ):
        await BoundedRunner.run(
            Agent(name="VerifierCriticAgent", model="verify"),
            "x" * 100_000,
            run_config=RunConfig(
                model_provider=ScriptProvider({"verify": model}), tracing_disabled=True
            ),
            max_turns=1,
        )
    assert budget.events[0]["status"] == "blocked"
    assert len(model.steps) == 1


@pytest.mark.asyncio
async def test_exhaustion_and_transport_failure_cannot_retry_spending() -> None:
    model = ScriptModel([RuntimeError("private provider payload"), "second request"])
    budget = ContextBudget(limits=replace(ContextLimits(), total_tokens=13_000))
    with context_scope(budget):
        with pytest.raises(RuntimeError, match="private provider"):
            await BoundedRunner.run(
                Agent(name="VerifierCriticAgent", model="verify"),
                "request",
                run_config=RunConfig(
                    model_provider=ScriptProvider({"verify": model}),
                    tracing_disabled=True,
                ),
                max_turns=1,
            )
        # Unknown failed usage is retained, so another call cannot consume the same allocation.
        budget.limits = replace(budget.limits, total_tokens=budget.spent)
        with pytest.raises(ContextBudgetExceeded):
            await BoundedRunner.run(
                Agent(name="VerifierCriticAgent", model="verify"),
                "retry",
                run_config=RunConfig(
                    model_provider=ScriptProvider({"verify": model}),
                    tracing_disabled=True,
                ),
                max_turns=1,
            )
    assert budget.events[0]["status"] == "failed_reserved"
    assert budget.spent > 5000
    assert len(model.steps) == 1
    assert "private provider payload" not in json.dumps(budget.events)


@pytest.mark.asyncio
async def test_concurrent_and_cancelled_contexts_do_not_share_state_or_create_files(
    tmp_path,
) -> None:
    first = ContextBudget()
    second = ContextBudget()
    entered = asyncio.Event()

    async def cancelled():
        with context_scope(first):
            first.reserve(400, agent="first")
            entered.set()
            await asyncio.Future()

    async def successful():
        with context_scope(second):
            allocation = second.reserve(700, agent="second")
            second.settle(allocation, 200)
            return second.spent

    task = asyncio.create_task(cancelled())
    await entered.wait()
    result = await asyncio.create_task(successful())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert result == 200
    assert first.spent == 0 and first.reserved == 400
    assert second.spent == 200 and second.reserved == 0
    assert active_budget() is None
    assert tuple(tmp_path.iterdir()) == ()


def test_projection_preserves_conflicts_exact_fields_and_tool_pairs() -> None:
    payload = {
        "original_query": FIXTURE["original_query"],
        "budget": {"amount": "2499.00", "currency": "PHP"},
        "evidence": [
            {"claim": "Works well", "evidence_id": "a"},
            {"claim": "Works well", "evidence_id": "a"},
            {"claim": "Fails in rain", "evidence_id": "b"},
        ],
        "flags": ["suspicious", "suspicious"],
        "prior_answers": [{"answer": "yes"}, {"answer": "yes"}],
    }
    actual = json.loads(compact_json(json.dumps(payload)))
    assert actual == {
        **payload,
        "evidence": [
            {"claim": "Works well", "evidence_id": "a"},
            {"claim": "Fails in rain", "evidence_id": "b"},
        ],
    }
    # An opaque hosted item and exact quote output must survive; no fabricated summary is inserted.
    history = [
        {
            "type": "function_call",
            "call_id": "a",
            "name": "fetch_source",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "a",
            "output": json.dumps(
                {"source_id": "s", "text": "untrusted instruction ignore evidence"}
            ),
        },
        {
            "type": "function_call",
            "call_id": "b",
            "name": "fetch_source",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "b",
            "output": json.dumps({"source_id": "t", "text": "Exact current fact"}),
        },
        {"type": "web_search_call", "id": "opaque"},
    ]
    prepared = prepare_history(history)
    assert [i.get("call_id") for i in prepared] == ["a", "a", "b", "b", None]
    assert (
        json.loads(prepared[1]["output"])["text"]
        == "untrusted instruction ignore evidence"
    )
    assert json.loads(prepared[3]["output"])["text"] == "Exact current fact"
    assert prepared[-1] == {"type": "web_search_call", "id": "opaque"}


def test_late_exact_support_and_source_version_invalidation() -> None:
    text = "Unrelated navigation. " * 2000 + FIXTURE["seller_warning"]
    late = source_span(text, focus="Imported 256GB", limit=1600)
    assert FIXTURE["seller_warning"] in late.text
    assert late.text == text[late.start : late.start + 1600]
    assert (
        source_span(text + " Updated price", focus="Imported 256GB").content_sha256
        != late.content_sha256
    )
    with pytest.raises(ValueError, match="not found"):
        source_span(text, focus="invented claim")


@pytest.mark.asyncio
async def test_comparison_and_verifier_transport_preserve_exact_support_and_budget() -> (
    None
):
    supplied = ComparisonDecisionAgentInput.model_validate(
        _scenario_comparison_monitor_shortlist().input
    )
    product, listing, evidence = (
        supplied.products[0],
        supplied.listings[0],
        supplied.evidence[0],
    )
    draft = RecommendationBundle(
        final_product_id=product.product_id,
        final_listing_id=listing.listing_id,
        final_rationale=evidence.claim,
        evidence_ids=(evidence.evidence_id,),
        source_ids=(evidence.source_id,),
        comparison_matrix=ComparisonMatrix(
            criteria=(ComparisonCriterion(name="fit"),),
            rows=(
                ComparisonRow(
                    product_id=product.product_id,
                    listing_id=listing.listing_id,
                    scores={"fit": 0.82},
                    evidence_ids=(evidence.evidence_id,),
                    summary=evidence.claim,
                ),
            ),
        ),
    )
    model = ScriptModel([draft.model_dump_json()])
    provider = ScriptProvider({"fixture": model})

    class OfflineSDKRunner:
        async def run(self, agent, model_input, *, run_config, max_turns):
            return await BoundedRunner.run(
                agent,
                model_input,
                run_config=replace(
                    run_config, model_provider=provider, tracing_disabled=True
                ),
                max_turns=max_turns,
            )

    settings = Settings(
        _env_file=None,
        environment="test",
        openai_model="fixture",
        live_agents_enabled=False,
        openai_api_key=None,
    )
    budget = ContextBudget()
    with context_scope(budget):
        comparison = LiveComparisonDecisionAgent(
            settings, model_runner=OfflineSDKRunner()
        )
        bundle = await comparison.run(supplied)
        assert bundle.final_product_id == product.product_id
        assert product.name == "Dell UltraSharp U2724DE"
        assert not bundle.no_strong_buy
        verification = VerificationAgentInput(
            run_id=supplied.run_id,
            brief=supplied.brief,
            recommendation_bundle=bundle,
            products=supplied.products,
            listings=supplied.listings,
            evidence=supplied.evidence,
            trust_assessments=supplied.trust_assessments,
            category_analyses=supplied.category_analyses,
        )
        model.steps.append(
            VerificationReport(
                approved=True, recommendation_bundle=bundle
            ).model_dump_json()
        )
        report = await LiveVerifierCriticAgent(
            settings, model_runner=OfflineSDKRunner()
        ).run(verification)
    assert not report.approved
    assert report.blocking_issues == (
        "best_value rationale includes a factual claim not backed by its evidence.",
        "within_budget rationale includes a factual claim not backed by its evidence.",
        "runner_up rationale includes a factual claim not backed by its evidence.",
    )
    assert report.recommendation_bundle.final_product_id == product.product_id
    assert [event["status"] for event in budget.events] == ["completed", "completed"]
    assert (
        comparison.workbench_activity[0]["status"]
        == "model_comparison_decision_completed"
    )
    actual_input = json.loads(model.inputs[-1][0]["content"])
    assert (
        actual_input["evidence"][0]["claim"]
        == "Dell U2724DE has QHD resolution, USB-C hub features, and ergonomic stand."
    )
    assert actual_input["listings"][0]["price"] == {
        "amount": "289.99",
        "currency": "USD",
    }
    assert budget.spent < 90_000
    safe = VerificationAgentInput.model_validate(_scenario_verifier_approved().input)
    model.steps.append(
        VerificationReport(
            approved=True, recommendation_bundle=safe.recommendation_bundle
        ).model_dump_json()
    )
    with context_scope(budget):
        approved = await LiveVerifierCriticAgent(
            settings, model_runner=OfflineSDKRunner()
        ).run(safe)
    assert approved.approved
    assert (
        approved.recommendation_bundle.final_product_id == safe.products[0].product_id
    )


@pytest.mark.asyncio
async def test_exhausted_tool_is_not_executed_or_repeated() -> None:
    @function_tool
    async def search_sources(query: str) -> str:
        return json.dumps(
            {"status": "budget_exhausted", "gap": "Search limit reached."}
        )

    def repeats(input, tools):
        assert [tool.name for tool in tools] == []
        return call("search_sources", "forbidden", query="Try again")

    model = ScriptModel(
        [
            call("search_sources", "first", query="Scoped research"),
            repeats,
            "must not be called",
        ]
    )
    budget = ContextBudget()
    with context_scope(budget), pytest.raises(ContextBudgetExceeded, match="closed"):
        await BoundedRunner.run(
            Agent(
                name="GeneralShoppingAgent", model="research", tools=[search_sources]
            ),
            "Need a lamp.",
            run_config=RunConfig(
                model_provider=ScriptProvider({"research": model}),
                tracing_disabled=True,
            ),
            max_turns=5,
        )
    assert [event["status"] for event in budget.events] == [
        "completed",
        "blocked_closed_research",
    ]
    assert len(model.steps) == 1


@pytest.mark.asyncio
async def test_actual_usage_breach_is_a_backstop_and_stops_all_future_calls() -> None:
    model = ScriptModel(["too costly", "must not run"], actual=90_001)
    budget = ContextBudget(limits=replace(ContextLimits(), total_tokens=90_000))
    config = RunConfig(
        model_provider=ScriptProvider({"research": model}), tracing_disabled=True
    )
    with context_scope(budget):
        with pytest.raises(ContextBudgetExceeded, match="Actual"):
            await BoundedRunner.run(
                Agent(name="GeneralShoppingAgent", model="research"),
                "Need a lamp.",
                run_config=config,
                max_turns=1,
            )
        with pytest.raises(ContextBudgetExceeded):
            await BoundedRunner.run(
                Agent(name="VerifierCriticAgent", model="research"),
                "Continue",
                run_config=config,
                max_turns=1,
            )
    assert budget.spent == 90_101
    assert budget.events[0]["status"] == "blocked_actual_usage"
    assert len(model.steps) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,total", [("owner", 86_000), ("source", 27_000)])
async def test_existing_owner_and_nested_source_ceiling_blocks_before_second_call(
    scope, total
):
    from app.agents.context_management import (
        managed_owner_context,
        managed_source_context,
    )

    model = ScriptModel(["First exact result", "must not run"], actual=total)
    budget = ContextBudget()
    config = RunConfig(
        model_provider=ScriptProvider({"bounded": model}), tracing_disabled=True
    )
    decorator = managed_owner_context if scope == "owner" else managed_source_context

    @decorator
    async def work():
        for name in (
            "SourceIntelligenceManagerAgent",
            "YouTubeReviewIntelligenceAgent",
        ):
            await BoundedRunner.run(
                Agent(name=name, model="bounded"),
                "Exact source request",
                run_config=config,
                max_turns=1,
            )

    with context_scope(budget), pytest.raises(ContextBudgetExceeded):
        await work()
    assert len(model.inputs) == 1
    assert budget.spent == total + 100
    assert budget.spent < 150_000
    assert budget.events[-1]["status"] == "blocked"


@pytest.mark.asyncio
async def test_research_closes_and_preserves_funds_for_decision_and_verification():
    @function_tool
    async def research_more(query: str) -> str:
        raise AssertionError("Research must be closed.")

    research_more.description = "Large research contract. " * 300

    def finish(input, tools):
        assert tools == []
        assert "Unverified imported seller" in json.dumps(input)
        return [
            message("Useful qualified suggestion; imported seller remains unverified.")
        ]

    model = ScriptModel([finish], actual=500)
    models = {
        "bounded": model,
        "ComparisonDecisionAgent": ScriptModel(["Qualified decision"], actual=15000),
        "VerifierCriticAgent": ScriptModel(["Exact support verified"], actual=15000),
    }
    config = RunConfig(model_provider=ScriptProvider(models), tracing_disabled=True)
    budget = ContextBudget(limits=replace(ContextLimits(), total_tokens=50_000))
    with context_scope(budget):
        result = await BoundedRunner.run(
            Agent(
                name="GeneralShoppingAgent",
                model="bounded",
                tools=[research_more],
                model_settings=ModelSettings(max_tokens=1000),
            ),
            "Unverified imported seller",
            run_config=config,
            max_turns=1,
        )
        for name in ("ComparisonDecisionAgent", "VerifierCriticAgent"):
            await BoundedRunner.run(
                Agent(
                    name=name,
                    model=name,
                    model_settings=ModelSettings(max_tokens=5000),
                ),
                "Exact source support. " + "x" * 35500,
                run_config=config,
                max_turns=1,
            )
    assert (
        result.final_output
        == "Useful qualified suggestion; imported seller remains unverified."
    )
    assert budget.events[0]["output"]["finalizing"] is True
    assert budget.spent == 30800
    assert all(
        14000 < e["output"]["estimated_input_tokens"] < 16000 for e in budget.events[1:]
    )
    assert budget.reserved == 0


@pytest.mark.asyncio
async def test_cancelled_transport_consumes_reservation_and_leaves_no_scratch(tmp_path):
    entered = asyncio.Event()

    class WaitingModel(ScriptModel):
        async def get_response(self, *args, **kwargs):
            entered.set()
            await asyncio.Future()

    model = WaitingModel([])
    budget = ContextBudget()

    async def work():
        with context_scope(budget):
            await BoundedRunner.run(
                Agent(name="VerifierCriticAgent", model="bounded"),
                "Exact request",
                run_config=RunConfig(
                    model_provider=ScriptProvider({"bounded": model}),
                    tracing_disabled=True,
                ),
                max_turns=1,
            )

    task = asyncio.create_task(work())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert budget.spent >= 5000
    assert budget.reserved == 0
    assert budget.events[0]["status"] == "cancelled_reserved"
    assert active_budget() is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_offline_audit_captures_every_contract_without_transport_or_raw_payload(
    monkeypatch,
):
    import httpx
    from agents import Runner
    from app.tools.audit_context import audit

    async def forbidden(*args, **kwargs):
        raise AssertionError("Audit must not execute SDK or network calls.")

    monkeypatch.setattr(Runner, "run", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    report = await audit()
    assert len(report["inventory"]) == 25
    assert len(report["calls"]) == 25
    assert all(call["actual_tokens"] is None for call in report["calls"])
    assert report["historical_per_turn_tokens"] is None
    graph = [
        call["receiving_handoff_contracts"]
        for call in report["calls"]
        if call["receiving_handoff_contracts"]
    ]
    assert len(graph) == 1 and len(graph[0]) == 7
    assert report["history_audit"]["before"]["characters"] == 95276
    assert report["history_audit"]["after"]["characters"] > 90_000
    assert report["retrieval_audit"]["bounded_views"]["characters"] < 15_000
    assert report["duplicate_history_audit"]["after"]["characters"] < 20_000
    assert "Navigation and unrelated prose." not in json.dumps(report)


def test_a_prior_quote_cannot_hide_a_later_read_or_another_unquoted_source():
    history = [
        {
            "type": "function_call",
            "call_id": "first",
            "name": "fetch_source",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "first",
            "output": json.dumps({"source_id": "s", "text": "Exact price fact"}),
        },
        {
            "type": "function_call",
            "call_id": "quote",
            "name": "record_source_quote",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "quote",
            "output": json.dumps(
                {"status": "succeeded", "source_id": "s", "quote": "Exact price fact"}
            ),
        },
        {
            "type": "function_call",
            "call_id": "late",
            "name": "fetch_source",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "late",
            "output": json.dumps(
                {
                    "source_id": "s",
                    "text": "Late warranty exclusion",
                    "start_char": 9000,
                }
            ),
        },
        {
            "type": "function_call",
            "call_id": "other",
            "name": "fetch_source",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "other",
            "output": json.dumps(
                {"source_id": "other", "text": "Unquoted conflicting review"}
            ),
        },
    ]
    prepared = prepare_history(history)
    assert json.loads(prepared[1]["output"])["deferred_text"]["characters"] == 16
    assert json.loads(prepared[5]["output"])["text"] == "Late warranty exclusion"
    assert json.loads(prepared[7]["output"])["text"] == "Unquoted conflicting review"
    assert prepare_history(prepared) == prepared


@pytest.mark.parametrize("warning_in_same_read", [False, True])
def test_partial_quote_never_erases_unrepresented_warning(warning_in_same_read):
    history = []
    texts = (
        ["Price PHP 90000. No local warranty."]
        if warning_in_same_read
        else ["Price PHP 90000.", "No local warranty."]
    )
    for index, text in enumerate(texts):
        history.extend(
            [
                {
                    "type": "function_call",
                    "name": "fetch_source",
                    "call_id": str(index),
                    "arguments": "{}",
                },
                {
                    "type": "function_call_output",
                    "call_id": str(index),
                    "output": json.dumps({"source_id": "s", "text": text}),
                },
            ]
        )
    history.extend(
        [
            {
                "type": "function_call",
                "name": "record_source_quote",
                "call_id": "q",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "q",
                "output": json.dumps(
                    {
                        "status": "succeeded",
                        "source_id": "s",
                        "quote": "Price PHP 90000.",
                    }
                ),
            },
        ]
    )
    prepared = prepare_history(history)
    assert "No local warranty." in json.dumps(prepared)
    assert len(prepared) == len(history)
    assert prepare_history(prepared) == prepared


def test_repeated_read_preserves_one_exact_body_with_unquoted_warnings():
    history = []
    for index in range(3):
        history.extend(
            [
                {
                    "type": "function_call",
                    "name": "fetch_source",
                    "call_id": str(index),
                    "arguments": "{}",
                },
                {
                    "type": "function_call_output",
                    "call_id": str(index),
                    "output": json.dumps(
                        {
                            "source_id": "s",
                            "start_char": 4000,
                            "text": "Price PHP 90000. No local warranty.",
                        }
                    ),
                },
            ]
        )
    prepared = prepare_history(history)
    assert sum("No local warranty." in item.get("output", "") for item in prepared) == 1
    assert (
        json.loads(prepared[-1]["output"])["text"]
        == "Price PHP 90000. No local warranty."
    )
    assert len(prepared) == 6
    assert prepare_history(prepared) == prepared


def test_focused_source_read_can_advance_past_an_earlier_match():
    text = "Warranty included. " + "x" * 5000 + "Warranty excludes imported variants."
    first = source_span(text, focus="Warranty", limit=1000)
    later = source_span(
        text, start=first.start + len(first.text), focus="Warranty", limit=1000
    )
    assert "Warranty excludes imported variants." in later.text
    assert later.start > first.start
    assert text[later.start : later.start + len(later.text)] == later.text
    assert later.content_sha256 == first.content_sha256


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "YouTubeReviewIntelligenceAgent",
        "RedditCommunityIntelligenceAgent",
        "AmazonProductIntelligenceAgent",
        "IKEAStoreIntelligenceAgent",
    ],
)
async def test_source_specialists_propagate_sdk_wrapped_budget_failure(name):
    from agents.exceptions import UserError
    from app.agents.catalog import DEFAULT_AGENT_CATALOG
    from app.agents.workbench import _build_workbench_definitions

    class FailingRunner:
        async def run(self, *args, **kwargs):
            try:
                raise ContextBudgetExceeded("Cannot fund exact support.")
            except ContextBudgetExceeded as cause:
                raise UserError("SDK function tool failed") from cause

    definition = _build_workbench_definitions(DEFAULT_AGENT_CATALOG)[name]
    supplied = definition.input_model.model_validate(definition.scenarios[0].input)
    agent = definition.mock_agent_factory(Settings(_env_file=None, environment="test"))
    agent.model_runner = FailingRunner()
    with pytest.raises(ContextBudgetExceeded, match="Cannot fund exact support"):
        await agent.run(supplied)


@pytest.mark.asyncio
async def test_exhausted_parent_tool_does_not_disable_fresh_child_quota() -> None:
    executions = []

    @function_tool(name_override="search_sources")
    async def parent_search(query: str) -> str:
        executions.append("parent")
        return json.dumps(
            {"status": "budget_exhausted", "gap": "Parent search quota closed."}
        )

    @function_tool(name_override="search_sources")
    async def child_search(query: str) -> str:
        executions.append("child")
        return json.dumps({"status": "succeeded", "source_id": "fresh-child-source"})

    child = Agent(name="TechnologyShoppingAgent", model="child", tools=[child_search])
    transfer = handoff(child)

    def parent_finish(input, tools):
        assert not tools
        return call(transfer.tool_name, "handoff")

    def child_continue(input, tools):
        assert [tool.name for tool in tools] == ["search_sources"]
        assert "Parent search quota closed." in json.dumps(input)
        return call("search_sources", "child-search", query="Fresh child research")

    parent_model = ScriptModel(
        [
            call("search_sources", "parent-search", query="Parent research"),
            parent_finish,
        ],
        actual=1000,
    )
    child_model = ScriptModel(
        [child_continue, "Child research completed."], actual=1000
    )
    with context_scope(ContextBudget()):
        result = await BoundedRunner.run(
            Agent(
                name="GeneralShoppingAgent",
                model="parent",
                tools=[parent_search],
                handoffs=[transfer],
            ),
            "Compare phones.",
            run_config=RunConfig(
                model_provider=ScriptProvider(
                    {"parent": parent_model, "child": child_model}
                ),
                tracing_disabled=True,
            ),
            max_turns=5,
        )
    assert result.final_output == "Child research completed."
    assert executions == ["parent", "child"]
