import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from agents.agent_output import AgentOutputSchema
from agents.items import ModelResponse
from agents.models.interface import Model, ModelProvider
from agents.usage import Usage
from openai.types.responses import ResponseOutputMessage, ResponseOutputText

import app.db.models  # noqa: F401
from app.agents.context_management import BoundedRunner
from app.agents.contracts import ShoppingGuideAgentInput
from app.agents.live_guide import (
    GuideQuestionDecision,
    GuideReadyDecision,
    LiveShoppingGuideAgent,
    ShoppingGuideDecision,
    _build_guide_agent,
    _model_input,
    _guided_question_by_id,
)
from app.agents.live_guardrails import (
    LiveShoppingScopeGuardrail,
    MockShoppingGuardrailModelRunner,
)
from app.agents.live_intake import LiveIntakeAgent
from app.db.base import Base
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_database_engine, create_session_factory
from app.schemas.guided_intake import (
    GuidedAnswerSubmission,
    GuidedIntakeState,
    GuidedIntakeStatus,
    NaturalLanguageGuidedAnswer,
    RegionSetupStatus,
    RegionSetupSubmission,
    ShoppingGuardrailDecision,
    ShoppingGuardrailReason,
    ShoppingGuardrailResult,
)
from app.schemas.intake import (
    CreateSessionRequest,
    ShoppingBrief,
    PreferenceConstraint,
    PreferenceMode,
    FieldSource,
    RegionPreference,
)
from app.schemas.regions import Region
from test_live_shopping_guide_agent import (
    _budget_question_state,
    _monitor_brief,
    _monitor_query,
    _settings,
)


def _intake_control(control, query):
    if control == "skip":
        model_brief = ShoppingBrief(
            original_query=query, category="desk", category_source=FieldSource.INFERRED
        )
        expected = ShoppingBrief(
            original_query=query,
            category="desk",
            category_source=FieldSource.INFERRED,
            preferences=(
                PreferenceConstraint(
                    text=query,
                    mode=PreferenceMode.SOFT,
                    source=FieldSource.USER_PROVIDED,
                ),
            ),
        )
        return model_brief, expected
    model_brief = _monitor_brief(query)
    expected = ShoppingBrief(
        original_query=query,
        category="monitor",
        category_source=FieldSource.INFERRED,
        region=RegionPreference(
            region=Region(country_code="PH", currency="PHP"),
            source=FieldSource.USER_PROVIDED,
        ),
        budget=model_brief.budget,
        constraints=(
            PreferenceConstraint(
                text=query, mode=PreferenceMode.HARD, source=FieldSource.USER_PROVIDED
            ),
            *model_brief.constraints,
        ),
        preferences=model_brief.preferences,
    )
    return model_brief, expected


class GuideTransport(Model):
    def __init__(self, output: dict[str, Any]):
        self.output = output
        self.requests: list[dict[str, Any]] = []

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
        self.requests.append(
            {
                "instructions": instructions,
                "input": input,
                "schema": output_schema.json_schema(),
                "output": self.output,
            }
        )
        return ModelResponse(
            output=[
                ResponseOutputMessage(
                    id="offline-guide",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[
                        ResponseOutputText(
                            type="output_text",
                            text=json.dumps(self.output),
                            annotations=[],
                        )
                    ],
                )
            ],
            usage=Usage(
                requests=1, input_tokens=500, output_tokens=100, total_tokens=600
            ),
            response_id=None,
        )

    def stream_response(self, *args, **kwargs):
        raise AssertionError("Offline guide controls do not stream.")


class GuideProvider(ModelProvider):
    def __init__(self, model: GuideTransport):
        self.model = model

    def get_model(self, model_name):
        return self.model


class SDKGuideRunner:
    def __init__(self, output: dict[str, Any]):
        self.transport = GuideTransport(output)

    async def run(self, agent, model_input, *, run_config, max_turns):
        return await BoundedRunner.run(
            agent,
            model_input,
            run_config=replace(
                run_config, model_provider=GuideProvider(self.transport)
            ),
            max_turns=max_turns,
        )


