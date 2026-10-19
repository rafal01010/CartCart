import pytest
from pydantic import BaseModel, ValidationError

from app.schemas import (
    AnalysisStartAvailability,
    CombinedOptionalQuestionPrompt,
    CreateGuidedSessionRequest,
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
    SourceReference,
)


def test_guided_intake_state_supports_single_textbox_prompt() -> None:
    question = CurrentGuidedQuestion(
        question_id="budget",
        text="What budget should we stay near?",
        purpose=GuidedQuestionPurpose.BUDGET,
        capture_targets=(GuidedCaptureTarget.BUDGET,),
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
        question_id="budget",
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


@pytest.mark.parametrize(
    "status",
    (
        GuidedIntakeStatus.COLLECTING,
        GuidedIntakeStatus.READY_FOR_ANALYSIS,
        GuidedIntakeStatus.ANALYSIS_STARTED,
    ),
)
def test_blocked_guardrail_cannot_advertise_an_active_guided_state(
    status: GuidedIntakeStatus,
) -> None:
    with pytest.raises(ValidationError, match="blocked guardrail requires blocked"):
        GuidedIntakeState(
            status=status,
            current_question=(
                CurrentGuidedQuestion(
                    question_id="budget",
                    text="What budget should we stay near?",
                    purpose=GuidedQuestionPurpose.BUDGET,
                )
                if status == GuidedIntakeStatus.COLLECTING
                else None
            ),
            analysis_start=AnalysisStartAvailability(enough_information=True),
            ready_brief=ShoppingBrief(original_query="Help me choose a laptop."),
            guardrail=ShoppingGuardrailResult(
                decision=ShoppingGuardrailDecision.BLOCKED,
                reason=ShoppingGuardrailReason.UNSAFE_PRODUCT,
                message="I can help with ordinary consumer purchases.",
            ),
        )


@pytest.mark.parametrize(
    "contradiction",
    (
        {"analysis_start": {"enough_information": True}},
        {
            "analysis_start": {
                "enough_information": True,
                "can_skip_all_and_start_analysis": True,
            }
        },
        {"ready_brief": {"original_query": "Help me choose a laptop."}},
        {
            "current_question": {
                "question_id": "budget",
                "text": "What budget should we stay near?",
                "purpose": "budget",
            }
        },
    ),
)
def test_blocked_state_cannot_offer_analysis_or_an_answer(
    contradiction: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="blocked intake cannot offer"):
        GuidedIntakeState.model_validate(
            {
                "status": "blocked",
                "guardrail": {
                    "decision": "blocked",
                    "reason": "off_topic",
                    "message": "I can help with shopping decisions.",
                },
                **contradiction,
            }
        )


@pytest.mark.parametrize("status", tuple(GuidedIntakeStatus))
def test_valid_guided_statuses_roundtrip_with_region_refusal(
    status: GuidedIntakeStatus,
) -> None:
    state = GuidedIntakeState(
        status=status,
        current_question=(
            CurrentGuidedQuestion(
                question_id="budget",
                text="What budget should we stay near?",
                purpose=GuidedQuestionPurpose.BUDGET,
            )
            if status == GuidedIntakeStatus.COLLECTING
            else None
        ),
        analysis_start=AnalysisStartAvailability(
            enough_information=status == GuidedIntakeStatus.READY_FOR_ANALYSIS,
        ),
        ready_brief=(
            ShoppingBrief(original_query="Help me choose a laptop.")
            if status == GuidedIntakeStatus.READY_FOR_ANALYSIS
            else None
        ),
        guardrail=(
            ShoppingGuardrailResult(
                decision=ShoppingGuardrailDecision.BLOCKED,
                reason=ShoppingGuardrailReason.OFF_TOPIC,
                message="I can help with shopping decisions.",
            )
            if status == GuidedIntakeStatus.BLOCKED
            else None
        ),
        region_setup=LocalRegionSetupState(status=RegionSetupStatus.REFUSED),
    )

    assert GuidedIntakeState.model_validate_json(state.model_dump_json()) == state
    assert state.model_dump(mode="json")["region_setup"]["status"] == "refused"


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


GENERATED_TEXT_FIELDS = (
    pytest.param(
        CurrentGuidedQuestion,
        "text",
        {"question_id": "color", "purpose": "priorities"},
        id="question",
    ),
    pytest.param(
        CombinedOptionalQuestionPrompt,
        "text",
        {"capture_targets": ["budget", "priorities"]},
        id="combined-prompt",
    ),
    pytest.param(InlineChoiceOption, "label", {"choice_id": "color"}, id="choice-label"),
    pytest.param(
        InlineChoiceOption,
        "description",
        {"choice_id": "color", "label": "Color"},
        id="choice-description",
    ),
    pytest.param(
        InlineChoiceControl,
        "custom_answer_label",
        {
            "control_id": "color",
            "control_type": "two_option_plus_type_answer",
            "options": [
                {"choice_id": "magenta", "label": "Magenta"},
                {"choice_id": "black", "label": "Black"},
            ],
        },
        id="custom-answer-label",
    ),
    pytest.param(
        ReanswerableQuestion,
        "label",
        {"question_id": "color"},
        id="reanswer-label",
    ),
    pytest.param(AnalysisStartAvailability, "message", {}, id="analysis-message"),
    pytest.param(LocalRegionSetupState, "prompt_text", {}, id="region-prompt"),
    pytest.param(ProgressDisplayStatus, "message", {"kind": "idle"}, id="progress"),
    pytest.param(
        ShoppingGuardrailResult,
        "message",
        {"decision": "blocked", "reason": "off_topic"},
        id="guardrail-message",
    ),
)


@pytest.mark.parametrize("schema,field,payload", GENERATED_TEXT_FIELDS)
@pytest.mark.parametrize(
    "text",
    (
        "Would you prefer magenta or black?",
        "Magenta detergent refill",
        "Reagent test strips",
        "A fragrance-free detergent",
        "Providerplus compatible accessories",
        "A power tool for cabinet repairs",
        "Tracing paper and running shoes",
        "Prompt delivery from the seller",
    ),
)
def test_generated_guided_copy_preserves_ordinary_shopping_words(
    schema: type[BaseModel], field: str, payload: dict[str, object], text: str
) -> None:
    model = schema.model_validate({**payload, field: text})

    assert model.model_dump(mode="json")[field] == text
    assert schema.model_validate_json(model.model_dump_json()).model_dump()[field] == text


@pytest.mark.parametrize("schema,field,payload", GENERATED_TEXT_FIELDS)
@pytest.mark.parametrize(
    "text",
    (
        "Ask the agent for a budget.",
        "Our agents are comparing options.",
        "Waiting for ShoppingGuideAgent.",
        "Waiting for CartCartShoppingGuideAgent.",
        "Waiting for TVSpecialistAgent.",
        "Waiting for shopping_guide_agent.",
        "Waiting for the provider.",
        "Our providers returned no results.",
        "Waiting for FakeSearchProvider.",
        "Waiting for serp_api_amazon_provider.",
        "Trace ID is available.",
        "trace_id is available.",
        "trace_abc123 is available.",
        "Run ID is available.",
        "run_id is available.",
        "run_abc123 is available.",
        "A tool call is pending.",
        "Tool_calls are pending.",
        "Read the raw prompt.",
        "Read the raw_prompt.",
        "Paste a product URL.",
        "Share the product link.",
        "Paste a URL.",
        "Paste the URL.",
        "Paste a link.",
        "Paste the link.",
    ),
)
def test_generated_guided_copy_rejects_internal_details_and_link_requests(
    schema: type[BaseModel], field: str, payload: dict[str, object], text: str
) -> None:
    with pytest.raises(ValidationError, match="user-facing text cannot include"):
        schema.model_validate({**payload, field: text})


@pytest.mark.parametrize("schema,field,payload", GENERATED_TEXT_FIELDS)
@pytest.mark.parametrize(
    "developer_field", ("agent_name", "provider_name", "trace_id", "tool_calls", "raw_prompt")
)
def test_generated_guided_models_still_forbid_unknown_developer_fields(
    schema: type[BaseModel],
    field: str,
    payload: dict[str, object],
    developer_field: str,
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        schema.model_validate(
            {**payload, field: "Magenta", developer_field: "internal detail"}
        )


@pytest.mark.parametrize("answer_type", ("natural_language", "choice_with_text"))
def test_submitted_shopper_and_source_literals_bypass_generated_copy_policy(
    answer_type: str,
) -> None:
    text = "  ShoppingGuideAgent provider trace_id run_abc123 raw prompt product link  "
    submitted = GuidedAnswerSubmission.model_validate(
        {
            "question_id": "color",
            "answer": {"answer_type": answer_type, "text": text},
        }
    )
    request = CreateGuidedSessionRequest(query=text)
    brief = ShoppingBrief(original_query=text)
    source = SourceReference.model_validate(
        {
            "source_id": "00000000-0000-0000-0000-000000000001",
            "url": "https://example.com/product",
            "title": text,
        }
    )

    assert submitted.model_dump(mode="json")["answer"]["text"] == text
    assert request.query == text
    assert brief.original_query == text
    assert source.title == text
