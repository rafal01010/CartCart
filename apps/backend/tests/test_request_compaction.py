import json

import pytest

from app.agents.context_metrics import measure
from app.agents.request_compaction import compact_to_tokens, plan_compaction
from app.agents.research_history import ResearchHistory


def test_projection_preserves_pairs_buyer_facts_and_late_caution():
    history = ResearchHistory()
    original = {
        "brief": {"original_query": "Exact wording " * 100, "region": "PH"},
        "source_id": "source-a",
        "url": "https://example.org/neutral",
        "price": {"amount": "2400.00", "currency": "PHP"},
        "quote": "Product A supports the requested feature.",
        "text": "Navigation and unrelated prose. " * 1200
        + "Warning: imported variant has no local warranty.",
    }
    items = [
        {
            "type": "function_call",
            "call_id": "fetch-a",
            "name": "fetch_source",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "fetch-a",
            "output": json.dumps(original),
        },
    ]
    projected = compact_to_tokens(plan_compaction(items, history), 3000)
    assert [item["call_id"] for item in projected] == ["fetch-a", "fetch-a"]
    payload = json.loads(projected[1]["output"])
    for key in ("brief", "price", "quote", "url"):
        assert payload[key] == original[key]
    context = payload["_context_projection"]
    assert context["material_cautions"] == [
        "Warning: imported variant has no local warranty."
    ]
    assert context["omitted_material_unreviewed"] is True
    handle = context["original_view_id"]
    assert (
        "Warning: imported variant has no local warranty."
        in history.read(handle, focus="imported variant")["text"]
    )
    assert history.views[handle].state is None
    assert measure(projected)["estimated_tokens"] < 3000


def test_stage_json_preserves_exact_support_and_safety():
    original = {
        "brief": {"original_query": "A lamp"},
        "evidence": [{"evidence_id": "e1", "claim": "Exact support"}],
        "category_analyses": [
            {"product_id": "p1", "rationale": "Repeated derivation. " * 5000}
        ],
        "trust_assessments": [{"listing_id": "l1", "red_flags": ["Suspicious seller"]}],
        "recommendation_bundle": {"final_rationale": "Exact final recommendation"},
    }
    payload = json.loads(
        compact_to_tokens(
            plan_compaction(json.dumps(original), ResearchHistory()), 1800
        )
    )
    for key in ("evidence", "trust_assessments", "recommendation_bundle"):
        assert payload[key] == original[key]
    assert payload["category_analyses"][0]["product_id"] == "p1"


def test_selector_only_accepts_exact_observed_offsets():
    plan = plan_compaction(
        json.dumps({"text": "Useful verified source passage. " * 500}),
        ResearchHistory(),
    )
    spans = plan.validate_spans('{"spans":[{"field_id":0,"start":0,"end":31}]}')
    assert (
        json.loads(plan.render(0, spans))["text"] == "Useful verified source passage."
    )
    for output in (
        '{"summary":"invented support"}',
        '{"spans":[{"field_id":0,"start":0,"end":5000}]}',
        '{"spans":[{"field_id":9,"start":0,"end":5}]}',
    ):
        with pytest.raises(ValueError):
            plan.validate_spans(output)


def test_exact_input_is_irreducible():
    history = ResearchHistory()
    exact = "x" * 100_000
    assert compact_to_tokens(plan_compaction(exact, history), 1000) == exact
    original = json.dumps({"brief": {"original_query": "x" * 100_000}})
    assert compact_to_tokens(plan_compaction(original, history), 1000) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["success", "invalid", "failure", "timeout"])
