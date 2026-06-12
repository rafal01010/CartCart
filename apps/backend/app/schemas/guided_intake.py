from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.ids import SessionId
from app.schemas.intake import ShoppingBrief
from app.schemas.regions import Region


QuestionId = Annotated[str, Field(min_length=1, max_length=120)]
ChoiceId = Annotated[str, Field(min_length=1, max_length=80)]


DEVELOPER_LANGUAGE = (
    "agent",
    "provider",
    "trace id",
    "trace_id",
    "tool call",
    "raw prompt",
    "run id",
    "run_id",
)
PRODUCT_LINK_REQUESTS = (
    "product url",
    "product link",
    "paste a url",
    "paste the url",
    "paste a link",
    "paste the link",
)


def _validate_user_facing_text(value: str | None) -> str | None:
    if value is None:
        return value
    normalized = value.lower()
    blocked_terms = DEVELOPER_LANGUAGE + PRODUCT_LINK_REQUESTS
    for term in blocked_terms:
        if term in normalized:
            raise ValueError(f"user-facing text cannot include {term!r}.")
    return value


class GuidedIntakeStatus(StrEnum):
    COLLECTING = "collecting"
    BLOCKED = "blocked"
    READY_FOR_ANALYSIS = "ready_for_analysis"
    ANALYSIS_STARTED = "analysis_started"


class GuidedAnswerSurface(StrEnum):
    TEXTBOX = "textbox"
    INLINE_CHOICE = "inline_choice"


class GuidedQuestionPurpose(StrEnum):
    FIRST_QUESTION = "first_question"
    USE_CASE = "use_case"
    BUDGET = "budget"
    PRIORITIES = "priorities"
    CONSTRAINTS = "constraints"
    CONSIDERED_PRODUCTS = "considered_products"
    COMPARISON = "comparison"
    COMBINED_OPTIONAL = "combined_optional"
    CLARIFICATION = "clarification"


class GuidedCaptureTarget(StrEnum):
    SHOPPING_QUESTION = "shopping_question"
    USE_CASE = "use_case"
    BUDGET = "budget"
    PRIORITIES = "priorities"
    CONSTRAINTS = "constraints"
    CONSIDERED_PRODUCT_NAMES = "considered_product_names"
    CONSIDERED_PRODUCT_DESCRIPTIONS = "considered_product_descriptions"
    COMPARISON_CANDIDATES = "comparison_candidates"
    PRODUCT_CATEGORY = "product_category"


class InlineChoiceControlType(StrEnum):
    YES_NO = "yes_no"
    TWO_OPTION = "two_option"
    TWO_OPTION_PLUS_TYPE_ANSWER = "two_option_plus_type_answer"


class InlineChoiceOption(CartCartBaseModel):
    choice_id: ChoiceId
    label: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, min_length=1, max_length=240)

    _label_is_user_safe = field_validator("label")(_validate_user_facing_text)
    _description_is_user_safe = field_validator("description")(
        _validate_user_facing_text
    )


class InlineChoiceControl(CartCartBaseModel):
    control_id: str = Field(min_length=1, max_length=80)
    control_type: InlineChoiceControlType
    options: tuple[InlineChoiceOption, InlineChoiceOption]
    custom_answer_label: str | None = Field(default=None, min_length=1, max_length=80)

    _custom_answer_label_is_user_safe = field_validator("custom_answer_label")(
        _validate_user_facing_text
    )

    @model_validator(mode="after")
    def _validate_choice_shape(self) -> "InlineChoiceControl":
        option_ids = {option.choice_id for option in self.options}
        if len(option_ids) != len(self.options):
            raise ValueError("inline choice option IDs must be unique.")

        if (
            self.control_type == InlineChoiceControlType.TWO_OPTION_PLUS_TYPE_ANSWER
            and self.custom_answer_label is None
        ):
            raise ValueError(
                "two-option-plus-type-answer controls require a custom answer label."
            )
        if (
            self.control_type != InlineChoiceControlType.TWO_OPTION_PLUS_TYPE_ANSWER
            and self.custom_answer_label is not None
        ):
            raise ValueError(
                "custom answer labels are only allowed for two-option-plus-type-answer controls."
            )
        return self


class CombinedOptionalQuestionPrompt(CartCartBaseModel):
    text: str = Field(min_length=1, max_length=600)
    capture_targets: tuple[GuidedCaptureTarget, ...] = Field(min_length=2, max_length=5)

    _text_is_user_safe = field_validator("text")(_validate_user_facing_text)


