"""Scoped intake/planning cases and offline adapters for production contracts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator
from pydantic_evals import Case, Dataset

from app.agents.contracts import (
    IntakeAgent,
    IntakeAgentInput,
    QueryPlannerAgent,
    QueryPlannerAgentInput,
    ShoppingGuideAgent,
    ShoppingGuideAgentInput,
)
from app.agents.live_guide import LiveShoppingGuideAgent, MockShoppingGuideModelRunner
from app.agents.live_intake import LiveIntakeAgent, MockIntakeModelRunner
from app.agents.live_query_planner import (
    LiveQueryPlannerAgent,
    MockQueryPlannerModelRunner,
)
from app.core.settings import Settings
from app.evals.schemas import EvalMetadata, LocalEvalCase
from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.guided_intake import (
    ChoiceWithTextGuidedAnswer,
    GuidedIntakeState,
    NaturalLanguageGuidedAnswer,
)
from app.schemas.intake import BudgetConstraint, CreateSessionRequest, ShoppingBrief
from app.schemas.regions import RegionCode
from app.schemas.search_sources import SearchPlan
from app.services.volunteered_products import volunteered_names

INTAKE_PLANNING_PATH = Path(__file__).parent / "fixtures" / "intake_planning.json"
_RUN_ID = UUID("00000000-0000-4000-8000-000000000097")


class IntakePlanningInput(VersionedSchema):
    stage: Literal["guide", "intake", "planning"]
    # Guide snapshots replay shopper context, not recorded agent responses.
    guide_turns: tuple[ShoppingGuideAgentInput, ...] = ()
    request: CreateSessionRequest | None = None
    planning: QueryPlannerAgentInput | None = None

    @model_validator(mode="after")
    def exclusive_stage(self) -> "IntakePlanningInput":
        if (
            bool(self.guide_turns),
            self.request is not None,
            self.planning is not None,
        ) != {
            "guide": (True, False, False),
            "intake": (False, True, False),
            "planning": (False, False, True),
        }[self.stage]:
            raise ValueError("Provide inputs for exactly the selected stage.")
        return self


class FieldCriterion(CartCartBaseModel):
    field: str = Field(
        pattern=r"^(guide_states|brief|considered_products|search_plan)(\.(\w+|\*))*$"
    )
    operator: Literal["equals", "includes", "contains_text"] = "equals"
    value: JsonValue
    requirement: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_operand(self) -> "FieldCriterion":
        if self.operator == "contains_text" and (
            not isinstance(self.value, str) or not self.value.strip()
        ):
            raise ValueError("contains_text requires a nonempty string.")
        if self.operator == "includes" and (
            not isinstance(self.value, list) or not self.value
        ):
            raise ValueError("includes requires a nonempty list.")
        return self


class PlanCriteria(CartCartBaseModel):
    # Each group accepts equivalent words; every group must be represented.
    topic_terms: tuple[str, ...] = Field(min_length=1)
    context_terms: tuple[tuple[str, ...], ...] = ()
    considered_products: tuple[str, ...] = ()
    region_code: RegionCode | None
    budget: BudgetConstraint | None = None
    forbidden_terms: tuple[str, ...] = ()

    @model_validator(mode="after")
    def nonempty_terms(self) -> "PlanCriteria":
        groups = (self.topic_terms, *self.context_terms)
        if any(
            not group or any(not term.strip() for term in group) for group in groups
        ):
            raise ValueError("Search reasoning term groups cannot be empty.")
        return self


class IntakePlanningExpectation(CartCartBaseModel):
    fields: tuple[FieldCriterion, ...] = Field(min_length=1)
    plan: PlanCriteria | None = None

    @model_validator(mode="after")
    def unique_fields(self) -> "IntakePlanningExpectation":
        names = [(rule.field, rule.operator, str(rule.value)) for rule in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate field criteria.")
        return self


class IntakePlanningOutput(CartCartBaseModel):
    guide_states: tuple[GuidedIntakeState, ...] = ()
    brief: ShoppingBrief | None = None
    considered_products: tuple[str, ...] = ()
    search_plan: SearchPlan | None = None


# The framework uses one type for actual and expected output. Expectations remain
# a separate model and are never passed to the task or any evaluated agent.
IntakePlanningResult = IntakePlanningOutput | IntakePlanningExpectation


class IntakePlanningCorpus(VersionedSchema):
    provenance: Literal["synthetic"]
    cases: tuple[LocalEvalCase[IntakePlanningInput, IntakePlanningExpectation], ...] = (
        Field(min_length=1)
    )


def intake_planning_cases(
    path: Path = INTAKE_PLANNING_PATH,
) -> tuple[LocalEvalCase[IntakePlanningInput, IntakePlanningExpectation], ...]:
    corpus = IntakePlanningCorpus.model_validate_json(path.read_text(encoding="utf-8"))
    versions = [corpus.schema_version]
    for case in corpus.cases:
        versions.extend((case.schema_version, case.inputs.schema_version))
        versions.extend(turn.schema_version for turn in case.inputs.guide_turns)
        if case.inputs.planning is not None:
            versions.extend(
                (
                    case.inputs.planning.schema_version,
                    case.inputs.planning.brief.schema_version,
                )
            )
        if (case.inputs.stage == "planning") != (case.expected_output.plan is not None):
            raise ValueError(
                f"{case.name}: planning cases require search reasoning criteria."
            )
    if any(version != 1 for version in versions):
        raise ValueError("Unsupported intake/planning corpus version.")
    names = [case.name for case in corpus.cases]
    if len(names) != len(set(names)):
        raise ValueError("Intake/planning case names must be unique.")
    return corpus.cases


def intake_planning_dataset() -> Dataset[
    IntakePlanningInput, IntakePlanningResult, EvalMetadata
]:
    from app.evals.intake_planning_scoring import IntakePlanningEvaluator

    return Dataset(
        name="cartcart-intake-planning",
        cases=[
            Case[IntakePlanningInput, IntakePlanningResult, EvalMetadata](
                name=case.name,
                inputs=case.inputs,
                expected_output=case.expected_output,
                metadata=case.metadata,
            )
            for case in intake_planning_cases()
        ],
        evaluators=[IntakePlanningEvaluator()],
    )


def _considered_names(input_data: ShoppingGuideAgentInput) -> tuple[str, ...]:
    texts = [(input_data.user_input, False)]
    for submission in input_data.prior_answers:
        answer = submission.answer
        if isinstance(answer, NaturalLanguageGuidedAnswer | ChoiceWithTextGuidedAnswer):
            texts.append((answer.text, submission.question_id == "considered-products"))
    names = {}
    for text, considered in texts:
        for name in volunteered_names(text, considered_answer=considered):
            names.setdefault(name.casefold(), name)
    return tuple(names.values())


@dataclass
class IntakePlanningTask:
    """Injectable contracts; the CLI constructs only the explicit mock lane."""

    guide: ShoppingGuideAgent
    intake: IntakeAgent
    planner: QueryPlannerAgent

    async def __call__(self, inputs: IntakePlanningInput) -> IntakePlanningOutput:
        # Agents may mutate their input. Keep report inputs and later cases intact.
        inputs = inputs.model_copy(deep=True)
        if inputs.stage == "guide":
            states = tuple(
                [
                    GuidedIntakeState.model_validate(await self.guide.run(turn))
                    for turn in inputs.guide_turns
                ]
            )
            return IntakePlanningOutput(
                guide_states=states,
                brief=states[-1].ready_brief,
                considered_products=_considered_names(inputs.guide_turns[-1]),
            )
        if inputs.stage == "intake":
            assert inputs.request is not None
            return IntakePlanningOutput(
                brief=ShoppingBrief.model_validate(
                    await self.intake.run(
                        IntakeAgentInput(run_id=_RUN_ID, request=inputs.request)
                    )
                ),
                considered_products=volunteered_names(inputs.request.query),
            )
        assert inputs.planning is not None
        return IntakePlanningOutput(
            search_plan=SearchPlan.model_validate(
                await self.planner.run(inputs.planning)
            )
        )


def offline_intake_planning_task() -> IntakePlanningTask:
    # Explicit overrides ignore ambient live/model/profile selections. No .env,
    # SDK Runner, hosted tools, app startup, providers or exporters are invoked.
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        live_agents_enabled=False,
        openai_api_key=None,
        openai_model="eval-mock-model",
        openai_run_profiles={},
        openai_agent_overrides={},
        openai_agent_tracing_enabled=False,
    )
    intake = LiveIntakeAgent(settings=settings, model_runner=MockIntakeModelRunner())
    return IntakePlanningTask(
        guide=LiveShoppingGuideAgent(
            settings=settings,
            model_runner=MockShoppingGuideModelRunner(),
            intake_agent=intake,
        ),
        intake=intake,
        planner=LiveQueryPlannerAgent(
            settings=settings, model_runner=MockQueryPlannerModelRunner()
        ),
    )