@pytest.fixture(autouse=True)
def scope_classifier(monkeypatch):
    runner = MockShoppingGuardrailModelRunner(
        output=ShoppingGuardrailResult(decision="allowed")
    )
    monkeypatch.setattr(
        "app.agents.live_guide.LiveShoppingScopeGuardrail",
        lambda *, settings: LiveShoppingScopeGuardrail(
            settings=settings, model_runner=runner
        ),
    )
    return runner


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control",
    ["question", "inline", "skip", "reanswer", "region", "premature", "ready"],
)
async def test_task212_actual_sdk_guide_decisions(control, tmp_path):
    ready = ShoppingGuideDecision(
        decision=GuideReadyDecision(
            reasoning="The provided shopping details are sufficient."
        )
    )
    input_data = ShoppingGuideAgentInput(user_input="Which headphones should I buy?")
    output = _budget_question_state()
    if control == "inline":
        input_data = ShoppingGuideAgentInput(user_input="Which monitor should I buy?")
        output = ShoppingGuideDecision(
            decision=GuideQuestionDecision(
                question=_guided_question_by_id(
                    "monitor-connection", input_data.user_input
                ),
                reasoning="The connection preference affects a useful monitor choice.",
            )
        )
    elif control == "skip":
        input_data = ShoppingGuideAgentInput(
            user_input="Which desk should I buy?",
            skipped_question_ids=("budget", "use-case", "considered-products"),
            start_analysis_requested=True,
        )
        output = ready
    elif control == "reanswer":
        input_data = ShoppingGuideAgentInput(
            user_input="Which laptop should I buy for travel?",
            prior_answers=(
                GuidedAnswerSubmission(
                    question_id="budget",
                    answer=NaturalLanguageGuidedAnswer(text="Around $1200"),
                ),
            ),
            reanswer_question_id="budget",
        )
        output = ready
    elif control == "region":
        input_data = ShoppingGuideAgentInput(
            user_input="Which headphones should I buy?",
            region_setup=RegionSetupSubmission(
                status="provided", region=Region(country_code="PH", currency="PHP")
            ),
        )
    elif control == "premature":
        input_data = ShoppingGuideAgentInput(
            user_input="Please help me choose something"
        )
        output = ready
    elif control == "ready":
        input_data = ShoppingGuideAgentInput(
            user_input=_monitor_query(),
            region_setup=RegionSetupSubmission(
                status="provided", region=Region(country_code="PH", currency="PHP")
            ),
        )
        output = ready

    guide_runner = SDKGuideRunner(output.model_dump(mode="json"))
    model_brief, expected_brief = _intake_control(control, input_data.user_input)
    intake_runner = SDKGuideRunner(model_brief.model_dump(mode="json"))
    intake = LiveIntakeAgent(settings=_settings(), model_runner=intake_runner)
    agent = LiveShoppingGuideAgent(
        settings=_settings(), model_runner=guide_runner, intake_agent=intake
    )
    result = await agent.run(input_data)

    assert len(guide_runner.transport.requests) == 1
    request = guide_runner.transport.requests[0]
    assert "ready_brief" not in json.dumps(request["schema"])
    assert "ShoppingBrief" not in json.dumps(request["schema"])
    assert "navigation" not in json.dumps(request["schema"])
    assert "region_setup" not in json.dumps(request["schema"])
    assert "_Guide" not in result.model_dump_json()
    assert GuidedIntakeState.model_validate_json(result.model_dump_json()) == result
    if control in {"skip", "ready"}:
        assert result.status == GuidedIntakeStatus.READY_FOR_ANALYSIS
        assert result.ready_brief == expected_brief
        assert len(intake_runner.transport.requests) == 1
        assert intake.workbench_activity[0]["status"] == "model_intake_completed"
        settings = _settings(database_path=tmp_path / "task212.sqlite3")
        engine = create_database_engine(settings)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = create_session_factory(engine)
            async with factory() as session:
                saved = await SessionRepository(session).create(
                    CreateSessionRequest(query=input_data.user_input),
                    result.ready_brief,
                )
                await session.commit()
            async with factory() as session:
                loaded = await SessionRepository(session).get(saved.session_id)
            assert loaded is not None
            assert loaded.original_input.query == input_data.user_input
            assert loaded.current_brief == expected_brief
        finally:
            await engine.dispose()
    else:
        assert not intake_runner.transport.requests
        assert result.status == GuidedIntakeStatus.COLLECTING
        assert result.current_question is not None
        if control == "premature":
            assert result.current_question.question_id == "category-clarification"
            assert result.analysis_start.enough_information is False
            assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"
        else:
            assert agent.workbench_activity[0]["status"] == "model_guide_completed"
            assert result.current_question.question_id == (
                "monitor-connection" if control == "inline" else "budget"
            )
            assert result.skippable_question.can_skip is (control != "inline")
            if control == "inline":
                assert result.current_question.inline_choice is not None
                assert tuple(
                    option.choice_id
                    for option in result.current_question.inline_choice.options
                ) == ("yes", "no")
        if control == "reanswer":
            assert result.navigation.current_reanswer_question_id == "budget"
            assert result.navigation.can_go_back is True
        if control == "region":
            assert result.region_setup.region == Region(
                country_code="PH", currency="PHP"
            )
            assert result.region_setup.status == RegionSetupStatus.PROVIDED


