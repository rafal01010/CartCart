import pytest
from pydantic import ValidationError

from app.schemas import (
    AnalysisStartAvailability,
    CombinedOptionalQuestionPrompt,
    CurrentGuidedQuestion,
    GuidedAnswerSubmission,
    GuidedAnswerSurface,
    GuidedCaptureTarget,
    GuidedIntakeState,
    GuidedIntakeStatus,
    GuidedQuestionPurpose,
    InlineChoiceControl,
    InlineChoiceControlType,
    InlineChoiceOption,
    LocalRegionSetupState,
    PriorQuestionNavigationState,
    ProgressDisplayKind,
    ProgressDisplayStatus,
    ReanswerableQuestion,
    Region,
    RegionSetupStatus,
    RegionSetupSubmission,
    ShoppingBrief,
    ShoppingGuardrailDecision,
    ShoppingGuardrailReason,
    ShoppingGuardrailResult,
    SkippableQuestionState,
)


def test_guided_intake_state_supports_combined_optional_textbox_prompt() -> None:
    question = CurrentGuidedQuestion(
        question_id="optional-context",
        text="Anything we should keep in mind, like budget or laptops you are already considering?",
        purpose=GuidedQuestionPurpose.COMBINED_OPTIONAL,
        capture_targets=(
            GuidedCaptureTarget.BUDGET,
            GuidedCaptureTarget.CONSIDERED_PRODUCT_NAMES,
        ),
        combined_optional_prompt=CombinedOptionalQuestionPrompt(
            text="Share any budget, must-haves, or products you are already considering.",
            capture_targets=(
                GuidedCaptureTarget.BUDGET,
                GuidedCaptureTarget.CONSTRAINTS,
                GuidedCaptureTarget.CONSIDERED_PRODUCT_NAMES,
            ),
        ),
    )
    state = GuidedIntakeState(
        current_question=question,
        skippable_question=SkippableQuestionState(can_skip=True),
        analysis_start=AnalysisStartAvailability(
            enough_information=True,
            can_skip_all_and_start_analysis=True,
            message="We can start with what you have already shared.",
        ),
        region_setup=LocalRegionSetupState(status=RegionSetupStatus.NOT_NEEDED),
    )

    assert state.status == GuidedIntakeStatus.COLLECTING
    assert state.current_question is not None
    assert state.current_question.answer_surface == GuidedAnswerSurface.TEXTBOX
    assert state.skippable_question.label == "Skip question"
    assert state.analysis_start.label == "Skip all and start analysis"


def test_guided_answer_submission_accepts_natural_language_budget_and_products() -> None:
    budget_answer = GuidedAnswerSubmission(
        question_id="optional-context",
        answer={
            "answer_type": "natural_language",
            "text": "Around $1,200 if possible. I am also looking at the ThinkPad X1 Carbon.",
        },
    )

    assert budget_answer.answer.answer_type == "natural_language"


def test_guided_answer_submission_accepts_yes_no_and_choice_answers() -> None:
    yes_no_answer = GuidedAnswerSubmission(
        question_id="touchscreen",
        answer={"answer_type": "yes_no", "value": False},
    )
    choice_answer = GuidedAnswerSubmission(
        question_id="portable-or-powerful",
        answer={"answer_type": "choice", "choice_id": "portable"},
    )
    typed_choice_answer = GuidedAnswerSubmission(
        question_id="portable-or-powerful",
        answer={
            "answer_type": "choice_with_text",
            "choice_id": "something-else",
            "text": "I want a quiet laptop more than either option.",
        },
    )

    assert yes_no_answer.answer.value is False
    assert choice_answer.answer.choice_id == "portable"
    assert typed_choice_answer.answer.text.startswith("I want a quiet laptop")


def test_inline_choice_controls_validate_yes_no_and_two_option_type_answer_shapes() -> None:
    yes_no = InlineChoiceControl(
        control_id="touchscreen-choice",
        control_type=InlineChoiceControlType.YES_NO,
        options=(
            InlineChoiceOption(choice_id="yes", label="Yes"),
            InlineChoiceOption(choice_id="no", label="No"),
        ),
    )
    two_option_plus_type = InlineChoiceControl(
        control_id="priority-choice",
        control_type=InlineChoiceControlType.TWO_OPTION_PLUS_TYPE_ANSWER,
        options=(
            InlineChoiceOption(choice_id="portable", label="More portable"),
            InlineChoiceOption(choice_id="powerful", label="More powerful"),
        ),
        custom_answer_label="Type my answer",
    )

    assert yes_no.options[0].label == "Yes"
    assert two_option_plus_type.custom_answer_label == "Type my answer"

    with pytest.raises(ValidationError):
        InlineChoiceControl(
            control_id="missing-type-answer",
            control_type=InlineChoiceControlType.TWO_OPTION_PLUS_TYPE_ANSWER,
            options=(
                InlineChoiceOption(choice_id="portable", label="More portable"),
                InlineChoiceOption(choice_id="powerful", label="More powerful"),
            ),
        )


