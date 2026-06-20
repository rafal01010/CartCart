import asyncio
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from pydantic import ValidationError

from app.agents.contracts import (
    IntakeAgent,
    IntakeAgentInput,
    ShoppingGuideAgentInput,
)
from app.agents.live_intake import LiveIntakeAgent
from app.agents.openai_config import build_openai_agent_run_configuration
from app.core.settings import Settings
from app.schemas.guided_intake import (
    AnalysisStartAvailability,
    ChoiceGuidedAnswer,
    ChoiceWithTextGuidedAnswer,
    CombinedOptionalQuestionPrompt,
    CurrentGuidedQuestion,
    GuidedAnswer,
    GuidedAnswerSurface,
    GuidedCaptureTarget,
    GuidedIntakeState,
    GuidedIntakeStatus,
    GuidedQuestionPurpose,
    InlineChoiceControl,
    InlineChoiceControlType,
    InlineChoiceOption,
    LocalRegionSetupState,
    NaturalLanguageGuidedAnswer,
    PriorQuestionNavigationState,
    ProgressDisplayKind,
    ProgressDisplayStatus,
    ReanswerableQuestion,
    RegionSetupStatus,
    RegionSetupSubmission,
    ShoppingGuardrailDecision,
    SkippableQuestionState,
    YesNoGuidedAnswer,
)
from app.schemas.ids import new_id
from app.schemas.intake import (
    BudgetConstraint,
    BudgetMode,
    CreateSessionRequest,
    FieldSource,
    PreferenceConstraint,
    PreferenceMode,
    RegionPreference,
    ShoppingBrief,
)
from app.schemas.money import Money
from app.schemas.regions import Region
from app.services.shopping_guardrails import evaluate_shopping_guardrail


FIRST_QUESTION_ID = "first-question"
BUDGET_QUESTION_ID = "budget"
CONSIDERED_PRODUCTS_QUESTION_ID = "considered-products"
MONITOR_CONNECTION_QUESTION_ID = "monitor-connection"
COMPARISON_PRIORITY_QUESTION_ID = "comparison-priority"
USE_CASE_QUESTION_ID = "use-case"
CATEGORY_CLARIFICATION_QUESTION_ID = "category-clarification"
COMBINED_OPTIONAL_QUESTION_ID = "combined-optional"

_OPTIONAL_QUESTION_IDS = frozenset(
    {
        BUDGET_QUESTION_ID,
        CONSIDERED_PRODUCTS_QUESTION_ID,
        USE_CASE_QUESTION_ID,
        COMBINED_OPTIONAL_QUESTION_ID,
    }
)
_KNOWN_QUESTION_IDS = frozenset(
    {
        FIRST_QUESTION_ID,
        BUDGET_QUESTION_ID,
        CONSIDERED_PRODUCTS_QUESTION_ID,
        MONITOR_CONNECTION_QUESTION_ID,
        COMPARISON_PRIORITY_QUESTION_ID,
        USE_CASE_QUESTION_ID,
        CATEGORY_CLARIFICATION_QUESTION_ID,
        COMBINED_OPTIONAL_QUESTION_ID,
    }
)
_PRODUCT_LINK_TERMS = (
    "product url",
    "product link",
    "paste a url",
    "paste the url",
    "paste a link",
    "paste the link",
    "web address",
    "listing url",
    "listing link",
)
_RECOMMENDATION_TERMS = (
    "i recommend",
    "my recommendation",
    "best pick",
    "top pick",
    "you should buy",
    "buy the ",
    "choose the ",
)


class ShoppingGuideModelRunner(Protocol):
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        """Run the SDK guide agent and return its raw run result."""


@dataclass
class OpenAIAgentsSDKShoppingGuideModelRunner:
    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        return await Runner.run(
            agent,
            model_input,
            run_config=run_config,
            max_turns=max_turns,
        )


