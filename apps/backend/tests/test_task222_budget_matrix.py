import asyncio
import json
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

import pytest
from agents import ModelSettings, WebSearchTool
from agents.agent_output import AgentOutputSchema
from agents.items import ModelResponse
from agents.models.interface import Model, ModelTracing
from agents.tool import FunctionTool
from agents.usage import Usage
from openai.types.responses import ResponseFunctionWebSearch

import app.agents.context_management as cm
from app.agents.catalog import ProductAnalysisRoute
from app.agents.contracts import ExtractionAgentOutput
from app.agents.live_amazon_product_intelligence import AmazonProductModelOutput
from app.agents.live_discovery import DiscoveryModelOutput
from app.agents.live_general_shopping import GeneralModelOutput
from app.agents.live_ikea_store_intelligence import IKEAStoreModelOutput
from app.agents.live_reddit_community_intelligence import RedditCommunityModelOutput
from app.agents.live_seller_listing_trust import SellerListingTrustModelOutput
from app.agents.live_source_intelligence_manager import SourceManagerDecision
from app.agents.live_verifier_critic import _VerifierModelDecision
from app.agents.live_youtube_review_intelligence import YouTubeReviewModelOutput
from app.schemas.analysis import CategoryAnalysis, RecommendationBundle
from app.schemas.guided_intake import GuidedIntakeState, ShoppingGuardrailResult
from app.schemas.intake import ShoppingBrief
from app.schemas.search_sources import SearchPlan
from test_task222_source_sdk import _call, _message, _save_control


_REPORTS: dict[str, Any] = {}
_BUYER = json.dumps(
    {
        "brief": {
            "original_query": "Compare monitors for reading. Budget is not a constraint.",
            "category": "monitor",
            "region": "PH",
        },
        "ownership": "MonitorSpecialistAgent",
        "objective": "Readable text and honest seller cautions.",
    }
)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["object", "array", "sdk-text-block"])
async def test_projected_assistant_json_keeps_complete_records_and_valid_sdk_shape(shape):
    fact = {
        "status": "succeeded", "source_id": "local-source-json",
        "quote": "The monitor has clear text. The imported variant has no local warranty.",
        "claim": "Choose the local variant for its warranty.",
    }
    data = {"rationale": "Execution metadata is redundant. " * 8000, "records": [fact]}
    encoded = json.dumps([data] if shape == "array" else data)
    content = [{"type": "output_text", "text": encoded, "annotations": []}] if shape == "sdk-text-block" else encoded
    root = cm.ContextBudget()
    model = _LocalTransportModel(_Step(_message({"local_control": "valid reduced history"})))
    items = [{"role": "user", "content": _BUYER}, {"role": "assistant", "content": content}]
    with _scopes(root, agent="GeneralShoppingAgent"):
        await _request(root, model, input=items, output=2000, tools=[], contract=GeneralModelOutput)
    observed = model.calls[0]["input"]
    assert json.loads(observed[0]["content"]) == json.loads(_BUYER)
    assistant = next(item for item in observed if item.get("role") == "assistant")
    body = assistant["content"]
    if isinstance(body, list):
        assert body[0]["type"] == "output_text"
        assert body[0]["annotations"] == []
        body = body[0]["text"]
    decoded = json.loads(body)
    assert fact["quote"] in json.dumps(decoded)
    assert fact["source_id"] in json.dumps(decoded)
    assert root.events[-1]["output"]["estimated_input_tokens"] <= 25334
    assert root.events[-1]["output"]["compaction"]["omitted_material_unreviewed"] is True
    assert root.spent == 100 and root.reserved == 0
    _record("assistant-json-" + shape, root)


@pytest.fixture(scope="module", autouse=True)
def save_matrix_report():
    _REPORTS.clear()
    yield
    _save_control("budget-matrix", {"cases": _REPORTS})


@dataclass
class _Step:
    output: Any
    usage: Usage | None = None
    entered: asyncio.Event | None = None
    release: asyncio.Event | None = None


