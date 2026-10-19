from dataclasses import dataclass, field, replace
from decimal import Decimal
import re
from typing import TypedDict

from pydantic import AnyHttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ShoppingScopeGuardrail, ShoppingScopeGuardrailInput
from app.core.errors import ApplicationError
from app.db.repositories.products import ProductRepository
from app.db.repositories.runs import RunRepository
from app.db.repositories.sessions import SessionRepository
from app.schemas.guided_intake import (
    AnalysisStartAvailability,
    ChoiceGuidedAnswer,
    ChoiceWithTextGuidedAnswer,
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
    ShoppingGuardrailResult,
    ShoppingGuardrailDecision,
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
from app.services.product_deduplication import canonical_listing_url
from app.services.shopping_intent import has_unconstrained_budget
from app.services.volunteered_products import (
    is_link_only,
    text_without_urls,
    volunteered_names,
    volunteered_urls,
)


FIRST_QUESTION_ID = "first-question"
SHOPPING_GOAL_QUESTION_ID = "shopping-goal"
MONITOR_CONNECTION_QUESTION_ID = "monitor-connection"
COMPARISON_PRIORITY_QUESTION_ID = "comparison-priority"
BUDGET_QUESTION_ID = "budget"
CONSIDERED_PRODUCTS_QUESTION_ID = "considered-products"


class CategoryFields(TypedDict, total=False):
    category: str
    category_source: FieldSource


@dataclass(frozen=True)
class GuidedGuardrailAssessment:
    input_data: ShoppingScopeGuardrailInput
    result: ShoppingGuardrailResult


@dataclass
class FixtureGuidedSession:
    session_id: SessionId
    query: str
    region_setup: RegionSetupSubmission | None = None
    answers: dict[str, GuidedAnswer] = field(default_factory=dict)
    skipped_question_ids: set[str] = field(default_factory=set)
    reanswer_question_id: str | None = None
    ready_for_analysis: bool = False
    analysis_started_brief: ShoppingBrief | None = None
    guardrail_assessment: GuidedGuardrailAssessment | None = None

    @property
    def blocked_guardrail(self) -> ShoppingGuardrailResult | None:
        assessment = self.guardrail_assessment
        if (
            assessment is not None
            and assessment.result.decision == ShoppingGuardrailDecision.BLOCKED
        ):
            return assessment.result
        return None


_fixture_sessions: dict[SessionId, FixtureGuidedSession] = {}


def _guardrail_input(
    fixture: FixtureGuidedSession,
    *,
    user_input: str | None = None,
) -> ShoppingScopeGuardrailInput:
    return ShoppingScopeGuardrailInput(
        user_input=user_input or _shopping_goal(fixture),
        prior_answers=tuple(
            GuidedAnswerSubmission(question_id=question_id, answer=answer)
            for question_id, answer in fixture.answers.items()
        ),
    )


def guided_guardrail_input(
    session_id: SessionId,
    fallback_query: str,
) -> ShoppingScopeGuardrailInput:
    fixture = _fixture_sessions.get(session_id)
    if fixture is None:
        return ShoppingScopeGuardrailInput(user_input=fallback_query)
    unresolved_link = (
        is_link_only(fixture.query)
        and SHOPPING_GOAL_QUESTION_ID not in fixture.answers
    )
    return _guardrail_input(
        fixture, user_input=fallback_query if unresolved_link else None
    )


class GuidedIntakeService:
    def __init__(
        self,
        db_session: AsyncSession,
        *,
        guardrail: ShoppingScopeGuardrail | None = None,
    ) -> None:
        self._sessions = SessionRepository(db_session)
        self._products = ProductRepository(db_session)
        self._runs = RunRepository(db_session)
        self._guardrail = guardrail

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
        )
        await self._check_effective_request(fixture)
        await self._sync_volunteered_products(fixture)
        _fixture_sessions[session.session_id] = fixture
        return GuidedSessionResponse(
            session_id=session.session_id,
            guide=self._state_for_fixture(fixture),
        )

    async def load_state(self, session_id: SessionId) -> GuidedIntakeState | None:
        fixture = await self._fixture_for_session(session_id, require_editable=False)
        if fixture is None:
            return None
        if fixture.analysis_started_brief is not None:
            return self._state_for_fixture(fixture)
        await self._check_effective_request(fixture)
        _fixture_sessions[session_id] = fixture
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

        await self._check_effective_request(fixture)
        if fixture.blocked_guardrail is not None:
            _fixture_sessions[session_id] = fixture
            return self._state_for_fixture(fixture)

        await self._sync_volunteered_products(fixture)
        if submission.question_id in {
            SHOPPING_GOAL_QUESTION_ID,
            BUDGET_QUESTION_ID,
            CONSIDERED_PRODUCTS_QUESTION_ID,
        }:
            await self._persist_ready_brief(fixture)

        _fixture_sessions[session_id] = fixture

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
        if question.question_id not in {
            BUDGET_QUESTION_ID,
            CONSIDERED_PRODUCTS_QUESTION_ID,
        }:
            raise ApplicationError(
                "guided_question_not_skippable",
                "This question needs an answer before we continue.",
                status_code=409,
                details={"question_id": question.question_id},
            )

        fixture.skipped_question_ids.add(question.question_id)
        fixture.answers.pop(question.question_id, None)
        fixture.reanswer_question_id = None
        await self._check_effective_request(fixture)
        if fixture.blocked_guardrail is not None:
            _fixture_sessions[session_id] = fixture
            return self._state_for_fixture(fixture)
        if question.question_id == CONSIDERED_PRODUCTS_QUESTION_ID:
            await self._sync_volunteered_products(fixture)
            await self._persist_ready_brief(fixture)
            _fixture_sessions[session_id] = fixture
            return self._ready_state_for_fixture(fixture)
        _fixture_sessions[session_id] = fixture
        return self._state_for_fixture(fixture)

    async def skip_all_and_start_analysis(
        self,
        session_id: SessionId,
    ) -> GuidedIntakeState | None:
        fixture = await self._fixture_for_session(session_id)
        if fixture is None:
            return None
        await self._check_effective_request(fixture)
        if fixture.blocked_guardrail is not None:
            _fixture_sessions[session_id] = fixture
            return self._state_for_fixture(fixture)
        if (
            is_link_only(fixture.query)
            and SHOPPING_GOAL_QUESTION_ID not in fixture.answers
        ):
            raise _guide_not_collecting(session_id)

        fixture.ready_for_analysis = True
        await self._persist_ready_brief(fixture)
        _fixture_sessions[session_id] = fixture
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
        await self._check_effective_request(fixture)
        _fixture_sessions[session_id] = fixture
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
        await self._check_effective_request(fixture)
        await self._persist_ready_brief(fixture)
        _fixture_sessions[session_id] = fixture
        return self._state_for_fixture(fixture)

    async def _fixture_for_session(
        self,
        session_id: SessionId,
        *,
        require_editable: bool = True,
    ) -> FixtureGuidedSession | None:
        session = await self._sessions.get(session_id)
        if session is None:
            return None
        if await self._runs.has_for_session(session_id):
            if require_editable:
                raise _guide_not_collecting(session_id)
            return FixtureGuidedSession(
                session_id=session_id,
                query=session.original_input.query,
                analysis_started_brief=session.current_brief,
            )

        fixture = _fixture_sessions.get(session_id)
        if fixture is not None:
            return replace(
                fixture,
                answers=dict(fixture.answers),
                skipped_question_ids=set(fixture.skipped_question_ids),
            )

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
        )
        return fixture

    async def _check_effective_request(self, fixture: FixtureGuidedSession) -> None:
        if self._guardrail is None:
            return
        if (
            is_link_only(fixture.query)
            and SHOPPING_GOAL_QUESTION_ID not in fixture.answers
        ):
            return
        input_data = _guardrail_input(fixture)
        if (
            fixture.guardrail_assessment is not None
            and fixture.guardrail_assessment.input_data == input_data
        ):
            return
        result = await self._guardrail.run(input_data)
        if await self._runs.has_for_session(fixture.session_id):
            raise _guide_not_collecting(fixture.session_id)
        fixture.guardrail_assessment = GuidedGuardrailAssessment(input_data, result)

    def _state_for_fixture(self, fixture: FixtureGuidedSession) -> GuidedIntakeState:
        if fixture.analysis_started_brief is not None:
            return GuidedIntakeState(
                status=GuidedIntakeStatus.ANALYSIS_STARTED,
                region_setup=LocalRegionSetupState(
                    status=RegionSetupStatus.NOT_NEEDED,
                    can_refuse=False,
                ),
                ready_brief=fixture.analysis_started_brief,
            )
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
                can_skip=question.question_id
                in {BUDGET_QUESTION_ID, CONSIDERED_PRODUCTS_QUESTION_ID},
            ),
            analysis_start=AnalysisStartAvailability(
                enough_information=question.question_id != SHOPPING_GOAL_QUESTION_ID,
                can_skip_all_and_start_analysis=question.question_id
                != SHOPPING_GOAL_QUESTION_ID,
                message=(
                    "Tell us what you want to decide first."
                    if question.question_id == SHOPPING_GOAL_QUESTION_ID
                    else "We can start with what you have already shared."
                ),
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
        if fixture.blocked_guardrail is not None:
            return self._state_for_fixture(fixture)
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
        if fixture.ready_for_analysis:
            return None

        if (
            is_link_only(fixture.query)
            and SHOPPING_GOAL_QUESTION_ID not in fixture.answers
        ):
            return _question_by_id(SHOPPING_GOAL_QUESTION_ID, fixture.query)

        first_followup = _first_followup_question_id(_shopping_goal(fixture))
        budget_answered = (
            _budget_from_texts(
                (
                    _shopping_goal(fixture),
                    *(
                        _answer_text(answer) or ""
                        for answer in fixture.answers.values()
                    ),
                ),
                currency=(fixture.region_setup.region.currency if fixture.region_setup and fixture.region_setup.region else None),
            )
            is not None
            or has_unconstrained_budget(_shopping_goal(fixture))
            or any(
                has_unconstrained_budget(_answer_text(answer) or "")
                for answer in fixture.answers.values()
            )
        )
        if (
            first_followup not in fixture.answers
            and first_followup not in fixture.skipped_question_ids
            and not (first_followup == BUDGET_QUESTION_ID and budget_answered)
        ):
            return _question_by_id(first_followup, fixture.query)
        if (
            BUDGET_QUESTION_ID not in fixture.answers
            and BUDGET_QUESTION_ID not in fixture.skipped_question_ids
            and not budget_answered
        ):
            return _question_by_id(BUDGET_QUESTION_ID, fixture.query)
        if (
            CONSIDERED_PRODUCTS_QUESTION_ID not in fixture.answers
            and CONSIDERED_PRODUCTS_QUESTION_ID not in fixture.skipped_question_ids
        ):
            return _question_by_id(CONSIDERED_PRODUCTS_QUESTION_ID, fixture.query)
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
            SHOPPING_GOAL_QUESTION_ID,
            MONITOR_CONNECTION_QUESTION_ID,
            COMPARISON_PRIORITY_QUESTION_ID,
            BUDGET_QUESTION_ID,
            CONSIDERED_PRODUCTS_QUESTION_ID,
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

    async def _sync_volunteered_products(self, fixture: FixtureGuidedSession) -> None:
        if fixture.blocked_guardrail is not None:
            return
        desired: dict[tuple[str, str], set[str]] = {}
        values: dict[tuple[str, str], str] = {}
        inputs = [(FIRST_QUESTION_ID, fixture.query)] + [
            (question_id, _answer_text(answer) or "")
            for question_id, answer in fixture.answers.items()
        ]
        for question_id, text in inputs:
            for url in volunteered_urls(text):
                key = ("url", canonical_listing_url(url))
                desired.setdefault(key, set()).add(question_id)
                values.setdefault(key, url)
            for name in volunteered_names(
                text,
                considered_answer=question_id == CONSIDERED_PRODUCTS_QUESTION_ID,
                initial_question=question_id == FIRST_QUESTION_ID,
            ):
                key = ("name", name.casefold())
                desired.setdefault(key, set()).add(question_id)
                values.setdefault(key, name)

        existing = await self._products.list_user_added_products(fixture.session_id)
        auto = {
            (
                ("url", canonical_listing_url(str(item.url)))
                if item.url is not None
                else ("name", (item.input_text or "").casefold())
            ): item
            for item in existing
            if item.intake_source_question_ids
        }
        for key, item in auto.items():
            if key not in desired:
                await self._products.delete_user_added_product(
                    fixture.session_id, item.candidate_id
                )
            else:
                source_question_ids = tuple(sorted(desired.pop(key)))
                if item.intake_source_question_ids != source_question_ids:
                    await self._products.replace_user_added_product(
                        fixture.session_id,
                        item.model_copy(
                            update={"intake_source_question_ids": source_question_ids}
                        ),
                    )
        for (kind, value), sources in desired.items():
            key = (kind, value)
            await self._products.add_user_added_product(
                fixture.session_id,
                UserAddedProduct(
                    url=AnyHttpUrl(values[key]) if kind == "url" else None,
                    input_text=values[key] if kind == "name" else None,
                    intake_source_question_ids=tuple(sorted(sources)),
                ),
            )

    async def _persist_ready_brief(self, fixture: FixtureGuidedSession) -> None:
        if fixture.blocked_guardrail is not None:
            return
        await self._sessions.update_current_brief(
            fixture.session_id,
            self._brief_for_fixture(fixture),
        )

    def _brief_for_fixture(self, fixture: FixtureGuidedSession) -> ShoppingBrief:
        query = _shopping_goal(fixture)
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
        if any(has_unconstrained_budget(text) for text in (query, *answer_texts)):
            preferences = (
                *preferences,
                PreferenceConstraint(
                    text="Budget is not a constraint.",
                    mode=PreferenceMode.SOFT,
                ),
            )

        return ShoppingBrief(
            original_query=query,
            region=_region_preference_from_setup(fixture.region_setup),
            budget=_budget_from_texts((query, *answer_texts), currency=(fixture.region_setup.region.currency if fixture.region_setup and fixture.region_setup.region else None)),
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
        return question_id == CONSIDERED_PRODUCTS_QUESTION_ID


def _guide_not_collecting(session_id: SessionId) -> ApplicationError:
    return ApplicationError(
        "guided_intake_not_collecting",
        "This shopping question is not waiting for another answer.",
        status_code=409,
        details={"session_id": str(session_id)},
    )


def _question_by_id(question_id: str, query: str) -> CurrentGuidedQuestion:
    if question_id == SHOPPING_GOAL_QUESTION_ID:
        return CurrentGuidedQuestion(
            question_id=SHOPPING_GOAL_QUESTION_ID,
            text="What would you like help deciding about this item?",
            purpose=GuidedQuestionPurpose.CLARIFICATION,
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


def _first_followup_question_id(query: str) -> str:
    normalized = query.lower()
    if "monitor" in normalized:
        return MONITOR_CONNECTION_QUESTION_ID
    if " between " in f" {normalized} " or " vs " in normalized:
        return COMPARISON_PRIORITY_QUESTION_ID
    return BUDGET_QUESTION_ID


def _shopping_goal(fixture: FixtureGuidedSession) -> str:
    return (
        _answer_text(fixture.answers.get(SHOPPING_GOAL_QUESTION_ID))
        or text_without_urls(fixture.query)
        or fixture.query
    )


def _category_fields(query: str) -> CategoryFields:
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
    for keyword in sorted(categories, key=len, reverse=True):
        category = categories[keyword]
        if re.search(rf"\b{re.escape(keyword)}s?\b", normalized):
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


def _budget_from_texts(texts: tuple[str, ...], *, currency: str | None = None) -> BudgetConstraint | None:
    codes = "|".join(re.escape(code) for code in sorted({"USD", *([currency] if currency else [])}))
    for text in texts:
        match = re.search(
            rf"(?:\$|\b(?P<currency>{codes})\s*)\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]{{1,2}})?)",
            text,
            re.I,
        )
        if match is None:
            continue
        amount = Decimal(match.group("amount").replace(",", ""))
        return BudgetConstraint(
            amount=Money(amount=amount, currency=match.group("currency") or "USD"),
            mode=BudgetMode.PREFERRED,
        )
    return None


def _looks_like_constraint(text: str) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in ("must", "need", "needs", "cannot"))


def _reanswer_label(question_id: str) -> str:
    labels = {
        SHOPPING_GOAL_QUESTION_ID: "Shopping goal",
        MONITOR_CONNECTION_QUESTION_ID: "Monitor setup",
        COMPARISON_PRIORITY_QUESTION_ID: "Comparison priority",
        BUDGET_QUESTION_ID: "Budget",
        CONSIDERED_PRODUCTS_QUESTION_ID: "Products to check",
    }
    return labels.get(question_id, "Earlier answer")