@dataclass
class MockShoppingGuideModelRunner:
    output: GuidedIntakeState | dict[str, Any] | None = None
    error: BaseException | None = None
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
    ) -> Any:
        del agent, run_config, max_turns
        self.calls += 1
        if self.error is not None:
            raise self.error
        output = self.output or _mock_guide_from_model_input(model_input)
        return _MockRunResult(final_output=output)


@dataclass
class LiveShoppingGuideAgent:
    settings: Settings
    model_runner: ShoppingGuideModelRunner = field(
        default_factory=OpenAIAgentsSDKShoppingGuideModelRunner,
    )
    intake_agent: IntakeAgent | None = None
    _workbench_activity: tuple[dict[str, Any], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    async def run(self, input_data: ShoppingGuideAgentInput) -> GuidedIntakeState:
        deterministic_guardrail = evaluate_shopping_guardrail(
            input_data.user_input,
            prior_answers=input_data.prior_answers,
        )
        if deterministic_guardrail.decision == ShoppingGuardrailDecision.BLOCKED:
            state = _blocked_guided_state(input_data)
            self._set_activity("not_started_deterministic_block", input_data, state)
            return state

        configuration = build_openai_agent_run_configuration(
            self.settings,
            agent_name="ShoppingGuideAgent",
        )
        agent = _build_guide_agent(configuration.model)
        run_config = RunConfig(
            model=configuration.model,
            model_settings=ModelSettings(
                temperature=0,
                max_tokens=1200,
                include_usage=True,
            ),
            tracing_disabled=not configuration.tracing_enabled,
            trace_include_sensitive_data=configuration.trace_include_sensitive_data,
            workflow_name=configuration.trace_workflow_name,
            trace_metadata=configuration.trace_metadata,
        )

        try:
            raw_result = await asyncio.wait_for(
                self.model_runner.run(
                    agent,
                    _model_input(input_data),
                    run_config=run_config,
                    max_turns=configuration.max_turns,
                ),
                timeout=configuration.timeout_seconds,
            )
            state = _coerce_guide_result(
                getattr(raw_result, "final_output", raw_result),
            )
            state = _validate_guide_policy(state, input_data)
            state = await self._attach_ready_brief_from_intake(state, input_data)
        except TimeoutError:
            state = _fallback_guided_state(input_data)
            self._set_activity("timeout_fallback", input_data, state)
            return state
        except (ValidationError, ValueError, TypeError):
            state = _fallback_guided_state(input_data)
            self._set_activity("schema_invalid_fallback", input_data, state)
            return state
        except Exception:
            state = _fallback_guided_state(input_data)
            self._set_activity("error_fallback", input_data, state)
            return state

        self._set_activity("model_guide_completed", input_data, state)
        return state

    @property
    def workbench_activity(self) -> tuple[dict[str, Any], ...]:
        return self._workbench_activity

    async def _attach_ready_brief_from_intake(
        self,
        state: GuidedIntakeState,
        input_data: ShoppingGuideAgentInput,
    ) -> GuidedIntakeState:
        if state.status != GuidedIntakeStatus.READY_FOR_ANALYSIS:
            return state

        intake = self.intake_agent or LiveIntakeAgent(settings=self.settings)
        brief = await intake.run(
            IntakeAgentInput(
                run_id=new_id(),
                request=_intake_request(input_data),
            )
        )
        data = state.model_dump(mode="python")
        data["current_question"] = None
        data["ready_brief"] = brief
        data["analysis_start"] = AnalysisStartAvailability(
            enough_information=True,
            can_skip_all_and_start_analysis=False,
            message="We have enough to start checking options.",
        )
        data["progress"] = data.get("progress") or ProgressDisplayStatus(
            kind=ProgressDisplayKind.CHECKING_OPTIONS,
            message="Ready to start checking options.",
        )
        return GuidedIntakeState.model_validate(data)

    def _set_activity(
        self,
        status: str,
        input_data: ShoppingGuideAgentInput,
        state: GuidedIntakeState,
    ) -> None:
        self._workbench_activity = (
            {
                "tool_name": "openai_agents_structured_output",
                "status": status,
                "input": {
                    "agent": "ShoppingGuideAgent",
                    "allowed_tools": [],
                    "has_region_setup": input_data.region_setup is not None,
                    "prior_answer_count": len(input_data.prior_answers),
                    "skipped_question_count": len(input_data.skipped_question_ids),
                    "start_analysis_requested": input_data.start_analysis_requested,
                },
                "output": state.model_dump(mode="json"),
            },
        )


@dataclass
class _MockRunResult:
    final_output: Any


def _build_guide_agent(model: str) -> Agent[Any]:
    return Agent(
        name="CartCartShoppingGuideAgent",
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=1200,
            include_usage=True,
        ),
        instructions=(
            "You are CartCart's user-facing guided shopping intake step. Return "
            "only a GuidedIntakeState. Ask the next concise question a regular "
            "shopper should answer, or return ready_for_analysis when the "
            "shopper has provided enough category, budget, region, use-case, "
            "constraint, or considered-product context. Use the provided "
            "prior_answers as structured state; do not refer to visible chat "
            "history. Prefer a textbox question. Use inline choices only when a "
            "yes/no or two-option answer is easier than typing. You may group "
            "small optional questions only with combined_optional_prompt. Never "
            "ask for product links, product URLs, listing links, or web "
            "addresses in normal intake; ask for product names or descriptions "
            "instead. Do not recommend products, rank products, browse, call "
            "tools, mention internal process, or expose agents, providers, "
            "prompts, traces, run IDs, policies, or schemas. When ready, include "
            "a ready_brief using only already-known shopper information; the "
            "runtime may replace it with IntakeAgent output."
        ),
        tools=[],
        output_type=GuidedIntakeState,
    )


