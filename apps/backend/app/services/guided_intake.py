from dataclasses import dataclass, field
from decimal import Decimal
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApplicationError
from app.db.repositories.products import ProductRepository
from app.db.repositories.sessions import SessionRepository
from app.schemas.guided_intake import (
    AnalysisStartAvailability,
    ChoiceGuidedAnswer,
    ChoiceWithTextGuidedAnswer,
    CombinedOptionalQuestionPrompt,
    CreateGuidedSessionRequest,
    CurrentGuidedQuestion,
    GuidedAnswer,
    GuidedAnswerSubmission,
    GuidedAnswerSurface,
    GuidedCaptureTarget,
    GuidedIntakeState,
    GuidedIntakeStatus,
    GuidedQuestionPurpose,
    GuidedReanswerRequest,
    GuidedSessionResponse,
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
    ShoppingGuardrailReason,
    ShoppingGuardrailResult,
    SkippableQuestionState,
    YesNoGuidedAnswer,
)
from app.schemas.ids import SessionId
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
from app.schemas.products import UserAddedProduct
from app.schemas.regions import Region


FIRST_QUESTION_ID = "first-question"
MONITOR_CONNECTION_QUESTION_ID = "monitor-connection"
COMPARISON_PRIORITY_QUESTION_ID = "comparison-priority"
OPTIONAL_CONTEXT_QUESTION_ID = "optional-context"


@dataclass
class FixtureGuidedSession:
    session_id: SessionId
    query: str
    region_setup: RegionSetupSubmission | None = None
    answers: dict[str, GuidedAnswer] = field(default_factory=dict)
    skipped_question_ids: set[str] = field(default_factory=set)
    reanswer_question_id: str | None = None
    started_analysis: bool = False
    blocked_guardrail: ShoppingGuardrailResult | None = None
    user_added_texts: set[str] = field(default_factory=set)


_fixture_sessions: dict[SessionId, FixtureGuidedSession] = {}