class CurrentGuidedQuestion(VersionedSchema):
    question_id: QuestionId
    text: str = Field(min_length=1, max_length=600)
    purpose: GuidedQuestionPurpose
    answer_surface: GuidedAnswerSurface = GuidedAnswerSurface.TEXTBOX
    capture_targets: tuple[GuidedCaptureTarget, ...] = Field(
        default_factory=tuple,
        max_length=5,
    )
    inline_choice: InlineChoiceControl | None = None
    combined_optional_prompt: CombinedOptionalQuestionPrompt | None = None

    _text_is_user_safe = field_validator("text")(_validate_user_facing_text)

    @model_validator(mode="after")
    def _validate_answer_surface(self) -> "CurrentGuidedQuestion":
        if self.answer_surface == GuidedAnswerSurface.INLINE_CHOICE:
            if self.inline_choice is None:
                raise ValueError("inline choice questions require inline_choice.")
            if self.combined_optional_prompt is not None:
                raise ValueError(
                    "combined optional prompts use the textbox answer surface."
                )
        if self.answer_surface == GuidedAnswerSurface.TEXTBOX and self.inline_choice:
            raise ValueError("textbox questions cannot include inline_choice.")
        if (
            self.combined_optional_prompt is not None
            and self.purpose != GuidedQuestionPurpose.COMBINED_OPTIONAL
        ):
            raise ValueError(
                "combined_optional_prompt is only valid for combined optional questions."
            )
        return self


class NaturalLanguageGuidedAnswer(CartCartBaseModel):
    answer_type: Literal["natural_language"] = "natural_language"
    text: str = Field(min_length=1, max_length=4000)


class YesNoGuidedAnswer(CartCartBaseModel):
    answer_type: Literal["yes_no"] = "yes_no"
    value: bool


class ChoiceGuidedAnswer(CartCartBaseModel):
    answer_type: Literal["choice"] = "choice"
    choice_id: ChoiceId


class ChoiceWithTextGuidedAnswer(CartCartBaseModel):
    answer_type: Literal["choice_with_text"] = "choice_with_text"
    text: str = Field(min_length=1, max_length=4000)
    choice_id: ChoiceId | None = None


GuidedAnswer = Annotated[
    NaturalLanguageGuidedAnswer
    | YesNoGuidedAnswer
    | ChoiceGuidedAnswer
    | ChoiceWithTextGuidedAnswer,
    Field(discriminator="answer_type"),
]


class GuidedAnswerSubmission(VersionedSchema):
    question_id: QuestionId
    answer: GuidedAnswer


class CreateGuidedSessionRequest(CartCartBaseModel):
    query: str = Field(min_length=1, max_length=4000)
    region_setup: "RegionSetupSubmission | None" = None


class GuidedSessionResponse(VersionedSchema):
    session_id: SessionId
    guide: "GuidedIntakeState"


class GuidedReanswerRequest(CartCartBaseModel):
    question_id: QuestionId


class ReanswerableQuestion(CartCartBaseModel):
    question_id: QuestionId
    label: str = Field(min_length=1, max_length=120)

    _label_is_user_safe = field_validator("label")(_validate_user_facing_text)


class PriorQuestionNavigationState(CartCartBaseModel):
    can_go_back: bool = False
    current_reanswer_question_id: QuestionId | None = None
    reanswerable_questions: tuple[ReanswerableQuestion, ...] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def _validate_navigation_state(self) -> "PriorQuestionNavigationState":
        if not self.can_go_back and self.reanswerable_questions:
            raise ValueError("reanswerable questions require can_go_back.")
        if (
            self.current_reanswer_question_id is not None
            and self.current_reanswer_question_id
            not in {question.question_id for question in self.reanswerable_questions}
        ):
            raise ValueError("current reanswer question must be reanswerable.")
        return self


class SkippableQuestionState(CartCartBaseModel):
    can_skip: bool = False
    label: Literal["Skip question"] = "Skip question"

    @model_validator(mode="after")
    def _validate_skip_label(self) -> "SkippableQuestionState":
        if not self.can_skip and self.label != "Skip question":
            raise ValueError("skip label is fixed for optional questions.")
        return self


class AnalysisStartAvailability(CartCartBaseModel):
    enough_information: bool = False
    can_skip_all_and_start_analysis: bool = False
    label: Literal["Skip all and start analysis"] = "Skip all and start analysis"
    message: str | None = Field(default=None, min_length=1, max_length=300)

    _message_is_user_safe = field_validator("message")(_validate_user_facing_text)

    @model_validator(mode="after")
    def _validate_start_availability(self) -> "AnalysisStartAvailability":
        if self.can_skip_all_and_start_analysis and not self.enough_information:
            raise ValueError(
                "skip-all start requires enough information to start analysis."
            )
        return self


class RegionSetupStatus(StrEnum):
    NOT_NEEDED = "not_needed"
    NEEDS_ANSWER = "needs_answer"
    PROVIDED = "provided"
    REFUSED = "refused"