@pytest.mark.parametrize(
    "agent_name",
    [
        "IntakeAgent",
        "GuideAgent",
        "GeneralShoppingAgent",
        "TechnologyDomainAnalystAgent",
        "GenericProductAnalystAgent",
        "SourceIntelligenceManagerAgent",
        "DiscoveryAgent",
        "ExtractionAgent",
        "SellerListingTrustAgent",
        "CartCartComparisonDecisionAgent",
        "CartCartVerifierCriticAgent",
    ],
)
async def test_automatic_sdk_shortening_is_bounded_and_charged(
    behavior, agent_name, monkeypatch
):
    import asyncio
    from agents import Agent, ModelSettings, RunConfig
    from openai.types.shared import Reasoning
    from agents.items import ModelResponse
    from agents.models.interface import Model, ModelProvider
    from agents.usage import Usage
    from openai.types.responses import ResponseOutputMessage, ResponseOutputText
    from app.agents.context_management import (
        BoundedRunner,
        ContextBudget,
        context_scope,
    )

    monkeypatch.setattr(
        "app.agents.context_management.SHORTENING_TIMEOUT_SECONDS", 0.01
    )

    class Transport(Model):
        def __init__(self):
            self.inputs = []

        async def get_response(
            self,
            instructions,
            input,
            settings,
            tools,
            schema,
            handoffs,
            tracing,
            **kwargs,
        ):
            self.inputs.append((instructions, input))
            assert settings.reasoning == Reasoning(effort="low")
            assert settings.verbosity == "low"
            assert settings.extra_body == {"profile_marker": "retained"}
            selecting = (instructions or "").startswith("Select useful exact passages")
            if selecting:
                assert settings.max_tokens == 768
                assert settings.tool_choice is None
                assert settings.parallel_tool_calls is False
            if selecting and behavior == "failure":
                raise RuntimeError("private provider payload")
            if selecting and behavior == "timeout":
                await asyncio.sleep(1)
            text = (
                '{"spans":[{"field_id":0,"start":0,"end":26}]}'
                if selecting and behavior == "success"
                else "invalid summary"
                if selecting
                else "Supported bounded result."
            )
            return ModelResponse(
                output=[
                    ResponseOutputMessage(
                        id="m",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[
                            ResponseOutputText(
                                type="output_text", text=text, annotations=[]
                            )
                        ],
                    )
                ],
                usage=Usage(
                    requests=1, input_tokens=600, output_tokens=100, total_tokens=700
                ),
                response_id=None,
            )

        def stream_response(self, *args, **kwargs):
            raise AssertionError("Unexpected streaming")

    transport = Transport()

    class Provider(ModelProvider):
        def get_model(self, model_name):
            assert model_name == "configured-model"
            return transport

    budget = ContextBudget()
    with context_scope(budget):
        result = await BoundedRunner.run(
            Agent(
                name=agent_name,
                model="configured-model",
                model_settings=ModelSettings(
                    reasoning=Reasoning(effort="low"),
                    verbosity="low",
                    extra_body={"profile_marker": "retained"},
                    max_tokens=2500,
                ),
            ),
            json.dumps(
                {
                    "brief": {"original_query": "A lamp for reading", "region": "PH"},
                    "text": "Supported product passage. " * 4000
                    + "Warning: seller is unverified.",
                }
            ),
            run_config=RunConfig(model_provider=Provider(), tracing_disabled=True),
            max_turns=1,
        )
    assert result.final_output == "Supported bounded result."
    assert len(transport.inputs) == 2
    main = [event for event in budget.events if event["tool_name"] == "context_call"]
    rewrite = [
        event for event in budget.events if event["tool_name"] == "context_shortening"
    ]
    assert len(rewrite) == 1
    assert main[0]["output"]["estimated_input_tokens"] <= 19_000
    assert budget.shortening_calls == 1 and budget.reserved == 0
    assert (
        budget.spent == 1400
        if behavior in {"success", "invalid"}
        else budget.spent > 1400
    )
    context = json.loads(transport.inputs[-1][1][0]["content"])["_context_projection"]
    assert context["material_cautions"] == ["Warning: seller is unverified."]
    assert context["omitted_material_unreviewed"] is True
    assert "private provider payload" not in json.dumps(budget.events)


def test_long_assistant_blocks_keep_protocol_and_original_lookup():
    history = ResearchHistory()
    original = [
        {"type": "message", "role": "user", "content": "Exact buyer query"},
        {
            "type": "message",
            "id": "assistant-m",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "Past research narration. " * 5000
                    + "Warning: disputed warranty.",
                    "annotations": [],
                }
            ],
        },
        {
            "type": "function_call",
            "call_id": "transfer",
            "name": "transfer_to_technology",
            "arguments": '{"reason":"Exact transfer reason"}',
        },
    ]
    projected = compact_to_tokens(plan_compaction(original, history), 2000)
    assert projected[0] == original[0]
    assert projected[2] == original[2]
    assert projected[1]["id"] == "assistant-m"
    block = projected[1]["content"][0]
    assert block["type"] == "output_text" and block["annotations"] == []
    assert "Warning: disputed warranty." in block["text"]
    assert "omitted_material_unreviewed" in block["text"]
    assert measure(projected)["estimated_tokens"] < 2000