@pytest.mark.asyncio
async def test_task212_blocked_guardrail_avoids_guide_and_intake_sdk_calls(
    scope_classifier,
):
    scope_classifier.output = ShoppingGuardrailResult(
        decision=ShoppingGuardrailDecision.BLOCKED,
        reason=ShoppingGuardrailReason.UNSAFE_PRODUCT,
        message="I can help with ordinary shopping questions.",
    )
    runner = SDKGuideRunner(_budget_question_state().model_dump(mode="json"))
    result = await LiveShoppingGuideAgent(
        settings=_settings(), model_runner=runner
    ).run(ShoppingGuideAgentInput(user_input="A request to classify"))
    assert result.status == GuidedIntakeStatus.BLOCKED
    assert not runner.transport.requests
    assert result.ready_brief is None
    assert result.analysis_start.enough_information is False


def test_task212_guide_schema_excludes_backend_state():
    schema = AgentOutputSchema(_build_guide_agent("offline").output_type).json_schema()
    baseline_schema = AgentOutputSchema(GuidedIntakeState).json_schema()
    assert len(json.dumps(schema)) < len(json.dumps(baseline_schema))
    assert "ShoppingBrief" not in json.dumps(schema)
    assert "PriorQuestionNavigationState" not in json.dumps(schema)


@pytest.mark.asyncio
async def test_task212_rejects_legacy_public_state_as_model_output():
    runner = SDKGuideRunner(
        {
            "status": "ready_for_analysis",
            "ready_brief": _monitor_brief().model_dump(mode="json"),
        }
    )
    result = await LiveShoppingGuideAgent(
        settings=_settings(), model_runner=runner
    ).run(ShoppingGuideAgentInput(user_input="Which headphones should I buy?"))
    assert result.status == GuidedIntakeStatus.COLLECTING
    assert result.ready_brief is None
    assert result.current_question is not None
    assert result.current_question.question_id == "budget"