class GuidedIntakeService:
    def __init__(self, db_session: AsyncSession) -> None:
        self._sessions = SessionRepository(db_session)
        self._products = ProductRepository(db_session)

    async def create_guided_session(
        self,
        request: CreateGuidedSessionRequest,
    ) -> GuidedSessionResponse:
        region_preference = _region_preference_from_setup(request.region_setup)
        create_request = CreateSessionRequest(
            query=request.query,
            region=region_preference,
        )
        brief = ShoppingBrief(
            original_query=request.query,
            region=region_preference,
            **_category_fields(request.query),
        )
        session = await self._sessions.create(
            original_input=create_request,
            current_brief=brief,
        )
        fixture = FixtureGuidedSession(
            session_id=session.session_id,
            query=request.query,
            region_setup=request.region_setup,
            blocked_guardrail=_guardrail_for_query(request.query),
        )
        _fixture_sessions[session.session_id] = fixture
        return GuidedSessionResponse(
            session_id=session.session_id,
            guide=self._state_for_fixture(fixture),
        )

    async def load_state(self, session_id: SessionId) -> GuidedIntakeState | None:
        fixture = await self._fixture_for_session(session_id)
        if fixture is None:
            return None
        return self._state_for_fixture(fixture)

    async def submit_answer(
        self,
        session_id: SessionId,
        submission: GuidedAnswerSubmission,
    ) -> GuidedIntakeState | None:
        fixture = await self._fixture_for_session(session_id)
        if fixture is None:
            return None

        current_question = self._current_question_for_fixture(fixture)
        if current_question is None:
            raise _guide_not_collecting(session_id)
        if submission.question_id != current_question.question_id:
            raise ApplicationError(
                "guided_question_mismatch",
                "That answer is for a different question.",
                status_code=409,
                details={
                    "expected_question_id": current_question.question_id,
                    "received_question_id": submission.question_id,
                },
            )

        was_reanswering = fixture.reanswer_question_id is not None
        fixture.answers[submission.question_id] = submission.answer
        fixture.reanswer_question_id = None

        if submission.question_id == OPTIONAL_CONTEXT_QUESTION_ID:
            await self._capture_optional_context(fixture, submission.answer)
            await self._persist_ready_brief(fixture)

        if self._is_ready_after_answer(
            fixture,
            submission.question_id,
            was_reanswering=was_reanswering,
        ):
            return self._ready_state_for_fixture(fixture)

        return self._state_for_fixture(fixture)

    async def skip_question(self, session_id: SessionId) -> GuidedIntakeState | None:
        fixture = await self._fixture_for_session(session_id)
        if fixture is None:
            return None

        question = self._current_question_for_fixture(fixture)
        if question is None:
            raise _guide_not_collecting(session_id)
        if question.question_id != OPTIONAL_CONTEXT_QUESTION_ID:
            raise ApplicationError(
                "guided_question_not_skippable",
                "This question needs an answer before we continue.",
                status_code=409,
                details={"question_id": question.question_id},
            )

        fixture.skipped_question_ids.add(question.question_id)
        fixture.reanswer_question_id = None
        await self._persist_ready_brief(fixture)
        return self._ready_state_for_fixture(fixture)

    async def skip_all_and_start_analysis(
        self,
        session_id: SessionId,
    ) -> GuidedIntakeState | None:
        fixture = await self._fixture_for_session(session_id)
        if fixture is None:
            return None
        if fixture.blocked_guardrail is not None:
            raise _guide_not_collecting(session_id)

        fixture.started_analysis = True
        await self._persist_ready_brief(fixture)
        return self._ready_state_for_fixture(fixture)

    async def reanswer_question(
        self,
        session_id: SessionId,
        request: GuidedReanswerRequest,
    ) -> GuidedIntakeState | None:
        fixture = await self._fixture_for_session(session_id)
        if fixture is None:
            return None
        if request.question_id not in self._answered_question_ids(fixture):
            raise ApplicationError(
                "guided_question_not_reanswerable",
                "That question cannot be changed right now.",
                status_code=409,
                details={"question_id": request.question_id},
            )

        fixture.reanswer_question_id = request.question_id
        return self._state_for_fixture(fixture)

    async def submit_region_setup(
        self,
        session_id: SessionId,
        submission: RegionSetupSubmission,
    ) -> GuidedIntakeState | None:
        fixture = await self._fixture_for_session(session_id)
        if fixture is None:
            return None

        fixture.region_setup = submission
        await self._persist_ready_brief(fixture)
        return self._state_for_fixture(fixture)

    async def _fixture_for_session(
        self,
        session_id: SessionId,
    ) -> FixtureGuidedSession | None:
        fixture = _fixture_sessions.get(session_id)
        if fixture is not None:
            return fixture

        session = await self._sessions.get(session_id)
        if session is None:
            return None

        region_setup: RegionSetupSubmission | None = None
        if session.current_brief.region is not None:
            region_setup = RegionSetupSubmission(
                status=RegionSetupStatus.PROVIDED,
                region=session.current_brief.region.region,
            )

        fixture = FixtureGuidedSession(
            session_id=session_id,
            query=session.original_input.query,
            region_setup=region_setup,
            blocked_guardrail=_guardrail_for_query(session.original_input.query),
        )
        _fixture_sessions[session_id] = fixture
        return fixture

    def _state_for_fixture(self, fixture: FixtureGuidedSession) -> GuidedIntakeState:
        if fixture.blocked_guardrail is not None:
            return GuidedIntakeState(
                status=GuidedIntakeStatus.BLOCKED,
                guardrail=fixture.blocked_guardrail,
                region_setup=self._region_setup_state(fixture),
                progress=ProgressDisplayStatus(
                    kind=ProgressDisplayKind.BLOCKED,
                    message="This request is outside shopping help.",
                ),
            )

        question = self._current_question_for_fixture(fixture)
        if question is None:
            return self._ready_state_for_fixture(fixture)

        return GuidedIntakeState(
            status=GuidedIntakeStatus.COLLECTING,
            current_question=question,
            navigation=self._navigation_state(fixture),
            skippable_question=SkippableQuestionState(
                can_skip=question.question_id == OPTIONAL_CONTEXT_QUESTION_ID,
            ),
            analysis_start=AnalysisStartAvailability(
                enough_information=True,
                can_skip_all_and_start_analysis=True,
                message="We can start with what you have already shared.",
            ),
            region_setup=self._region_setup_state(fixture),
            progress=ProgressDisplayStatus(
                kind=ProgressDisplayKind.IDLE,
                message="Ready for your answer.",
            ),
        )

    def _ready_state_for_fixture(
        self,
        fixture: FixtureGuidedSession,
    ) -> GuidedIntakeState:
        return GuidedIntakeState(
            status=GuidedIntakeStatus.READY_FOR_ANALYSIS,
            navigation=self._navigation_state(fixture),
            analysis_start=AnalysisStartAvailability(
                enough_information=True,
                can_skip_all_and_start_analysis=False,
                message="We have enough to start checking options.",
            ),
            region_setup=self._region_setup_state(fixture),
            progress=ProgressDisplayStatus(
                kind=ProgressDisplayKind.CHECKING_OPTIONS,
                message="Ready to start checking options.",
            ),
            ready_brief=self._brief_for_fixture(fixture),
        )

    def _current_question_for_fixture(
        self,
        fixture: FixtureGuidedSession,
    ) -> CurrentGuidedQuestion | None:
        if fixture.blocked_guardrail is not None:
            return None
        if fixture.reanswer_question_id is not None:
            return _question_by_id(fixture.reanswer_question_id, fixture.query)
        if fixture.started_analysis:
            return None

        first_followup = _first_followup_question_id(fixture.query)
        if first_followup not in fixture.answers:
            return _question_by_id(first_followup, fixture.query)
        if (
            OPTIONAL_CONTEXT_QUESTION_ID not in fixture.answers
            and OPTIONAL_CONTEXT_QUESTION_ID not in fixture.skipped_question_ids
        ):
            return _optional_context_question()
        return None

    def _navigation_state(
        self,
        fixture: FixtureGuidedSession,
    ) -> PriorQuestionNavigationState:
        questions = tuple(
            ReanswerableQuestion(
                question_id=question_id,
                label=_reanswer_label(question_id),
            )
            for question_id in self._answered_question_ids(fixture)
        )
        return PriorQuestionNavigationState(
            can_go_back=bool(questions),
            current_reanswer_question_id=fixture.reanswer_question_id,
            reanswerable_questions=questions,
        )

    def _answered_question_ids(self, fixture: FixtureGuidedSession) -> tuple[str, ...]:
        ordered = (
            MONITOR_CONNECTION_QUESTION_ID,
            COMPARISON_PRIORITY_QUESTION_ID,
            OPTIONAL_CONTEXT_QUESTION_ID,
        )
        return tuple(
            question_id for question_id in ordered if question_id in fixture.answers
        )

    def _region_setup_state(
        self,
        fixture: FixtureGuidedSession,
    ) -> LocalRegionSetupState:
        if fixture.region_setup is None:
            return LocalRegionSetupState(
                status=RegionSetupStatus.NEEDS_ANSWER,
                prompt_text=(
                    "Where are you buying from? "
                    "It helps show options you can actually buy."
                ),
                resumes_pending_question=True,
            )
        if fixture.region_setup.status == RegionSetupStatus.PROVIDED:
            return LocalRegionSetupState(
                status=RegionSetupStatus.PROVIDED,
                region=fixture.region_setup.region,
                resumes_pending_question=True,
            )
        return LocalRegionSetupState(
            status=RegionSetupStatus.REFUSED,
            resumes_pending_question=True,
        )

    async def _capture_optional_context(
        self,
        fixture: FixtureGuidedSession,
        answer: GuidedAnswer,
    ) -> None:
        text = _answer_text(answer)
        if text is None or text in fixture.user_added_texts:
            return
        if not _mentions_considered_product(text):
            return

        await self._products.add_user_added_product(
            fixture.session_id,
            UserAddedProduct(input_text=text),
        )
        fixture.user_added_texts.add(text)

    async def _persist_ready_brief(self, fixture: FixtureGuidedSession) -> None:
        await self._sessions.update_current_brief(
            fixture.session_id,
            self._brief_for_fixture(fixture),
        )

    def _brief_for_fixture(self, fixture: FixtureGuidedSession) -> ShoppingBrief:
        query = _answer_text(fixture.answers.get(FIRST_QUESTION_ID)) or fixture.query
        answer_texts = tuple(
            text
            for text in (_answer_text(answer) for answer in fixture.answers.values())
            if text
        )
        constraints = tuple(
            PreferenceConstraint(
                text=text,
                mode=PreferenceMode.HARD,
            )
            for text in answer_texts
            if _looks_like_constraint(text)
        )
        preferences = tuple(
            PreferenceConstraint(
                text=text,
                mode=PreferenceMode.SOFT,
            )
            for text in answer_texts
            if not _looks_like_constraint(text)
        )

        return ShoppingBrief(
            original_query=query,
            region=_region_preference_from_setup(fixture.region_setup),
            budget=_budget_from_texts(answer_texts),
            constraints=constraints,
            preferences=preferences,
            **_category_fields(query),
        )

    def _is_ready_after_answer(
        self,
        fixture: FixtureGuidedSession,
        question_id: str,
        *,
        was_reanswering: bool,
    ) -> bool:
        if was_reanswering:
            return True
        return question_id == OPTIONAL_CONTEXT_QUESTION_ID


