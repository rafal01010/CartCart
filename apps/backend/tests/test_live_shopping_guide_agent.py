import asyncio
from dataclasses import dataclass, field
import os
from typing import Any

import pytest

from agents import Agent, RunConfig

from app.agents import (
    IntakeAgentInput,
    LiveShoppingGuideAgent,
    ShoppingGuideAgentInput,
)
from app.agents.live_guide import MockShoppingGuideModelRunner
from app.core.settings import Settings
from app.schemas.guided_intake import (
    AnalysisStartAvailability,
    CurrentGuidedQuestion,
    GuidedAnswerSurface,
    GuidedAnswerSubmission,
    GuidedCaptureTarget,
    GuidedIntakeState,
    GuidedIntakeStatus,
    GuidedQuestionPurpose,
    NaturalLanguageGuidedAnswer,
    ProgressDisplayKind,
    ProgressDisplayStatus,
    RegionSetupStatus,
    RegionSetupSubmission,
)
from app.schemas.intake import (
    BudgetConstraint,
    BudgetMode,
    FieldSource,
    PreferenceConstraint,
    PreferenceMode,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.money import Money
from app.schemas.regions import Region


@dataclass
class RecordingGuideRunner:
    output: GuidedIntakeState | dict[str, Any] | None = None
    error: BaseException | None = None
    delay_seconds: float = 0
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del agent, model_input, run_config, max_turns
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return _RunResult(final_output=self.output or _budget_question_state())


@dataclass
class RecordingIntakeAgent:
    output: ShoppingBrief | None = None
    calls: int = 0
    inputs: list[IntakeAgentInput] = field(default_factory=list)

    async def run(self, input_data: IntakeAgentInput) -> ShoppingBrief:
        self.calls += 1
        self.inputs.append(input_data)
        return self.output or _monitor_brief(input_data.request.query)


@dataclass
class _RunResult:
    final_output: Any


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        **overrides,
    )


def _monitor_query() -> str:
    return (
        "I need a 27-inch 1440p monitor for coding and movies under "
        "PHP 18,000 in the Philippines"
    )


def _monitor_brief(query: str | None = None) -> ShoppingBrief:
    return ShoppingBrief(
        original_query=query or _monitor_query(),
        category="monitor",
        category_source=FieldSource.INFERRED,
        region=RegionPreference(
            region=Region(country_code="PH", currency="PHP"),
            source=FieldSource.INFERRED,
        ),
        budget=BudgetConstraint(
            amount=Money(amount="18000", currency="PHP"),
            mode=BudgetMode.HARD_CAP,
            source=FieldSource.INFERRED,
        ),
        constraints=(
            PreferenceConstraint(
                text="27-inch size",
                mode=PreferenceMode.HARD,
                source=FieldSource.INFERRED,
            ),
            PreferenceConstraint(
                text="1440p resolution",
                mode=PreferenceMode.HARD,
                source=FieldSource.INFERRED,
            ),
        ),
        preferences=(
            PreferenceConstraint(
                text="Good for coding",
                mode=PreferenceMode.SOFT,
                source=FieldSource.INFERRED,
            ),
            PreferenceConstraint(
                text="Good for movies",
                mode=PreferenceMode.SOFT,
                source=FieldSource.INFERRED,
            ),
        ),
    )


def _budget_question_state() -> GuidedIntakeState:
    return GuidedIntakeState(
        status=GuidedIntakeStatus.COLLECTING,
        current_question=CurrentGuidedQuestion(
            question_id="budget",
            text="What budget should we stay near?",
            purpose=GuidedQuestionPurpose.BUDGET,
            answer_surface=GuidedAnswerSurface.TEXTBOX,
            capture_targets=(GuidedCaptureTarget.BUDGET,),
        ),
        skippable_question={"can_skip": True},
        analysis_start=AnalysisStartAvailability(
            enough_information=True,
            can_skip_all_and_start_analysis=True,
            message="We can start with what you have already shared.",
        ),
        progress=ProgressDisplayStatus(
            kind=ProgressDisplayKind.IDLE,
            message="Ready for your answer.",
        ),
    )


def _ready_monitor_state() -> GuidedIntakeState:
    return GuidedIntakeState(
        status=GuidedIntakeStatus.READY_FOR_ANALYSIS,
        analysis_start=AnalysisStartAvailability(
            enough_information=True,
            message="We have enough to start checking options.",
        ),
        progress=ProgressDisplayStatus(
            kind=ProgressDisplayKind.CHECKING_OPTIONS,
            message="Ready to start checking options.",
        ),
        ready_brief=_monitor_brief(),
    )


def _guide_input(
    user_input: str,
    **overrides: object,
) -> ShoppingGuideAgentInput:
    return ShoppingGuideAgentInput(user_input=user_input, **overrides)