def _model_input(input_data: ShoppingGuideAgentInput) -> str:
    return json.dumps(
        {
            "user_input": input_data.user_input,
            "region_setup": input_data.region_setup.model_dump(mode="json")
            if input_data.region_setup is not None
            else None,
            "prior_answers": [
                answer.model_dump(mode="json") for answer in input_data.prior_answers
            ],
            "skipped_question_ids": list(input_data.skipped_question_ids),
            "reanswer_question_id": input_data.reanswer_question_id,
            "start_analysis_requested": input_data.start_analysis_requested,
        },
        sort_keys=True,
    )


def _coerce_guide_result(value: Any) -> GuidedIntakeState:
    if isinstance(value, GuidedIntakeState):
        return value
    return GuidedIntakeState.model_validate(value)


def _validate_guide_policy(
    state: GuidedIntakeState,
    input_data: ShoppingGuideAgentInput,
) -> GuidedIntakeState:
    _reject_policy_text(state)
    if state.current_question is not None:
        question_id = state.current_question.question_id
        if question_id not in _KNOWN_QUESTION_IDS:
            raise ValueError("guide returned an unknown question id.")

    if (
        state.status == GuidedIntakeStatus.COLLECTING
        and state.ready_brief is not None
    ):
        raise ValueError("collecting guide state cannot include a ready brief.")

    if state.status == GuidedIntakeStatus.READY_FOR_ANALYSIS:
        if not _enough_information_for_analysis(input_data):
            raise ValueError("guide returned ready before enough information existed.")
        data = state.model_dump(mode="python")
        data["current_question"] = None
        data["skippable_question"] = SkippableQuestionState(can_skip=False)
        return GuidedIntakeState.model_validate(data)

    return state


def _reject_policy_text(state: GuidedIntakeState) -> None:
    for text in _user_facing_texts(state):
        normalized = text.casefold()
        for term in (*_PRODUCT_LINK_TERMS, *_RECOMMENDATION_TERMS):
            if term in normalized:
                raise ValueError(f"guide output included disallowed text: {term}")