class _LocalTransportModel(Model):
    def __init__(self, *steps: _Step):
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self, instructions, input, settings, tools, schema, handoffs, tracing, **kwargs
    ):
        self.calls.append(
            {
                "instructions": instructions,
                "input": input,
                "tools": [tool.name for tool in tools],
                "tool_choice": settings.tool_choice,
                "output_tokens": settings.max_tokens,
                "contract": schema.json_schema().get("title") if schema else None,
            }
        )
        assert self.steps, "The local control forbids unplanned model calls."
        step = self.steps.pop(0)
        if step.entered is not None:
            step.entered.set()
        if step.release is not None:
            await step.release.wait()
        if isinstance(step.output, BaseException):
            raise step.output
        output = step.output(input) if callable(step.output) else step.output
        return ModelResponse(
            output=output,
            usage=step.usage
            if step.usage is not None
            else Usage(requests=1, input_tokens=80, output_tokens=20, total_tokens=100),
            response_id=None,
        )

    async def stream_response(self, *args, **kwargs):
        raise AssertionError("Local matrix controls never stream.")
        yield


async def _forbid_tool(context, arguments):
    raise AssertionError("Transport controls never execute external or native tools.")


def _native() -> FunctionTool:
    return FunctionTool(
        name="read_video_transcript",
        description="Read an approved bounded transcript span.",
        params_json_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        on_invoke_tool=_forbid_tool,
    )


@contextmanager
def _scopes(root, *children, agent="YouTubeReviewIntelligenceAgent", stage="general_owner"):
    with cm.context_scope(root):
        tokens = (
            cm._allowances.set(tuple(children)),
            cm._agent.set(agent),
            cm._stage.set(stage),
        )
        try:
            yield
        finally:
            cm._allowances.reset(tokens[0])
            cm._agent.reset(tokens[1])
            cm._stage.reset(tokens[2])


async def _request(
    root,
    model,
    *,
    input=_BUYER,
    output=4000,
    tools=None,
    contract=None,
    choice="auto",
):
    return await cm.BudgetedModel(model, root, "explicitly-local-model").get_response(
        "Return the requested contract from the supplied reviewed facts.",
        input,
        ModelSettings(max_tokens=output, tool_choice=choice),
        [_native()] if tools is None else tools,
        AgentOutputSchema(contract, strict_json_schema=False) if contract else None,
        [],
        ModelTracing.DISABLED,
        previous_response_id=None,
        conversation_id=None,
        prompt=None,
    )


def _record(name, root, *children):
    _REPORTS[name] = {
        "events": root.events,
        "ledgers_after": [
            {
                "scope": ledger.scope,
                "funded_tokens": ledger.limits.total_tokens,
                "spent_tokens": ledger.spent,
                "reserved_tokens": ledger.reserved,
                "exhausted": ledger.exhausted,
                "completion_plans": dict(ledger.completion_plans),
            }
            for ledger in (root, *children)
        ],
    }