def _guide_not_collecting(session_id: SessionId) -> ApplicationError:
    return ApplicationError(
        "guided_intake_not_collecting",
        "This shopping question is not waiting for another answer.",
        status_code=409,
        details={"session_id": str(session_id)},
    )


def _question_by_id(question_id: str, query: str) -> CurrentGuidedQuestion:
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
    if question_id == OPTIONAL_CONTEXT_QUESTION_ID:
        return _optional_context_question()
    if question_id == FIRST_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=FIRST_QUESTION_ID,
            text="Send your question",
            purpose=GuidedQuestionPurpose.FIRST_QUESTION,
            capture_targets=(GuidedCaptureTarget.SHOPPING_QUESTION,),
        )
    raise ApplicationError(
        "guided_question_not_found",
        "Question not found.",
        status_code=404,
        details={"question_id": question_id},
    )


def _optional_context_question() -> CurrentGuidedQuestion:
    return CurrentGuidedQuestion(
        question_id=OPTIONAL_CONTEXT_QUESTION_ID,
        text=(
            "Anything we should keep in mind, like budget, must-haves, "
            "or products you are already considering?"
        ),
        purpose=GuidedQuestionPurpose.COMBINED_OPTIONAL,
        capture_targets=(
            GuidedCaptureTarget.BUDGET,
            GuidedCaptureTarget.CONSTRAINTS,
            GuidedCaptureTarget.CONSIDERED_PRODUCT_NAMES,
        ),
        combined_optional_prompt=CombinedOptionalQuestionPrompt(
            text=(
                "Share any budget, must-haves, "
                "or product names you already have in mind."
            ),
            capture_targets=(
                GuidedCaptureTarget.BUDGET,
                GuidedCaptureTarget.CONSTRAINTS,
                GuidedCaptureTarget.CONSIDERED_PRODUCT_NAMES,
            ),
        ),
    )