def _user_facing_texts(state: GuidedIntakeState) -> tuple[str, ...]:
    texts: list[str] = []
    if state.current_question is not None:
        question = state.current_question
        texts.append(question.text)
        if question.combined_optional_prompt is not None:
            texts.append(question.combined_optional_prompt.text)
        if question.inline_choice is not None:
            control = question.inline_choice
            if control.custom_answer_label:
                texts.append(control.custom_answer_label)
            for option in control.options:
                texts.append(option.label)
                if option.description:
                    texts.append(option.description)
    if state.analysis_start.message:
        texts.append(state.analysis_start.message)
    if state.region_setup.prompt_text:
        texts.append(state.region_setup.prompt_text)
    if state.progress is not None:
        texts.append(state.progress.message)
    if state.guardrail is not None and state.guardrail.message:
        texts.append(state.guardrail.message)
    return tuple(texts)


def _mock_guide_from_model_input(model_input: str) -> GuidedIntakeState:
    input_data = ShoppingGuideAgentInput.model_validate(json.loads(model_input))
    return _fallback_guided_state(input_data)


def _fallback_guided_state(input_data: ShoppingGuideAgentInput) -> GuidedIntakeState:
    guardrail = evaluate_shopping_guardrail(
        input_data.user_input,
        prior_answers=input_data.prior_answers,
    )
    if guardrail.decision == ShoppingGuardrailDecision.BLOCKED:
        return _blocked_guided_state(input_data)

    answer_map = _answer_map(input_data)
    if input_data.reanswer_question_id is not None:
        question = _guided_question_by_id(
            input_data.reanswer_question_id,
            input_data.user_input,
        )
        return _collecting_state(input_data, answer_map, question)

    if (
        _query_has_complete_brief(input_data)
        or _ready_requested(input_data)
        and _enough_information_for_analysis(input_data)
    ):
        return _ready_guided_state(input_data, answer_map)

    question_id = _next_question_id(input_data, answer_map)
    if question_id is None:
        return _ready_guided_state(input_data, answer_map)
    question = _guided_question_by_id(question_id, input_data.user_input)
    return _collecting_state(input_data, answer_map, question)


def _blocked_guided_state(input_data: ShoppingGuideAgentInput) -> GuidedIntakeState:
    guardrail = evaluate_shopping_guardrail(
        input_data.user_input,
        prior_answers=input_data.prior_answers,
    )
    return GuidedIntakeState(
        status=GuidedIntakeStatus.BLOCKED,
        guardrail=guardrail,
        region_setup=_region_setup_state(input_data.region_setup),
        progress=ProgressDisplayStatus(
            kind=ProgressDisplayKind.BLOCKED,
            message="This request is outside shopping help.",
        ),
    )


def _collecting_state(
    input_data: ShoppingGuideAgentInput,
    answer_map: dict[str, GuidedAnswer],
    question: CurrentGuidedQuestion,
) -> GuidedIntakeState:
    enough_information = _enough_information_for_analysis(input_data)
    return GuidedIntakeState(
        status=GuidedIntakeStatus.COLLECTING,
        current_question=question,
        navigation=_navigation_state(answer_map, input_data.reanswer_question_id),
        skippable_question=SkippableQuestionState(
            can_skip=question.question_id in _OPTIONAL_QUESTION_IDS,
        ),
        analysis_start=AnalysisStartAvailability(
            enough_information=enough_information,
            can_skip_all_and_start_analysis=enough_information,
            message="We can start with what you have already shared."
            if enough_information
            else None,
        ),
        region_setup=_region_setup_state(input_data.region_setup),
        progress=ProgressDisplayStatus(
            kind=ProgressDisplayKind.IDLE,
            message="Ready for your answer.",
        ),
    )


def _ready_guided_state(
    input_data: ShoppingGuideAgentInput,
    answer_map: dict[str, GuidedAnswer],
) -> GuidedIntakeState:
    return GuidedIntakeState(
        status=GuidedIntakeStatus.READY_FOR_ANALYSIS,
        navigation=_navigation_state(answer_map, input_data.reanswer_question_id),
        analysis_start=AnalysisStartAvailability(
            enough_information=True,
            can_skip_all_and_start_analysis=False,
            message="We have enough to start checking options.",
        ),
        region_setup=_region_setup_state(input_data.region_setup),
        progress=ProgressDisplayStatus(
            kind=ProgressDisplayKind.CHECKING_OPTIONS,
            message="Ready to start checking options.",
        ),
        ready_brief=_fallback_brief(input_data),
    )