_TERMINALS = (
    "MonitorSpecialistAgent",
    "SmartphoneSpecialistAgent",
    "LaptopSpecialistAgent",
    "EarphonesHeadphonesSpecialistAgent",
    "TVSpecialistAgent",
    "SmartwatchSpecialistAgent",
)
_ROLES = [
    ("ShoppingScopeGuardrailClassifier", ShoppingGuardrailResult, 400, "structured"),
    ("IntakeAgent", ShoppingBrief, 1200, "structured"),
    ("ShoppingGuideAgent", GuidedIntakeState, 1600, "structured"),
    ("GeneralShoppingAgent", GeneralModelOutput, 3334, "owner"),
    ("TechnologyDomainAnalystAgent", GeneralModelOutput, 2400, "owner"),
    *[(name, GeneralModelOutput, 2000, "owner") for name in _TERMINALS],
    *[("CartCart" + name, CategoryAnalysis, 1600, "structured") for name in _TERMINALS],
    ("CartCartGenericProductAnalystAgent", CategoryAnalysis, 1467, "structured"),
    ("CartCartTechnologyDomainAnalystAgent", CategoryAnalysis, 1467, "structured"),
    ("SourceIntelligenceManagerAgent", SourceManagerDecision, 2000, "source_manager"),
    ("YouTubeReviewIntelligenceAgent", YouTubeReviewModelOutput, 4000, "source"),
    ("RedditCommunityIntelligenceAgent", RedditCommunityModelOutput, 4000, "source"),
    ("AmazonProductIntelligenceAgent", AmazonProductModelOutput, 4000, "source"),
    ("IKEAStoreIntelligenceAgent", IKEAStoreModelOutput, 4000, "source"),
    ("CartCartComparisonDecisionAgent", RecommendationBundle, 2267, "owner"),
    ("CartCartVerifierCriticAgent", _VerifierModelDecision, 2000, "structured"),
    ("CartCartQueryPlannerAgent", SearchPlan, 1467, "structured"),
    ("CartCartDiscoveryAgent", DiscoveryModelOutput, 5334, "structured"),
    ("CartCartExtractionAgent", ExtractionAgentOutput, 6667, "structured"),
    ("CartCartCategoryRouterAgent", ProductAnalysisRoute, 667, "structured"),
    ("CartCartSellerListingTrustAgent", SellerListingTrustModelOutput, 1067, "structured"),
    ("GeneralShoppingAgent", GeneralModelOutput, 2000, "owner"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("agent,contract,output,purpose", _ROLES)
async def test_role_contracts_have_funded_completion(agent, contract, output, purpose):
    probe = cm.ContextBudget()
    with _scopes(probe, agent=agent):
        await _request(
            probe,
            _LocalTransportModel(_Step(_message({"local_control": "probe"}))),
            output=output,
            contract=contract,
        )
    promised = probe.events[0]["output"]["completion_request_tokens"]
    root = cm.ContextBudget(spent=200_000 - promised - 10)
    model = _LocalTransportModel(_Step(_message({"local_control": "funded finish"})))
    with _scopes(root, agent=agent):
        response = await _request(root, model, output=output, contract=contract)
    event = root.events[-1]["output"]
    request = model.calls[0]
    assert request["output_tokens"] == output
    assert request["contract"] == contract.model_json_schema()["title"]
    assert request["tools"] == []
    assert event["completion_purpose"] == purpose
    assert event["phase"] == "complete"
    assert event["downstream_reserve_tokens"] == 0
    assert event["estimated_input_tokens"] <= 25_334
    assert "Further research is closed" in request["instructions"]
    if purpose == "owner":
        assert "Recommend by default" in request["instructions"]
    else:
        assert "Recommend by default" not in request["instructions"]
    assert json.loads(response.output[0].content[0].text) == {
        "local_control": "funded finish"
    }
    assert root.spent == 200_000 - promised + 90
    assert root.reserved == 0
    _record(f"role-{agent}-{output}", root)


@pytest.mark.asyncio
async def test_nested_transfer_funds_exact_shortfalls_without_new_main_tokens():
    root = cm.ContextBudget(spent=140_000)
    owner = cm.ContextBudget(
        limits=replace(cm.ContextLimits(), total_tokens=120_000),
        scope="owner",
        spent=119_950,
        completion_plans={"owner": 1500},
    )
    source = cm.ContextBudget(
        limits=replace(cm.ContextLimits(), total_tokens=40_000),
        scope="source",
        spent=39_960,
        completion_plans={"source_manager:SourceIntelligenceManagerAgent": 900},
    )
    model = _LocalTransportModel(
        _Step(_call("read_video_transcript", {})),
        _Step(_message({"local_source": "completed within the funded allocation"})),
    )
    with _scopes(root, owner, source):
        await _request(root, model)
    event = root.events[0]["output"]
    request, hold = event["requested_reservation"], event["completion_hold_tokens"]
    transfers = event["allocation_transfers"]
    assert [row["scope"] for row in transfers] == ["owner", "source"]
    assert transfers[0]["tokens"] == request + hold + 2400 - 50
    assert transfers[1]["tokens"] == request + hold + 900 - 40
    assert owner.limits.total_tokens == 119_950 + request + hold + 2400
    assert source.limits.total_tokens == 39_960 + request + hold + 900
    assert root.limits.total_tokens == 200_000
    assert [ledger.spent for ledger in (root, owner, source)] == [140_100, 120_050, 40_060]
    assert [ledger.reserved for ledger in (root, owner, source)] == [0, 0, 0]
    assert event["phase"] == "research"
    assert model.calls[0]["tools"] == ["read_video_transcript"]
    funded = (owner.limits.total_tokens, source.limits.total_tokens)
    with _scopes(root, owner, source):
        response = await _request(root, model, tools=[])
    assert json.loads(response.output[0].content[0].text) == {
        "local_source": "completed within the funded allocation"
    }
    assert root.events[-1]["output"]["allocation_transfers"] == []
    assert (owner.limits.total_tokens, source.limits.total_tokens) == funded
    assert [ledger.spent for ledger in (root, owner, source)] == [140_200, 120_150, 40_160]
    assert [ledger.reserved for ledger in (root, owner, source)] == [0, 0, 0]
    _record("exact-nested-transfer", root, owner, source)


@pytest.mark.asyncio
async def test_unfunded_nested_request_cannot_transfer_or_reset_spending():
    root = cm.ContextBudget(spent=199_500)
    owner = cm.ContextBudget(
        limits=replace(cm.ContextLimits(), total_tokens=120_000),
        scope="owner",
        spent=119_990,
    )
    source = cm.ContextBudget(
        limits=replace(cm.ContextLimits(), total_tokens=40_000),
        scope="source",
        spent=39_990,
    )
    model = _LocalTransportModel()
    with _scopes(root, owner, source), pytest.raises(cm.ContextBudgetExceeded):
        await _request(root, model)
    assert model.calls == []
    assert [ledger.limits.total_tokens for ledger in (root, owner, source)] == [200_000, 120_000, 40_000]
    assert [ledger.spent for ledger in (root, owner, source)] == [199_500, 119_990, 39_990]
    assert [ledger.reserved for ledger in (root, owner, source)] == [0, 0, 0]
    assert root.events[-1]["output"]["allocation_transfers"] == []
    assert root.events[-1]["status"] == "blocked"
    assert root.exhausted is owner.exhausted is source.exhausted is False
    _record("rejected-nested-conservation", root, owner, source)


@pytest.mark.asyncio
async def test_parallel_sources_keep_independent_completion_holds():
    root = cm.ContextBudget()
    source = cm.ContextBudget(
        limits=replace(cm.ContextLimits(), total_tokens=40_000),
        scope="source",
        completion_plans={"source_manager:SourceIntelligenceManagerAgent": 2500},
    )
    entered_a, entered_b, release_a, release_b = [asyncio.Event() for _ in range(4)]
    first = _LocalTransportModel(_Step(_message({"local": "done"}), entered=entered_a, release=release_a))
    second = _LocalTransportModel(_Step(_call("read_video_transcript", {}), entered=entered_b, release=release_b))

    async def run(agent, model):
        cm._agent.set(agent)
        return await _request(root, model)

    with _scopes(root, source):
        first_task = asyncio.create_task(run("YouTubeReviewIntelligenceAgent", first))
        await entered_a.wait()
        first_hold = source.completion_plans["source:YouTubeReviewIntelligenceAgent"]
        second_task = asyncio.create_task(run("RedditCommunityIntelligenceAgent", second))
        await entered_b.wait()
        assert set(source.completion_plans) == {
            "source_manager:SourceIntelligenceManagerAgent",
            "source:YouTubeReviewIntelligenceAgent",
            "source:RedditCommunityIntelligenceAgent",
        }
        second_hold = source.completion_plans["source:RedditCommunityIntelligenceAgent"]
        assert root.reserved == sum(e["output"]["requested_reservation"] for e in root.events)
        assert root.reserved + first_hold + second_hold + 2500 <= 200_000
        release_a.set()
        await first_task
        assert source.completion_plans == {
            "source_manager:SourceIntelligenceManagerAgent": 2500,
            "source:RedditCommunityIntelligenceAgent": second_hold,
        }
        release_b.set()
        await second_task
    assert root.spent == source.spent == 200
    assert root.reserved == source.reserved == 0
    _record("parallel-distinct-source-holds", root, source)


@pytest.mark.asyncio
@pytest.mark.parametrize("removed_call", [False, True])
async def test_hosted_removal_keeps_native_tools_and_rejects_removed_calls(removed_call):
    root = cm.ContextBudget(spent=182_000)
    output = _call("web_search", {}) if removed_call else _call("read_video_transcript", {})
    model = _LocalTransportModel(_Step(output))
    with _scopes(root):
        if removed_call:
            with pytest.raises(cm.ContextBudgetExceeded, match="research"):
                await _request(root, model, tools=[WebSearchTool(), _native()], choice="web_search")
        else:
            response = await _request(root, model, tools=[WebSearchTool(), _native()], choice="web_search")
            assert response.output[0].name == "read_video_transcript"
    assert model.calls[0]["tools"] == ["read_video_transcript"]
    assert model.calls[0]["tool_choice"] == "auto"
    event = root.events[-1]
    assert event["output"]["hosted_search_disabled"] is True
    assert event["output"]["hosted_expansion_reservation"] == 0
    assert event["output"]["phase"] == "research"
    assert event["status"] == ("blocked_closed_research" if removed_call else "completed")
    assert root.spent == 182_100 and root.reserved == 0
    _record(f"hosted-removal-{removed_call}", root)


@pytest.mark.asyncio
async def test_removed_hosted_search_rejects_actual_sdk_hosted_output_shape():
    root = cm.ContextBudget(spent=182_000)
    model = _LocalTransportModel(
        _Step(
            [
                ResponseFunctionWebSearch(
                    id="explicitly-local-removed-hosted-record",
                    type="web_search_call",
                    status="completed",
                    action={"type": "search", "query": "explicitly local control"},
                )
            ]
        )
    )
    try:
        with _scopes(root), pytest.raises(cm.ContextBudgetExceeded, match="research"):
            await _request(root, model, tools=[WebSearchTool(), _native()], choice="web_search")
    finally:
        _record("actual-hosted-output-after-removal", root)
    assert model.calls[0]["tools"] == ["read_video_transcript"]
    assert model.calls[0]["tool_choice"] == "auto"
    assert root.events[-1]["status"] == "blocked_closed_research"
    assert root.spent == 182_100 and root.reserved == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["comparison_decision", "verification"])
async def test_only_eligible_downstream_stages_protect_their_32000_allocation(stage):
    inactive = cm.ContextBudget(spent=160_000)
    active = cm.ContextBudget(spent=160_000, eligible_stages=frozenset({stage}))
    for root in (inactive, active):
        with _scopes(root):
            await _request(root, _LocalTransportModel(_Step(_message({"local": "finish"}))))
    assert inactive.events[0]["output"]["downstream_reserve_tokens"] == 0
    assert inactive.events[0]["output"]["phase"] == "research"
    assert active.events[0]["output"]["downstream_reserve_tokens"] == 32_000
    assert active.events[0]["output"]["phase"] == "complete"
    assert inactive.spent == active.spent == 160_100
    assert inactive.reserved == active.reserved == 0
    _record(f"inactive-{stage}", inactive)
    _record(f"eligible-{stage}", active)


@pytest.mark.asyncio
@pytest.mark.parametrize("decorator,scope", [(cm.managed_decision_context, "decision"), (cm.managed_verification_context, "verification")])
async def test_configured_decision_and_verification_scopes_do_not_transfer(decorator, scope):
    root = cm.ContextBudget()
    model = _LocalTransportModel(
        _Step(
            _message({"local": "within scope"}),
            usage=Usage(requests=1, input_tokens=31_980, output_tokens=20, total_tokens=32_000),
        )
    )

    @decorator
    async def run():
        child = cm._allowances.get()[-1]
        assert child.scope == scope and child.transferable is False
        assert child.limits.total_tokens == 32_000
        await _request(root, model, output=2000, tools=[])
        assert child.spent == 32_000
        with pytest.raises(cm.ContextBudgetExceeded):
            await _request(root, model, output=2000, tools=[])
        assert child.limits.total_tokens == 32_000 and child.reserved == 0
        _record(f"fixed-{scope}", root, child)

    with _scopes(root, agent="VerifierCriticAgent" if scope == "verification" else "ComparisonDecisionAgent"):
        await run()
    assert len(model.calls) == 1
    assert root.spent == 32_000 and root.reserved == 0
    assert root.events[-1]["status"] == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("exhausted", [False, True])
async def test_true_main_exhaustion_never_launches_a_model_call(exhausted):
    root = cm.ContextBudget(spent=200_000, exhausted=exhausted)
    model = _LocalTransportModel()
    with _scopes(root), pytest.raises(cm.ContextBudgetExceeded):
        await _request(root, model)
    assert model.calls == []
    assert root.events[-1]["status"] == "blocked"
    assert root.events[-1]["output"]["block_reason"] == "completion_funding"
    assert root.spent == 200_000 and root.reserved == 0
    _record(f"main-exhaustion-{exhausted}", root)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["known", "unknown", "failed", "cancelled"])