def _first_followup_question_id(query: str) -> str:
    normalized = query.lower()
    if "monitor" in normalized:
        return MONITOR_CONNECTION_QUESTION_ID
    if " between " in f" {normalized} " or " vs " in normalized:
        return COMPARISON_PRIORITY_QUESTION_ID
    return OPTIONAL_CONTEXT_QUESTION_ID


def _category_fields(query: str) -> dict[str, str]:
    normalized = query.lower()
    categories = {
        "laptop": "laptop",
        "phone": "smartphone",
        "iphone": "smartphone",
        "samsung": "smartphone",
        "camera": "camera",
        "desk": "desk",
        "monitor": "monitor",
        "headphone": "headphones",
        "earbud": "earbuds",
    }
    for keyword, category in categories.items():
        if keyword in normalized:
            return {
                "category": category,
                "category_source": FieldSource.INFERRED,
            }
    return {}


def _region_preference_from_setup(
    submission: RegionSetupSubmission | None,
) -> RegionPreference | None:
    if submission is None or submission.status != RegionSetupStatus.PROVIDED:
        return None
    region = submission.region or Region(country_code="US")
    return RegionPreference(
        region=region,
        source=FieldSource.USER_PROVIDED,
    )


def _guardrail_for_query(query: str) -> ShoppingGuardrailResult | None:
    normalized = query.lower()
    if any(term in normalized for term in ("homework", "write an essay", "poem")):
        return _blocked_guardrail(
            ShoppingGuardrailReason.OFF_TOPIC,
            "I can help with shopping decisions. Try asking what to buy or compare.",
        )
    if any(term in normalized for term in ("gun", "explosive", "weapon")):
        return _blocked_guardrail(
            ShoppingGuardrailReason.UNSAFE_PRODUCT,
            "I cannot help choose unsafe products. "
            "I can help with ordinary consumer purchases.",
        )
    if any(term in normalized for term in ("fake passport", "stolen", "illegal")):
        return _blocked_guardrail(
            ShoppingGuardrailReason.ILLEGAL_PRODUCT,
            "I cannot help with illegal purchases. I can help with ordinary consumer products.",
        )
    return None


def _blocked_guardrail(
    reason: ShoppingGuardrailReason,
    message: str,
) -> ShoppingGuardrailResult:
    return ShoppingGuardrailResult(
        decision=ShoppingGuardrailDecision.BLOCKED,
        reason=reason,
        message=message,
    )


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


def _budget_from_texts(texts: tuple[str, ...]) -> BudgetConstraint | None:
    for text in texts:
        match = re.search(
            r"(?:\$|usd\s*)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            text,
            re.I,
        )
        if match is None:
            continue
        amount = Decimal(match.group(1).replace(",", ""))
        return BudgetConstraint(
            amount=Money(amount=amount, currency="USD"),
            mode=BudgetMode.PREFERRED,
        )
    return None


def _looks_like_constraint(text: str) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in ("must", "need", "needs", "cannot"))


def _mentions_considered_product(text: str) -> bool:
    normalized = text.lower()
    return any(
        term in normalized
        for term in (
            "considering",
            "looking at",
            "between",
            "already have in mind",
        )
    )


def _reanswer_label(question_id: str) -> str:
    labels = {
        MONITOR_CONNECTION_QUESTION_ID: "Monitor setup",
        COMPARISON_PRIORITY_QUESTION_ID: "Comparison priority",
        OPTIONAL_CONTEXT_QUESTION_ID: "Budget and must-haves",
    }
    return labels.get(question_id, "Earlier answer")