def _next_question_id(
    input_data: ShoppingGuideAgentInput,
    answer_map: dict[str, GuidedAnswer],
) -> str | None:
    if _category_fields(input_data.user_input) == {}:
        category_answer = answer_map.get(CATEGORY_CLARIFICATION_QUESTION_ID)
        if category_answer is None:
            return CATEGORY_CLARIFICATION_QUESTION_ID

    first_followup = _first_followup_question_id(input_data.user_input)
    if (
        first_followup not in answer_map
        and first_followup not in input_data.skipped_question_ids
    ):
        return first_followup
    if (
        BUDGET_QUESTION_ID not in answer_map
        and BUDGET_QUESTION_ID not in input_data.skipped_question_ids
        and _budget_from_input(input_data) is None
    ):
        return BUDGET_QUESTION_ID
    if (
        USE_CASE_QUESTION_ID not in answer_map
        and USE_CASE_QUESTION_ID not in input_data.skipped_question_ids
        and not _has_use_case(input_data)
    ):
        return USE_CASE_QUESTION_ID
    if (
        CONSIDERED_PRODUCTS_QUESTION_ID not in answer_map
        and CONSIDERED_PRODUCTS_QUESTION_ID not in input_data.skipped_question_ids
        and not _mentions_considered_products(input_data.user_input)
    ):
        return CONSIDERED_PRODUCTS_QUESTION_ID
    return None


def _ready_requested(input_data: ShoppingGuideAgentInput) -> bool:
    return (
        input_data.start_analysis_requested
        or CONSIDERED_PRODUCTS_QUESTION_ID in input_data.skipped_question_ids
        or CONSIDERED_PRODUCTS_QUESTION_ID in _answer_map(input_data)
    )


def _enough_information_for_analysis(input_data: ShoppingGuideAgentInput) -> bool:
    if _category_fields(input_data.user_input) == {} and not _answer_text(
        _answer_map(input_data).get(CATEGORY_CLARIFICATION_QUESTION_ID)
    ):
        return False
    return (
        _budget_from_input(input_data) is not None
        or _region_preference_from_input(input_data) is not None
        or _has_use_case(input_data)
        or _ready_requested(input_data)
    )


def _query_has_complete_brief(input_data: ShoppingGuideAgentInput) -> bool:
    return (
        _category_fields(input_data.user_input) != {}
        and _budget_from_input(input_data) is not None
        and _region_preference_from_input(input_data) is not None
        and _has_use_case(input_data)
    )


def _first_followup_question_id(user_input: str) -> str:
    normalized = user_input.casefold()
    if "monitor" in normalized:
        return MONITOR_CONNECTION_QUESTION_ID
    if " between " in f" {normalized} " or " vs " in normalized:
        return COMPARISON_PRIORITY_QUESTION_ID
    return BUDGET_QUESTION_ID