async def test_settlement_charges_every_scope_once(outcome):
    root = cm.ContextBudget()
    owner = cm.ContextBudget(limits=replace(cm.ContextLimits(), total_tokens=120_000), scope="owner")
    source = cm.ContextBudget(limits=replace(cm.ContextLimits(), total_tokens=40_000), scope="source")
    output = _message({"local": "complete"})
    usage = Usage(requests=1) if outcome == "unknown" else None
    if outcome == "failed":
        output = RuntimeError("Explicit local failure.")
    if outcome == "cancelled":
        output = asyncio.CancelledError()
    model = _LocalTransportModel(_Step(output, usage=usage))
    with _scopes(root, owner, source):
        if outcome in {"failed", "cancelled"}:
            with pytest.raises(RuntimeError if outcome == "failed" else asyncio.CancelledError):
                await _request(root, model)
        else:
            response = await _request(root, model)
            assert json.loads(response.output[0].content[0].text) == {"local": "complete"}
    event = root.events[-1]
    charge = 100 if outcome == "known" else event["output"]["requested_reservation"]
    assert [ledger.spent for ledger in (root, owner, source)] == [charge, charge, charge]
    assert [ledger.reserved for ledger in (root, owner, source)] == [0, 0, 0]
    assert event["output"]["charged_tokens"] == charge
    assert event["status"] == {"known": "completed", "unknown": "completed_estimated", "failed": "failed_reserved", "cancelled": "cancelled_reserved"}[outcome]
    _record(f"settlement-{outcome}", root, owner, source)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_standalone_releases_hold_and_keeps_reusable_checkpoint(cancelled):
    root = cm.ContextBudget()
    failure = asyncio.CancelledError() if cancelled else RuntimeError("Explicit local failure.")
    model = _LocalTransportModel(_Step(failure))
    with _scopes(root), pytest.raises(asyncio.CancelledError if cancelled else RuntimeError):
        await _request(root, model)
    event = root.events[-1]
    assert root.completion_plans == {}
    checkpoint = root.completion_checkpoints["source:YouTubeReviewIntelligenceAgent"]
    assert checkpoint.agent == "YouTubeReviewIntelligenceAgent"
    assert checkpoint.output_tokens == 4000
    assert json.loads(checkpoint.input) == json.loads(_BUYER)
    assert event["output"]["actual_input_tokens"] is None
    assert root.spent == event["output"]["requested_reservation"]
    assert event["output"]["charged_tokens"] == root.spent
    assert root.reserved == 0
    assert event["status"] == ("cancelled_reserved" if cancelled else "failed_reserved")
    assert len(model.calls) == 1
    _record(f"standalone-hold-release-{cancelled}", root)