class LocalRegionSetupState(CartCartBaseModel):
    status: RegionSetupStatus = RegionSetupStatus.NOT_NEEDED
    prompt_text: str | None = Field(default=None, min_length=1, max_length=400)
    region: Region | None = None
    can_refuse: bool = True
    resumes_pending_question: bool = False

    _prompt_text_is_user_safe = field_validator("prompt_text")(
        _validate_user_facing_text
    )

    @model_validator(mode="after")
    def _validate_region_status(self) -> "LocalRegionSetupState":
        if self.status == RegionSetupStatus.NEEDS_ANSWER and self.prompt_text is None:
            raise ValueError("region setup prompt text is required when asking.")
        if self.status == RegionSetupStatus.PROVIDED and self.region is None:
            raise ValueError("provided region setup requires a region.")
        if self.status == RegionSetupStatus.REFUSED and self.region is not None:
            raise ValueError("refused region setup cannot include a region.")
        if self.status in {RegionSetupStatus.NOT_NEEDED, RegionSetupStatus.NEEDS_ANSWER}:
            if self.region is not None:
                raise ValueError("region is only allowed after it is provided.")
        return self


class RegionSetupSubmission(CartCartBaseModel):
    status: Literal[RegionSetupStatus.PROVIDED, RegionSetupStatus.REFUSED]
    region: Region | None = None

    @model_validator(mode="after")
    def _validate_region_submission(self) -> "RegionSetupSubmission":
        if self.status == RegionSetupStatus.PROVIDED and self.region is None:
            raise ValueError("provided region setup requires a region.")
        if self.status == RegionSetupStatus.REFUSED and self.region is not None:
            raise ValueError("refused region setup cannot include a region.")
        return self


class ProgressDisplayKind(StrEnum):
    IDLE = "idle"
    CHECKING_OPTIONS = "checking_options"
    COMPARING_EVIDENCE = "comparing_evidence"
    VERIFYING_RISKY_LISTINGS = "verifying_risky_listings"
    PREPARING_RECOMMENDATION = "preparing_recommendation"
    READY = "ready"
    BLOCKED = "blocked"


class ProgressDisplayStatus(CartCartBaseModel):
    kind: ProgressDisplayKind
    message: str = Field(min_length=1, max_length=300)

    _message_is_user_safe = field_validator("message")(_validate_user_facing_text)


class ShoppingGuardrailDecision(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


class ShoppingGuardrailReason(StrEnum):
    OFF_TOPIC = "off_topic"
    UNSAFE_PRODUCT = "unsafe_product"
    ILLEGAL_PRODUCT = "illegal_product"
    INAPPROPRIATE_PRODUCT = "inappropriate_product"


class ShoppingGuardrailResult(VersionedSchema):
    decision: ShoppingGuardrailDecision
    reason: ShoppingGuardrailReason | None = None
    message: str | None = Field(default=None, min_length=1, max_length=300)

    _message_is_user_safe = field_validator("message")(_validate_user_facing_text)

    @model_validator(mode="after")
    def _validate_guardrail_result(self) -> "ShoppingGuardrailResult":
        if self.decision == ShoppingGuardrailDecision.BLOCKED:
            if self.reason is None:
                raise ValueError("blocked guardrail results require a reason.")
            if self.message is None:
                raise ValueError("blocked guardrail results require a user message.")
        if self.decision == ShoppingGuardrailDecision.ALLOWED:
            if self.reason is not None or self.message is not None:
                raise ValueError(
                    "allowed guardrail results cannot include block reason or message."
                )
        return self


class GuidedIntakeState(VersionedSchema):
    status: GuidedIntakeStatus = GuidedIntakeStatus.COLLECTING
    current_question: CurrentGuidedQuestion | None = None
    navigation: PriorQuestionNavigationState = Field(
        default_factory=PriorQuestionNavigationState
    )
    skippable_question: SkippableQuestionState = Field(
        default_factory=SkippableQuestionState
    )
    analysis_start: AnalysisStartAvailability = Field(
        default_factory=AnalysisStartAvailability
    )
    region_setup: LocalRegionSetupState = Field(default_factory=LocalRegionSetupState)
    progress: ProgressDisplayStatus | None = None
    guardrail: ShoppingGuardrailResult | None = None
    ready_brief: ShoppingBrief | None = None

    @model_validator(mode="after")
    def _validate_guided_state(self) -> "GuidedIntakeState":
        if self.status == GuidedIntakeStatus.COLLECTING and self.current_question is None:
            raise ValueError("collecting intake state requires a current question.")
        if self.status == GuidedIntakeStatus.BLOCKED:
            if (
                self.guardrail is None
                or self.guardrail.decision != ShoppingGuardrailDecision.BLOCKED
            ):
                raise ValueError("blocked intake state requires a blocked guardrail.")
        if self.status == GuidedIntakeStatus.READY_FOR_ANALYSIS:
            if not self.analysis_start.enough_information:
                raise ValueError(
                    "ready-for-analysis state requires enough information."
                )
            if self.ready_brief is None:
                raise ValueError("ready-for-analysis state requires a shopping brief.")
        return self