def test_inline_choice_question_requires_inline_choice_control() -> None:
    with pytest.raises(ValidationError):
        CurrentGuidedQuestion(
            question_id="priority-choice",
            text="Would you rather prioritize portability or power?",
            purpose=GuidedQuestionPurpose.PRIORITIES,
            answer_surface=GuidedAnswerSurface.INLINE_CHOICE,
        )


def test_prior_question_navigation_supports_reanswer_state() -> None:
    navigation = PriorQuestionNavigationState(
        can_go_back=True,
        current_reanswer_question_id="budget",
        reanswerable_questions=(
            ReanswerableQuestion(question_id="first", label="Original question"),
            ReanswerableQuestion(question_id="budget", label="Budget and priorities"),
        ),
    )

    assert navigation.current_reanswer_question_id == "budget"

    with pytest.raises(ValidationError):
        PriorQuestionNavigationState(
            can_go_back=True,
            current_reanswer_question_id="unknown",
            reanswerable_questions=(
                ReanswerableQuestion(question_id="budget", label="Budget"),
            ),
        )


def test_skip_all_requires_enough_information_to_start_analysis() -> None:
    with pytest.raises(ValidationError):
        AnalysisStartAvailability(
            enough_information=False,
            can_skip_all_and_start_analysis=True,
        )


def test_region_setup_tracks_provided_and_refused_states() -> None:
    provided = LocalRegionSetupState(
        status=RegionSetupStatus.PROVIDED,
        region=Region(country_code="US", currency="USD"),
        resumes_pending_question=True,
    )
    refused = LocalRegionSetupState(status=RegionSetupStatus.REFUSED)
    provided_submission = RegionSetupSubmission(
        status=RegionSetupStatus.PROVIDED,
        region=Region(country_code="PH", currency="PHP"),
    )
    refused_submission = RegionSetupSubmission(status=RegionSetupStatus.REFUSED)

    assert provided.region is not None
    assert refused.region is None
    assert provided_submission.region is not None
    assert refused_submission.region is None

    with pytest.raises(ValidationError):
        RegionSetupSubmission(status=RegionSetupStatus.PROVIDED)

    with pytest.raises(ValidationError):
        LocalRegionSetupState(
            status=RegionSetupStatus.REFUSED,
            region=Region(country_code="US"),
        )


def test_guardrail_result_returns_user_safe_blocked_redirection() -> None:
    guardrail = ShoppingGuardrailResult(
        decision=ShoppingGuardrailDecision.BLOCKED,
        reason=ShoppingGuardrailReason.OFF_TOPIC,
        message="I can help with shopping decisions. Try asking what to buy or compare.",
    )
    blocked_state = GuidedIntakeState(
        status=GuidedIntakeStatus.BLOCKED,
        guardrail=guardrail,
        progress=ProgressDisplayStatus(
            kind=ProgressDisplayKind.BLOCKED,
            message="This request is outside shopping help.",
        ),
    )

    assert blocked_state.guardrail is not None
    assert blocked_state.guardrail.reason == ShoppingGuardrailReason.OFF_TOPIC

    with pytest.raises(ValidationError):
        ShoppingGuardrailResult(decision=ShoppingGuardrailDecision.BLOCKED)


def test_ready_for_analysis_state_requires_enough_information_and_brief() -> None:
    state = GuidedIntakeState(
        status=GuidedIntakeStatus.READY_FOR_ANALYSIS,
        analysis_start=AnalysisStartAvailability(enough_information=True),
        ready_brief=ShoppingBrief(
            original_query="Which laptop should I buy for travel?"
        ),
    )

    assert state.ready_brief is not None

    with pytest.raises(ValidationError):
        GuidedIntakeState(
            status=GuidedIntakeStatus.READY_FOR_ANALYSIS,
            analysis_start=AnalysisStartAvailability(enough_information=False),
        )


def test_user_facing_models_reject_developer_only_fields_and_language() -> None:
    with pytest.raises(ValidationError):
        CurrentGuidedQuestion(
            question_id="budget",
            text="What budget should the agent use?",
            purpose=GuidedQuestionPurpose.BUDGET,
        )

    with pytest.raises(ValidationError):
        CurrentGuidedQuestion(
            question_id="known-products",
            text="Paste a product URL for anything you are considering.",
            purpose=GuidedQuestionPurpose.CONSIDERED_PRODUCTS,
        )

    with pytest.raises(ValidationError):
        CurrentGuidedQuestion(
            question_id="budget",
            text="What budget should we keep in mind?",
            purpose=GuidedQuestionPurpose.BUDGET,
            agent_name="ShoppingGuideAgent",
        )

    with pytest.raises(ValidationError):
        CurrentGuidedQuestion(
            question_id="budget",
            text="What budget should we keep in mind?",
            purpose=GuidedQuestionPurpose.BUDGET,
            form_fields=[{"label": "Budget"}, {"label": "Product"}],
        )