@pytest.mark.asyncio
async def test_transport_clamps_an_oversized_requested_output_to_global_ceiling():
    root = cm.ContextBudget()
    model = _LocalTransportModel(_Step(_message({"local": "bounded output"})))
    with _scopes(root):
        response = await _request(root, model, output=100_000)
    assert model.calls[0]["output_tokens"] == 6667
    assert root.events[-1]["output"]["active_output_limit"] == 6667
    assert json.loads(response.output[0].content[0].text) == {"local": "bounded output"}
    assert root.spent == 100 and root.reserved == 0
    _record("global-output-ceiling", root)


@pytest.mark.asyncio
@pytest.mark.parametrize("final", [False, True])
async def test_actual_overage_preserves_paid_final_but_forbids_followup(final):
    root = cm.ContextBudget(spent=180_000)
    owner = cm.ContextBudget(limits=replace(cm.ContextLimits(), total_tokens=120_000), spent=110_000, scope="owner")
    output = _message({"recommendation": "Use the reviewed monitor for readable text."}) if final else _call("read_video_transcript", {})
    model = _LocalTransportModel(_Step(output, usage=Usage(requests=1, input_tokens=24_980, output_tokens=20, total_tokens=25_000)))
    with _scopes(root, owner, agent="MonitorSpecialistAgent"):
        if final:
            response = await _request(root, model, output=2000)
            assert json.loads(response.output[0].content[0].text) == {"recommendation": "Use the reviewed monitor for readable text."}
        else:
            with pytest.raises(cm.ContextBudgetExceeded):
                await _request(root, model, output=2000)
        event = root.events[-1]
        assert event["status"] == ("completed_actual_overage" if final else "blocked_actual_usage")
        assert event["output"]["actual_input_tokens"] == 24_980
        assert event["output"]["charged_tokens"] == 25_000
        assert event["output"]["exceeded_scopes"] == ["main", "owner"]
        assert root.spent == 205_000 and owner.spent == 135_000
        assert root.exhausted is owner.exhausted is True
        with pytest.raises(cm.ContextBudgetExceeded):
            await _request(root, model, output=2000)
    assert len(model.calls) == 1
    assert root.reserved == owner.reserved == 0
    _record(f"actual-overage-final-{final}", root, owner)