def test_omitted_page_text_does_not_authorize_quote_but_transport_reread_does():
    history = ResearchHistory()
    original = {
        "source_id": "source-a",
        "snapshot_id": "snapshot-a",
        "text": "Navigation. " * 5000
        + "Product A has a five year support promise. Warning: no local warranty.",
    }
    prepared = compact_to_tokens(plan_compaction(json.dumps(original), history), 1000)
    original_text = history.source_text(original)
    retained_text = history.source_text(prepared)
    history.compacted_sources.update(
        identity
        for identity, text in original_text.items()
        if text != retained_text.get(identity)
    )
    history.record_transport(prepared)
    assert not history.quote_visible(
        "source-a", "Product A has a five year support promise."
    )
    assert not history.quote_visible("source-a", "Warning: no local warranty.")
    history.record_transport(
        {
            "source_id": "source-a",
            "snapshot_id": "snapshot-a",
            "text": "Product A has a five year support promise.",
        }
    )
    assert history.quote_visible(
        "source-a", "Product A has a five year support promise."
    )
    assert history.quote_visible(
        "snapshot-a", "Product A has a five year support promise."
    )
    assert history.quote_visible(
        "uncompacted-source", "Direct tool validation is unchanged."
    )


@pytest.mark.asyncio
async def test_sdk_original_view_reread_unlocks_only_the_visible_source_quote():
    from agents import Agent, RunConfig, function_tool
    from app.agents.context_management import (
        BoundedRunner,
        ContextBudget,
        context_scope,
    )
    from app.agents.research_history import active_history, tracked_tools
    from test_context_management import ScriptModel, ScriptProvider, call

    quote = "Aster lamp has a five year support promise."
    original = {
        "sources": [
            {
                "source_id": "source-a",
                "snapshot_id": "snapshot-a",
                "text": "Navigation A. " * 6000 + quote,
            },
            {
                "source_id": "source-b",
                "snapshot_id": "snapshot-b",
                "text": "Navigation B. " * 6000 + quote,
            },
        ]
    }
    recorded = []

    @function_tool
    async def fetch_source(source_id: str) -> str:
        return json.dumps(original)

    @function_tool
    async def record_source_quote(source_id: str, exact_quote: str) -> str:
        history = active_history()
        assert history is not None
        assert history.quote_visible(source_id, exact_quote)
        assert history.quote_visible("snapshot-a", exact_quote)
        assert not history.quote_visible("source-b", exact_quote)
        assert not history.quote_visible("snapshot-b", exact_quote)
        recorded.append((source_id, exact_quote))
        return json.dumps(
            {"status": "succeeded", "source_id": source_id, "quote": exact_quote}
        )

    def reread(input, tools):
        outputs = [
            json.loads(item["output"])
            for item in input
            if item.get("type") == "function_call_output"
        ]
        view_id = outputs[-1]["sources"][0]["_context_projection"]["original_view_id"]
        history = active_history()
        assert history is not None and not history.quote_visible("source-a", quote)
        return call(
            "read_research_result", "reread-a", view_id=view_id, focus="Aster lamp"
        )

    class Transport(ScriptModel):
        async def get_response(
            self,
            instructions,
            input,
            settings,
            tools,
            schema,
            handoffs,
            tracing,
            **kwargs,
        ):
            if (instructions or "").startswith("Select useful exact passages"):
                selector = ScriptModel(['{"spans":[]}'])
                return await selector.get_response(
                    instructions,
                    input,
                    settings,
                    tools,
                    schema,
                    handoffs,
                    tracing,
                    **kwargs,
                )
            return await super().get_response(
                instructions,
                input,
                settings,
                tools,
                schema,
                handoffs,
                tracing,
                **kwargs,
            )

    model = Transport(
        [
            call("fetch_source", "fetch-a", source_id="source-a"),
            reread,
            call(
                "record_source_quote",
                "quote-a",
                source_id="source-a",
                exact_quote=quote,
            ),
            "Exact original support recorded.",
        ]
    )
    with context_scope(ContextBudget()):
        result = await BoundedRunner.run(
            Agent(
                name="GeneralShoppingAgent",
                model="configured",
                tools=list(tracked_tools((fetch_source, record_source_quote))),
            ),
            "Find a reading lamp.",
            run_config=RunConfig(
                model_provider=ScriptProvider({"configured": model}),
                tracing_disabled=True,
            ),
            max_turns=5,
        )
    assert result.final_output == "Exact original support recorded."
    assert recorded == [("source-a", quote)]