def _guided_question_by_id(question_id: str, user_input: str) -> CurrentGuidedQuestion:
    del user_input
    if question_id == FIRST_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=FIRST_QUESTION_ID,
            text="Send your question",
            purpose=GuidedQuestionPurpose.FIRST_QUESTION,
            capture_targets=(GuidedCaptureTarget.SHOPPING_QUESTION,),
        )
    if question_id == MONITOR_CONNECTION_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=MONITOR_CONNECTION_QUESTION_ID,
            text="Would one-cable setup be useful for this monitor?",
            purpose=GuidedQuestionPurpose.PRIORITIES,
            answer_surface=GuidedAnswerSurface.INLINE_CHOICE,
            capture_targets=(GuidedCaptureTarget.PRIORITIES,),
            inline_choice=InlineChoiceControl(
                control_id="monitor-connection-choice",
                control_type=InlineChoiceControlType.YES_NO,
                options=(
                    InlineChoiceOption(choice_id="yes", label="Yes"),
                    InlineChoiceOption(choice_id="no", label="No"),
                ),
            ),
        )
    if question_id == COMPARISON_PRIORITY_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=COMPARISON_PRIORITY_QUESTION_ID,
            text="For that comparison, what should matter most?",
            purpose=GuidedQuestionPurpose.PRIORITIES,
            answer_surface=GuidedAnswerSurface.INLINE_CHOICE,
            capture_targets=(GuidedCaptureTarget.PRIORITIES,),
            inline_choice=InlineChoiceControl(
                control_id="comparison-priority-choice",
                control_type=InlineChoiceControlType.TWO_OPTION_PLUS_TYPE_ANSWER,
                options=(
                    InlineChoiceOption(choice_id="everyday-use", label="Everyday use"),
                    InlineChoiceOption(choice_id="best-value", label="Best value"),
                ),
                custom_answer_label="Type my answer",
            ),
        )
    if question_id == BUDGET_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=BUDGET_QUESTION_ID,
            text="What budget should we stay near?",
            purpose=GuidedQuestionPurpose.BUDGET,
            capture_targets=(GuidedCaptureTarget.BUDGET,),
        )
    if question_id == USE_CASE_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=USE_CASE_QUESTION_ID,
            text="What will you use it for most?",
            purpose=GuidedQuestionPurpose.USE_CASE,
            capture_targets=(GuidedCaptureTarget.USE_CASE,),
        )
    if question_id == CONSIDERED_PRODUCTS_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=CONSIDERED_PRODUCTS_QUESTION_ID,
            text="Are there any products you want CartCart to check?",
            purpose=GuidedQuestionPurpose.CONSIDERED_PRODUCTS,
            capture_targets=(
                GuidedCaptureTarget.CONSIDERED_PRODUCT_NAMES,
                GuidedCaptureTarget.CONSIDERED_PRODUCT_DESCRIPTIONS,
            ),
        )
    if question_id == CATEGORY_CLARIFICATION_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=CATEGORY_CLARIFICATION_QUESTION_ID,
            text="What kind of product are you deciding on?",
            purpose=GuidedQuestionPurpose.CLARIFICATION,
            capture_targets=(GuidedCaptureTarget.PRODUCT_CATEGORY,),
        )
    if question_id == COMBINED_OPTIONAL_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=COMBINED_OPTIONAL_QUESTION_ID,
            text="Anything else I should keep in mind?",
            purpose=GuidedQuestionPurpose.COMBINED_OPTIONAL,
            capture_targets=(
                GuidedCaptureTarget.BUDGET,
                GuidedCaptureTarget.USE_CASE,
                GuidedCaptureTarget.CONSIDERED_PRODUCT_NAMES,
            ),
            combined_optional_prompt=CombinedOptionalQuestionPrompt(
                text=(
                    "Share a budget, main use, or any products you already have "
                    "in mind."
                ),
                capture_targets=(
                    GuidedCaptureTarget.BUDGET,
                    GuidedCaptureTarget.USE_CASE,
                    GuidedCaptureTarget.CONSIDERED_PRODUCT_NAMES,
                ),
            ),
        )
    raise ValueError(f"unknown guided question id: {question_id}")


def _navigation_state(
    answer_map: dict[str, GuidedAnswer],
    reanswer_question_id: str | None,
) -> PriorQuestionNavigationState:
    ordered_question_ids = (
        MONITOR_CONNECTION_QUESTION_ID,
        COMPARISON_PRIORITY_QUESTION_ID,
        CATEGORY_CLARIFICATION_QUESTION_ID,
        BUDGET_QUESTION_ID,
        USE_CASE_QUESTION_ID,
        CONSIDERED_PRODUCTS_QUESTION_ID,
        COMBINED_OPTIONAL_QUESTION_ID,
    )
    questions = tuple(
        ReanswerableQuestion(
            question_id=question_id,
            label=_reanswer_label(question_id),
        )
        for question_id in ordered_question_ids
        if question_id in answer_map
    )
    return PriorQuestionNavigationState(
        can_go_back=bool(questions),
        current_reanswer_question_id=reanswer_question_id,
        reanswerable_questions=questions,
    )