@pytest.mark.asyncio
async def test_native_actual_input_mismatch_updates_bounded_headroom():
    root = cm.ContextBudget()
    model = _LocalTransportModel(
        _Step(_message({"local": "first"}), usage=Usage(requests=1, input_tokens=3000, output_tokens=20, total_tokens=3020)),
        _Step(_message({"local": "second"})),
    )
    with _scopes(root):
        await _request(root, model, output=2000, tools=[])
        first = root.events[-1]["output"]
        assert first["actual_input_over_estimate"] is True
        assert first["actual_input_tokens"] == 3000
        assert root.input_headroom_ratio == 2.0
        await _request(root, model, output=2000, tools=[])
    second = root.events[-1]["output"]
    assert first["input_headroom_ratio"] == 1.25
    assert second["input_headroom_ratio"] == 2.0
    assert second["estimated_input_tokens"] > first["estimated_input_tokens"]
    assert second["estimated_input_tokens"] <= 25_334
    assert root.spent == 3120 and root.reserved == 0
    _record("native-estimator-mismatch", root)


@pytest.mark.asyncio
async def test_hosted_expansion_is_recorded_separately_from_native_headroom():
    root = cm.ContextBudget()
    model = _LocalTransportModel(
        _Step(
            [
                ResponseFunctionWebSearch(
                    id="explicitly-local-hosted-record",
                    type="web_search_call",
                    status="completed",
                    action={"type": "search", "query": "explicitly local control"},
                ),
                *_message({"local_source": "hosted expansion accounted"}),
            ],
            usage=Usage(requests=1, input_tokens=30_000, output_tokens=20, total_tokens=30_020),
        )
    )
    with _scopes(root):
        response = await _request(root, model, tools=[WebSearchTool(), _native()])
    event = root.events[-1]["output"]
    assert json.loads(response.output[1].content[0].text) == {
        "local_source": "hosted expansion accounted"
    }
    assert event["hosted_expansion_reservation"] == 10_667
    assert event["hosted_input_expansion_unmeasured"] is True
    assert event["actual_input_over_bound"] is True
    assert event["actual_input_tokens"] == 30_000
    assert root.input_headroom_ratio == 1.25
    assert root.spent == 30_020 and root.reserved == 0
    _record("hosted-estimator-expansion", root)