@pytest.mark.asyncio
async def test_task212_actual_sdk_before_after_receipts():
    from agents import RunConfig
    from app.agents.contracts import IntakeAgentInput
    from app.agents.live_guide import (
        _answer_map,
        _collecting_state,
        _intake_request,
        _ready_guided_state,
    )
    from app.schemas.ids import new_id

    receipts = {
        "baseline": "Reconstructed legacy GuidedIntakeState output contract using the same current guide instructions and input. Model usage is scripted, not live token savings.",
        "controls": [],
    }
    for control in ("question", "ready"):
        input_data = ShoppingGuideAgentInput(
            user_input="I need headphones"
            if control == "question"
            else _monitor_query(),
            region_setup=None
            if control == "question"
            else RegionSetupSubmission(
                status="provided", region=Region(country_code="PH", currency="PHP")
            ),
        )
        model_intake, expected_intake = _intake_control(control, input_data.user_input)
        answers = _answer_map(input_data)
        if control == "question":
            question = _budget_question_state().decision
            assert isinstance(question, GuideQuestionDecision)
            legacy_output = _collecting_state(input_data, answers, question.question)
            current_output = ShoppingGuideDecision(decision=question)
        else:
            legacy_output = _ready_guided_state(input_data, answers)
            current_output = ShoppingGuideDecision(
                decision=GuideReadyDecision(
                    reasoning="The supplied details are enough to begin."
                )
            )
        legacy_runner = SDKGuideRunner(legacy_output.model_dump(mode="json"))
        legacy_agent = _build_guide_agent("offline-control").clone(
            output_type=GuidedIntakeState
        )
        old_result = await legacy_runner.run(
            legacy_agent,
            _model_input(input_data),
            run_config=RunConfig(tracing_disabled=True),
            max_turns=3,
        )
        old_state = old_result.final_output
        assert isinstance(old_state, GuidedIntakeState)
        legacy_intake_runner = SDKGuideRunner(model_intake.model_dump(mode="json"))
        if control == "ready":
            old_brief = await LiveIntakeAgent(
                settings=_settings(), model_runner=legacy_intake_runner
            ).run(
                IntakeAgentInput(run_id=new_id(), request=_intake_request(input_data))
            )
            old_state = _ready_guided_state(input_data, answers, brief=old_brief)

        current_runner = SDKGuideRunner(current_output.model_dump(mode="json"))
        current_intake_runner = SDKGuideRunner(model_intake.model_dump(mode="json"))
        current_state = await LiveShoppingGuideAgent(
            settings=_settings(),
            model_runner=current_runner,
            intake_agent=LiveIntakeAgent(
                settings=_settings(), model_runner=current_intake_runner
            ),
        ).run(input_data)
        assert current_state == old_state
        if control == "ready":
            assert current_state.ready_brief == expected_intake
        assert (
            len(legacy_runner.transport.requests)
            == len(current_runner.transport.requests)
            == 1
        )
        old_request = legacy_runner.transport.requests[0]
        new_request = current_runner.transport.requests[0]
        assert old_request["input"] == new_request["input"]
        assert len(json.dumps(new_request["schema"])) < len(
            json.dumps(old_request["schema"])
        )
        assert len(json.dumps(new_request["output"])) < len(
            json.dumps(old_request["output"])
        )
        if control == "ready":
            assert (
                len(legacy_intake_runner.transport.requests)
                == len(current_intake_runner.transport.requests)
                == 1
            )
            old_intake = legacy_intake_runner.transport.requests[0]
            new_intake = current_intake_runner.transport.requests[0]

            def request_without_run_id(request):
                normalized = json.loads(json.dumps(request["input"]))
                for item in normalized:
                    if item.get("role") == "user":
                        content = item["content"]
                        if isinstance(content, str):
                            payload = json.loads(content)
                            if "run_id" in payload:
                                payload["run_id"] = "same-length-offline-control-run-id"
                            item["content"] = json.dumps(payload, sort_keys=True)
                return normalized

            assert request_without_run_id(old_intake) == request_without_run_id(
                new_intake
            )
            assert len(json.dumps(old_intake["input"])) == len(
                json.dumps(new_intake["input"])
            )
        receipts["controls"].append(
            {
                "name": control,
                "before": {
                    key + "_chars": len(json.dumps(old_request[key]))
                    for key in ("schema", "input", "output")
                },
                "after": {
                    key + "_chars": len(json.dumps(new_request[key]))
                    for key in ("schema", "input", "output")
                },
                "downstream_public_chars_before": len(old_state.model_dump_json()),
                "downstream_public_chars_after": len(current_state.model_dump_json()),
                "intake_input_chars_before": len(
                    json.dumps(legacy_intake_runner.transport.requests[0]["input"])
                )
                if control == "ready"
                else 0,
                "intake_input_chars_after": len(
                    json.dumps(current_intake_runner.transport.requests[0]["input"])
                )
                if control == "ready"
                else 0,
                "actual_sdk_calls_before": 1
                + len(legacy_intake_runner.transport.requests),
                "actual_sdk_calls_after": 1
                + len(current_intake_runner.transport.requests),
                "public_state_equal": current_state == old_state,
                "intake_brief_equal": current_state.ready_brief == expected_intake
                if control == "ready"
                else current_state.ready_brief is None,
            }
        )
    artifact = (
        Path(__file__).parents[3] / "data/artifacts/task212/guide-sdk-measurements.json"
    )
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(receipts, indent=2))