def _reanswer_label(question_id: str) -> str:
    labels = {
        MONITOR_CONNECTION_QUESTION_ID: "Monitor setup",
        COMPARISON_PRIORITY_QUESTION_ID: "Comparison priority",
        CATEGORY_CLARIFICATION_QUESTION_ID: "Product category",
        BUDGET_QUESTION_ID: "Budget",
        USE_CASE_QUESTION_ID: "Main use",
        CONSIDERED_PRODUCTS_QUESTION_ID: "Products to check",
        COMBINED_OPTIONAL_QUESTION_ID: "Extra details",
    }
    return labels.get(question_id, "Earlier answer")


def _region_setup_state(
    submission: RegionSetupSubmission | None,
) -> LocalRegionSetupState:
    if submission is None:
        return LocalRegionSetupState(
            status=RegionSetupStatus.NEEDS_ANSWER,
            prompt_text=(
                "Where are you buying from? "
                "It helps show options you can actually buy."
            ),
            resumes_pending_question=True,
        )
    if submission.status == RegionSetupStatus.PROVIDED:
        return LocalRegionSetupState(
            status=RegionSetupStatus.PROVIDED,
            region=submission.region,
            resumes_pending_question=True,
        )
    return LocalRegionSetupState(
        status=RegionSetupStatus.REFUSED,
        resumes_pending_question=True,
    )


def _intake_request(input_data: ShoppingGuideAgentInput) -> CreateSessionRequest:
    texts = _known_texts(input_data)
    constraints = tuple(
        PreferenceConstraint(
            text=text,
            mode=PreferenceMode.HARD,
            source=FieldSource.USER_PROVIDED,
        )
        for text in texts
        if _looks_like_constraint(text)
    )
    preferences = tuple(
        PreferenceConstraint(
            text=text,
            mode=PreferenceMode.SOFT,
            source=FieldSource.USER_PROVIDED,
        )
        for text in texts
        if not _looks_like_constraint(text) and not _looks_like_budget(text)
    )
    return CreateSessionRequest(
        query=input_data.user_input,
        region=_region_preference_from_input(input_data),
        budget=_budget_from_input(input_data),
        constraints=constraints,
        preferences=preferences,
    )


def _fallback_brief(input_data: ShoppingGuideAgentInput) -> ShoppingBrief:
    request = _intake_request(input_data)
    return ShoppingBrief(
        original_query=request.query,
        region=request.region,
        budget=request.budget,
        constraints=request.constraints,
        preferences=request.preferences,
        **_category_fields(input_data.user_input),
    )


def _answer_map(input_data: ShoppingGuideAgentInput) -> dict[str, GuidedAnswer]:
    return {
        submission.question_id: submission.answer
        for submission in input_data.prior_answers
    }


def _known_texts(input_data: ShoppingGuideAgentInput) -> tuple[str, ...]:
    texts = [input_data.user_input]
    for answer in _answer_map(input_data).values():
        text = _answer_text(answer)
        if text:
            texts.append(text)
    return tuple(texts)


def _answer_text(answer: GuidedAnswer | None) -> str | None:
    if answer is None:
        return None
    if isinstance(answer, NaturalLanguageGuidedAnswer | ChoiceWithTextGuidedAnswer):
        return answer.text
    if isinstance(answer, YesNoGuidedAnswer):
        return "Yes" if answer.value else "No"
    if isinstance(answer, ChoiceGuidedAnswer):
        return answer.choice_id.replace("-", " ")
    return None


def _category_fields(user_input: str) -> dict[str, str]:
    normalized = user_input.casefold()
    if "desk setup" in normalized or "something for" in normalized:
        return {}
    categories = {
        "coffee grinder": "coffee grinder",
        "grinder": "coffee grinder",
        "office chair": "office chair",
        "laptop": "laptop",
        "notebook": "laptop",
        "phone": "smartphone",
        "iphone": "smartphone",
        "samsung": "smartphone",
        "camera": "camera",
        "desk": "desk",
        "monitor": "monitor",
        "display": "monitor",
        "headphone": "headphones",
        "noise-cancelling": "headphones",
        "earphone": "earphones",
        "earbud": "earbuds",
        "tv": "tv",
        "television": "tv",
        "smartwatch": "smartwatch",
    }
    for keyword, category in categories.items():
        if keyword in normalized:
            return {"category": category, "category_source": FieldSource.INFERRED}
    return {}