@pytest.mark.asyncio
async def test_live_guide_accepts_valid_mocked_question_output() -> None:
    runner = RecordingGuideRunner()
    intake = RecordingIntakeAgent()
    agent = LiveShoppingGuideAgent(
        settings=_settings(),
        model_runner=runner,
        intake_agent=intake,
    )

    result = await agent.run(_guide_input("I need noise-cancelling headphones"))

    assert result.status == GuidedIntakeStatus.COLLECTING
    assert result.current_question is not None
    assert result.current_question.question_id == "budget"
    assert "recommend" not in result.current_question.text.casefold()
    assert runner.calls == 1
    assert intake.calls == 0
    assert agent.workbench_activity[0]["status"] == "model_guide_completed"
    assert agent.workbench_activity[0]["input"]["allowed_tools"] == []


@pytest.mark.asyncio
async def test_live_guide_default_mock_asks_budget_for_headphones() -> None:
    runner = MockShoppingGuideModelRunner()
    agent = LiveShoppingGuideAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_guide_input("I need noise-cancelling headphones"))

    assert result.status == GuidedIntakeStatus.COLLECTING
    assert result.current_question is not None
    assert result.current_question.purpose in {
        GuidedQuestionPurpose.BUDGET,
        GuidedQuestionPurpose.USE_CASE,
    }
    assert "link" not in result.current_question.text.casefold()
    assert "recommend" not in result.current_question.text.casefold()
    assert runner.calls == 1


@pytest.mark.asyncio
async def test_live_guide_keeps_region_setup_separate_from_main_question() -> None:
    agent = LiveShoppingGuideAgent(
        settings=_settings(),
        model_runner=MockShoppingGuideModelRunner(),
    )

    missing = await agent.run(_guide_input("Which phone should I buy?"))
    provided = await agent.run(
        _guide_input(
            "Which phone should I buy?",
            region_setup=RegionSetupSubmission(
                status=RegionSetupStatus.PROVIDED,
                region=Region(country_code="US", currency="USD"),
            ),
        )
    )
    refused = await agent.run(
        _guide_input(
            "Which phone should I buy?",
            region_setup=RegionSetupSubmission(status=RegionSetupStatus.REFUSED),
        )
    )

    assert missing.region_setup.status == RegionSetupStatus.NEEDS_ANSWER
    assert missing.current_question is not None
    assert missing.current_question.question_id != "region"
    assert provided.region_setup.status == RegionSetupStatus.PROVIDED
    assert provided.region_setup.region is not None
    assert provided.region_setup.region.country_code == "US"
    assert refused.region_setup.status == RegionSetupStatus.REFUSED


@pytest.mark.asyncio
async def test_live_guide_handles_already_considered_product_names_without_links() -> None:
    agent = LiveShoppingGuideAgent(
        settings=_settings(),
        model_runner=MockShoppingGuideModelRunner(),
    )

    result = await agent.run(
        _guide_input(
            "I'm considering Sony WH-1000XM5 and Bose QuietComfort Ultra headphones"
        )
    )

    assert result.status == GuidedIntakeStatus.COLLECTING
    assert result.current_question is not None
    user_text = result.current_question.text.casefold()
    assert "link" not in user_text
    assert "url" not in user_text
    assert "recommend" not in user_text


@pytest.mark.asyncio
async def test_live_guide_asks_category_clarification_for_ambiguous_request() -> None:
    agent = LiveShoppingGuideAgent(
        settings=_settings(),
        model_runner=MockShoppingGuideModelRunner(),
    )

    result = await agent.run(_guide_input("I need something for my desk setup"))

    assert result.status == GuidedIntakeStatus.COLLECTING
    assert result.current_question is not None
    assert result.current_question.question_id == "category-clarification"
    assert result.current_question.purpose == GuidedQuestionPurpose.CLARIFICATION
    assert result.current_question.capture_targets == (
        GuidedCaptureTarget.PRODUCT_CATEGORY,
    )


@pytest.mark.asyncio
async def test_live_guide_supports_reanswer_without_visible_chat_history() -> None:
    agent = LiveShoppingGuideAgent(
        settings=_settings(),
        model_runner=MockShoppingGuideModelRunner(),
    )

    result = await agent.run(
        _guide_input(
            "Which laptop should I buy for travel?",
            prior_answers=(
                GuidedAnswerSubmission(
                    question_id="budget",
                    answer=NaturalLanguageGuidedAnswer(text="Around $1,200."),
                ),
            ),
            reanswer_question_id="budget",
        )
    )

    assert result.status == GuidedIntakeStatus.COLLECTING
    assert result.current_question is not None
    assert result.current_question.question_id == "budget"
    assert result.navigation.can_go_back is True
    assert result.navigation.current_reanswer_question_id == "budget"
    assert "chat" not in result.current_question.text.casefold()
    assert "previous" not in result.current_question.text.casefold()


@pytest.mark.asyncio
async def test_live_guide_skip_all_optional_questions_reaches_ready_state() -> None:
    intake = RecordingIntakeAgent()
    agent = LiveShoppingGuideAgent(
        settings=_settings(),
        model_runner=MockShoppingGuideModelRunner(),
        intake_agent=intake,
    )

    result = await agent.run(
        _guide_input(
            "Which desk should I buy?",
            skipped_question_ids=("budget", "use-case", "considered-products"),
            start_analysis_requested=True,
        )
    )

    assert result.status == GuidedIntakeStatus.READY_FOR_ANALYSIS
    assert result.current_question is None
    assert result.ready_brief is not None
    assert result.ready_brief.original_query == "Which desk should I buy?"
    assert intake.calls == 1