@pytest.mark.asyncio
async def test_large_child_return_keeps_whole_useful_speech_in_funded_completion():
    speech = "The monitor has sharp text for reading, but the imported seller offers no local warranty."
    segment = {
        "video_id": "localReview01",
        "source_id": "local-source-01",
        "segment_id": "local-segment-01",
        "start_seconds": 15.0,
        "end_seconds": 26.0,
        "url": "https://www.youtube.com/watch?v=localReview01",
        "text": speech,
        "content_sha256": "explicitly-local-speech-hash",
    }
    user = {"role": "user", "content": _BUYER}
    initial = [user]
    root = cm.ContextBudget(spent=182_000)
    source = cm.ContextBudget(limits=replace(cm.ContextLimits(), total_tokens=40_000), scope="source")
    large_result = {
        "status": "ok",
        "video_id": "localReview01",
        "segments": [segment],
        "execution_metadata": "Repeated local transport diagnostics. " * 12_000,
        "repeated_source_views": [{"video_id": "localReview01", "text": "Unrelated repeated local prose. " * 500}] * 20,
    }
    research_call = _call("read_video_transcript", {})[0]
    returned = [
        user,
        research_call.model_dump(mode="json", exclude_none=True),
        {"type": "function_call_output", "call_id": research_call.call_id, "output": json.dumps(large_result)},
    ]

    def authored_source(items):
        encoded = json.dumps(items, ensure_ascii=False)
        assert speech in encoded
        records = []

        def collect(value):
            if isinstance(value, str):
                try:
                    collect(json.loads(value))
                except ValueError:
                    return
            elif isinstance(value, dict):
                records.append(value)
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(items)
        retained = next(row for row in records if row.get("segment_id") == "local-segment-01")
        assert {key: retained[key] for key in segment} == segment
        buyer = next(row for row in records if "brief" in row)
        assert buyer["brief"]["original_query"] == "Compare monitors for reading. Budget is not a constraint."
        assert buyer["ownership"] == "MonitorSpecialistAgent"
        assert buyer["objective"] == "Readable text and honest seller cautions."
        assert any(row.get("omitted_material_unreviewed") is True for row in records)
        return _message({"video_id": "localReview01", "speech": speech, "start_seconds": 15.0, "end_seconds": 26.0, "caution": "Imported seller has no local warranty."})

    model = _LocalTransportModel(
        _Step([research_call], usage=Usage(requests=1, input_tokens=5480, output_tokens=20, total_tokens=5500)),
        _Step(authored_source),
    )
    with _scopes(root, source):
        await _request(root, model, input=initial)
        assert "source:YouTubeReviewIntelligenceAgent" in source.completion_checkpoints
        response = await _request(root, model, input=returned)
    assert model.calls[1]["tools"] == []
    assert "Recommend by default" not in model.calls[1]["instructions"]
    assert json.loads(response.output[0].content[0].text) == {
        "video_id": "localReview01",
        "speech": speech,
        "start_seconds": 15.0,
        "end_seconds": 26.0,
        "caution": "Imported seller has no local warranty.",
    }
    final = root.events[-1]["output"]
    _record("large-child-funded-source-completion", root, source)
    assert final["phase"] == "complete"
    assert final["estimated_input_tokens"] <= 25_334
    assert final["requested_reservation"] <= 12_500
    assert final["compaction"]["omitted_material_unreviewed"] is True
    assert root.spent == 187_600 and source.spent == 5600
    assert root.reserved == source.reserved == 0
    assert large_result["segments"][0] == segment