def _region_preference_from_input(
    input_data: ShoppingGuideAgentInput,
) -> RegionPreference | None:
    if (
        input_data.region_setup is not None
        and input_data.region_setup.status == RegionSetupStatus.PROVIDED
        and input_data.region_setup.region is not None
    ):
        return RegionPreference(
            region=input_data.region_setup.region,
            source=FieldSource.USER_PROVIDED,
        )
    normalized = input_data.user_input.casefold()
    if "philippines" in normalized or "php" in normalized or "₱" in normalized:
        return RegionPreference(
            region=Region(country_code="PH", currency="PHP"),
            source=FieldSource.INFERRED,
        )
    if (
        "united states" in normalized
        or " usa" in f" {normalized}"
        or " usd" in f" {normalized}"
        or "$" in input_data.user_input
    ):
        return RegionPreference(
            region=Region(country_code="US", currency="USD"),
            source=FieldSource.INFERRED,
        )
    return None


def _budget_from_input(input_data: ShoppingGuideAgentInput) -> BudgetConstraint | None:
    region = _region_preference_from_input(input_data)
    for text in _known_texts(input_data):
        budget = _budget_from_text(text, region)
        if budget is not None:
            return budget
    return None


def _budget_from_text(
    text: str,
    region: RegionPreference | None,
) -> BudgetConstraint | None:
    normalized = text.replace(",", "")
    php_match = re.search(r"(?:php|₱)\s*(\d+(?:\.\d{1,2})?)", normalized, re.I)
    usd_match = re.search(r"\$\s*(\d+(?:\.\d{1,2})?)", normalized)
    generic_match = re.search(
        r"\b(?:under|below|around|about|near|max(?:imum)?)\s+(\d+(?:\.\d{1,2})?)",
        normalized,
        re.I,
    )
    if php_match is not None:
        currency = "PHP"
        amount = php_match.group(1)
    elif usd_match is not None:
        currency = "USD"
        amount = usd_match.group(1)
    elif generic_match is not None and region is not None and region.region.currency:
        currency = region.region.currency
        amount = generic_match.group(1)
    else:
        return None

    lower_text = text.casefold()
    hard_cap = any(
        term in lower_text
        for term in ("under", "below", "max", "maximum", "must stay below")
    )
    return BudgetConstraint(
        amount=Money(amount=Decimal(amount), currency=currency),
        mode=BudgetMode.HARD_CAP if hard_cap else BudgetMode.PREFERRED,
        source=FieldSource.INFERRED,
    )


def _has_use_case(input_data: ShoppingGuideAgentInput) -> bool:
    normalized = " ".join(_known_texts(input_data)).casefold()
    use_case_terms = (
        "for ",
        "coding",
        "movies",
        "gaming",
        "travel",
        "commute",
        "work",
        "school",
        "calls",
        "noise-cancelling",
        "battery",
        "portable",
    )
    return any(term in normalized for term in use_case_terms)


def _mentions_considered_products(user_input: str) -> bool:
    normalized = user_input.casefold()
    return any(
        term in normalized
        for term in ("considering", "between ", " vs ", "already looking at")
    )


def _looks_like_budget(text: str) -> bool:
    lowered = text.casefold()
    return bool(re.search(r"(?:\$|php|₱|\bunder\b|\bbelow\b|\baround\b)", lowered))


def _looks_like_constraint(text: str) -> bool:
    lowered = text.casefold()
    return any(
        term in lowered
        for term in (
            "must",
            "need",
            "required",
            "can't",
            "cannot",
            "under",
            "below",
            "long battery",
            "fit",
            "27-inch",
            "27 inch",
            "1440p",
        )
    )