@pytest.mark.asyncio
async def test_live_guide_ready_state_hands_off_to_intake_agent() -> None:
    runner = RecordingGuideRunner(output=_ready_monitor_state())
    intake = RecordingIntakeAgent(output=_monitor_brief())
    agent = LiveShoppingGuideAgent(
        settings=_settings(),
        model_runner=runner,
        intake_agent=intake,
    )

    result = await agent.run(
        _guide_input(
            _monitor_query(),
            region_setup=RegionSetupSubmission(
                status=RegionSetupStatus.PROVIDED,
                region=Region(country_code="PH", currency="PHP"),
            ),
        )
    )

    assert result.status == GuidedIntakeStatus.READY_FOR_ANALYSIS
    assert result.current_question is None
    assert result.ready_brief is not None
    assert result.ready_brief.category == "monitor"
    assert result.ready_brief.budget is not None
    assert result.ready_brief.budget.amount.currency == "PHP"
    assert intake.calls == 1
    assert intake.inputs[0].request.query == _monitor_query()
    assert runner.calls == 1


@pytest.mark.asyncio
async def test_live_guide_default_mock_ready_monitor_brief_scenario() -> None:
    intake = RecordingIntakeAgent(output=_monitor_brief())
    agent = LiveShoppingGuideAgent(
        settings=_settings(),
        model_runner=MockShoppingGuideModelRunner(),
        intake_agent=intake,
    )

    result = await agent.run(
        _guide_input(
            _monitor_query(),
            region_setup=RegionSetupSubmission(
                status=RegionSetupStatus.PROVIDED,
                region=Region(country_code="PH", currency="PHP"),
            ),
        )
    )

    assert result.status == GuidedIntakeStatus.READY_FOR_ANALYSIS
    assert result.ready_brief is not None
    assert result.ready_brief.category == "monitor"
    assert intake.calls == 1


@pytest.mark.asyncio
async def test_live_guide_falls_back_on_invalid_model_output() -> None:
    runner = RecordingGuideRunner(output={"status": "collecting"})
    agent = LiveShoppingGuideAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_guide_input("Need a monitor"))

    assert result.status == GuidedIntakeStatus.COLLECTING
    assert result.current_question is not None
    assert result.current_question.question_id == "monitor-connection"
    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"


@pytest.mark.asyncio
async def test_live_guide_falls_back_on_recommendation_like_output() -> None:
    runner = RecordingGuideRunner(
        output=GuidedIntakeState(
            status=GuidedIntakeStatus.COLLECTING,
            current_question=CurrentGuidedQuestion(
                question_id="budget",
                text="I recommend Sony first. What budget should we stay near?",
                purpose=GuidedQuestionPurpose.BUDGET,
                capture_targets=(GuidedCaptureTarget.BUDGET,),
            ),
        )
    )
    agent = LiveShoppingGuideAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_guide_input("I need noise-cancelling headphones"))

    assert result.status == GuidedIntakeStatus.COLLECTING
    assert result.current_question is not None
    assert "recommend" not in result.current_question.text.casefold()
    assert agent.workbench_activity[0]["status"] == "schema_invalid_fallback"


@pytest.mark.asyncio
async def test_live_guide_falls_back_on_timeout() -> None:
    runner = RecordingGuideRunner(delay_seconds=0.02)
    agent = LiveShoppingGuideAgent(
        settings=_settings(openai_agent_timeout_seconds=0.001),
        model_runner=runner,
    )

    result = await agent.run(_guide_input("Need a monitor"))

    assert result.status == GuidedIntakeStatus.COLLECTING
    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "timeout_fallback"


@pytest.mark.asyncio
async def test_live_guide_falls_back_on_model_error() -> None:
    runner = RecordingGuideRunner(error=RuntimeError("mock model failed"))
    agent = LiveShoppingGuideAgent(settings=_settings(), model_runner=runner)

    result = await agent.run(_guide_input("Need a monitor"))

    assert result.status == GuidedIntakeStatus.COLLECTING
    assert runner.calls == 1
    assert agent.workbench_activity[0]["status"] == "error_fallback"


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_shopping_guide_agent_live_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("Set CARTCART_RUN_LIVE_PROVIDER_TESTS=1 to allow live calls.")

    settings = Settings(_env_file=None, live_agents_enabled=True)  # type: ignore[call-arg]
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY is not configured.")

    agent = LiveShoppingGuideAgent(settings=settings)
    result = await agent.run(_guide_input("I need noise-cancelling headphones"))

    assert result.status in {
        GuidedIntakeStatus.COLLECTING,
        GuidedIntakeStatus.READY_FOR_ANALYSIS,
        GuidedIntakeStatus.BLOCKED,
    }