def test_original_view_decodes_exact_escaped_source_text_without_caution_authority():
    history = ResearchHistory()
    quote = 'Lamp "A" supports reading.\nNo warranty promise.'
    original = {
        "source_id": "a",
        "text": "Earlier prose. " * 500 + quote,
        "cautions": [{"source_id": "a", "text": "A caution is not source support."}],
    }
    registered = json.loads(
        history.register("fetch_source", json.dumps(original), force=True)
    )
    view_id = registered["_research_view"]["view_id"]
    history.compacted_sources.add("a")
    reread = history.read(view_id, focus="supports reading")
    history.record_transport(reread)
    assert history.quote_visible("a", quote)
    assert not history.quote_visible("a", "A caution is not source support.")


@pytest.mark.parametrize(
    "tool_name", ["fetch_source", "read_source_snapshot", "read_research_result"]
)
def test_focused_exact_passage_survives_small_fallback_and_optional_selection(
    tool_name,
):
    history = ResearchHistory()
    quote = "Aster lamp has a five year support promise. No local warranty."
    text = "Before focus. " * 40 + quote + " Following unrelated prose." * 500
    items = [
        {
            "type": "function_call",
            "call_id": "focus-read",
            "name": tool_name,
            "arguments": json.dumps({"focus": "Aster lamp"}),
        },
        {
            "type": "function_call_output",
            "call_id": "focus-read",
            "output": json.dumps({"source_id": "a", "text": text}),
        },
    ]
    plan = plan_compaction(items, history)
    assert plan.required_spans
    optional = plan.validate_spans('{"spans":[{"field_id":0,"start":0,"end":10}]}')
    for spans in (None, optional):
        projected = plan.render(0, spans)
        payload = json.loads(projected[1]["output"])
        assert quote in payload["text"]
        assert payload["_context_projection"]["omitted_material_unreviewed"] is True


@pytest.mark.asyncio
async def test_repeated_context_pressure_caps_rewriting_and_continues_with_fallback():
    from agents import Agent, RunConfig
    from app.agents.context_management import (
        BoundedRunner,
        ContextBudget,
        context_scope,
    )
    from test_context_management import ScriptModel, ScriptProvider

    class Transport(ScriptModel):
        def __init__(self):
            super().__init__(
                ['{"spans":[]}', "Supported decision."] * 3
                + ["Supported decision."] * 2,
                actual=500,
            )
            self.rewrites = 0
            self.main = 0

        async def get_response(
            self,
            instructions,
            input,
            settings,
            tools,
            schema,
            handoffs,
            tracing,
            **kwargs,
        ):
            if (instructions or "").startswith("Select useful exact passages"):
                self.rewrites += 1
            else:
                self.main += 1
            return await super().get_response(
                instructions,
                input,
                settings,
                tools,
                schema,
                handoffs,
                tracing,
                **kwargs,
            )

    model = Transport()
    budget = ContextBudget()
    with context_scope(budget):
        for index in range(5):
            result = await BoundedRunner.run(
                Agent(name="GeneralShoppingAgent", model="configured"),
                json.dumps(
                    {
                        "brief": {"original_query": "A lamp"},
                        "text": (f"Unique context {index}. " * 5000),
                    }
                ),
                run_config=RunConfig(
                    model_provider=ScriptProvider({"configured": model}),
                    tracing_disabled=True,
                ),
                max_turns=1,
            )
            assert result.final_output == "Supported decision."
            assert budget.reserved == 0
    assert model.rewrites == 3
    assert model.main == 5
    assert budget.shortening_calls == 3
    assert budget.spent == 4800
    assert (
        budget.spent
        + budget.limits.decision_reserve
        + budget.limits.verification_reserve
        < budget.limits.total_tokens
    )
    events = [event for event in budget.events if event["tool_name"] == "context_call"]
    assert len(events) == 5
    assert all(event["output"]["estimated_input_tokens"] <= 19_000 for event in events)
    assert [event["output"]["compaction"]["status"] for event in events[-2:]] == [
        "deterministic_fallback",
        "deterministic_fallback",
    ]
