"""Offline context inventory. No credentials, network, raw inputs, or source text in reports."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from agents import Agent, RunConfig, FunctionTool, Handoff
from agents.agent_output import AgentOutputSchema, AgentOutputSchemaBase
from sqlalchemy.ext.asyncio import create_async_engine
from pydantic import SecretStr
from app.core.settings import EnvironmentMode

from app.agents.catalog import DEFAULT_AGENT_CATALOG
from app.agents.context_metrics import input_breakdown, measure
from app.agents.source_spans import source_span
from app.agents.context_management import compact_json, prepare_history
from app.agents.contracts import (
    ExtractionAgentInput,
    GeneralShoppingAgentInput,
    VerificationAgentInput,
)
from app.agents.extraction_tools import SnapshotInterpretationTools
from app.agents.live_extraction import LiveExtractionAgent
from app.agents.live_general_shopping import LiveGeneralShoppingAgent
from app.agents.live_source_intelligence_manager import (
    SourceIntelligenceManagerAgent,
    SourceManagerInput,
)
from app.agents.research_tools import AgentResearchTools
from app.agents.workbench import _build_workbench_definitions
from app.core.settings import Settings
from app.db.base import Base
from app.db.repositories.runs import RunRepository
from app.db.repositories.search_sources import SearchSourceRepository
from app.db.repositories.sessions import SessionRepository
from app.db.session import create_session_factory
from app.providers.fakes import FakeExtractionProvider, FakeSearchProvider
from app.schemas.intake import CreateSessionRequest, ShoppingBrief
from app.schemas.search_sources import SourceIntelligenceCapability


def schema_payload(agent: Agent[Any]) -> dict[str, Any]:
    return {
        "output": (
            agent.output_type.json_schema()
            if isinstance(agent.output_type, AgentOutputSchemaBase)
            else AgentOutputSchema(agent.output_type).json_schema()
        )
        if agent.output_type is not None and agent.output_type is not str
        else {},
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.params_json_schema,
            }
            if isinstance(tool, FunctionTool)
            else {"type": tool.name}
            for tool in agent.tools
        ],
        "handoffs": [
            {
                "name": item.tool_name,
                "description": item.tool_description,
                "parameters": item.input_json_schema,
            }
            for item in agent.handoffs
            if isinstance(item, Handoff)
        ],
    }


class CaptureComplete(Exception):
    """Stop a capture-only wrapper before a model or provider can run."""


class CaptureRunner:
    def __init__(self, delegate: Any, records: list[dict[str, Any]]):
        self.delegate = delegate
        self.records = records

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: RunConfig,
        max_turns: int,
        **kwargs: Any,
    ) -> Any:
        payload = json.loads(model_input)
        self.records.append(
            {
                "agent": agent.name,
                "instructions": measure(str(agent.instructions)),
                "schemas": measure(schema_payload(agent)),
                "input": measure(model_input),
                "after_input": measure(compact_json(model_input)),
                "fields": {key: measure(value) for key, value in payload.items()},
                "actual_tokens": None,
                "history": "Single initial mock input; no measured SDK turns.",
                "receiving_handoff_contracts": [
                    {
                        "agent": target.name,
                        "instructions": measure(str(target.instructions)),
                        "schemas": measure(schema_payload(target)),
                        "actual_tokens": None,
                    }
                    for target in receiving_agents(agent)
                ],
            }
        )
        if self.delegate is None:
            raise CaptureComplete()
        return await self.delegate.run(
            agent, model_input, run_config=run_config, max_turns=max_turns, **kwargs
        )


def receiving_agents(agent: Agent[Any]) -> list[Agent[Any]]:
    """Inventory the constructed ownership graph without executing any handoff."""
    found = []
    seen = {id(agent)}
    pending = list(agent.handoffs)
    while pending:
        item = pending.pop()
        target = item if isinstance(item, Agent) else getattr(item, "_agent_ref", None)
        if target is not None and not isinstance(target, Agent):
            target = target()
        if target is None or id(target) in seen:
            continue
        seen.add(id(target))
        found.append(target)
        pending.extend(target.handoffs)
    return found


def history_audit(*, repeated: bool = False) -> dict[str, Any]:
    """Reproducible synthetic replay sizes, not reconstructed historical usage."""
    items: list[Any] = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "original_query": "Need a phone, budget is not a problem",
                    "region": "PH",
                    "budget_unconstrained": True,
                }
            ),
        }
    ]
    for index in range(8):
        source = "0" if repeated else str(index)
        quote = (
            f"Independent source {source}: exact warranty, variant and seller caveat."
        )
        items.extend(
            [
                {
                    "type": "function_call",
                    "call_id": f"r{index}",
                    "name": "fetch_source",
                    "arguments": json.dumps({"source_id": source}),
                },
                {
                    "type": "function_call_output",
                    "call_id": f"r{index}",
                    "output": json.dumps(
                        {
                            "source_id": source,
                            "text": "Navigation and unrelated prose. " * 350 + quote,
                            "status": "succeeded",
                        }
                    ),
                },
                {
                    "type": "function_call",
                    "call_id": f"q{index}",
                    "name": "record_source_quote",
                    "arguments": json.dumps({"source_id": source, "quote": quote}),
                },
                {
                    "type": "function_call_output",
                    "call_id": f"q{index}",
                    "output": json.dumps(
                        {"source_id": source, "quote": quote, "status": "succeeded"}
                    ),
                },
            ]
        )
    prepared = prepare_history(items)
    return {
        "mode": "synthetic history; no model execution",
        "before": measure(items),
        "after": measure(prepared),
        "before_components": input_breakdown(items),
        "after_components": input_breakdown(prepared),
        "actual_tokens": None,
    }


def retrieval_audit() -> dict[str, Any]:
    pages = [
        "Navigation and unrelated prose. " * 350
        + f"Independent source {index}: exact warranty, variant and seller caveat."
        for index in range(8)
    ]
    views = [
        source_span(page, focus="Independent source", limit=1600).text for page in pages
    ]
    return {
        "mode": "synthetic bounded retrieval; canonical pages retained",
        "canonical_pages": measure(pages),
        "bounded_views": measure(views),
        "actual_tokens": None,
    }


async def audit() -> dict[str, Any]:
    settings = Settings(
        _env_file=None,
        environment=EnvironmentMode.TEST,
        live_agents_enabled=False,
        live_providers_enabled=False,
        openai_api_key=None,
        openai_agent_tracing_enabled=False,
    )  # type: ignore[call-arg]
    records: list[dict[str, Any]] = []
    inventory = []
    definitions = _build_workbench_definitions(DEFAULT_AGENT_CATALOG)
    for name, definition in definitions.items():
        scenario = definition.scenarios[0]
        supplied = definition.input_model.model_validate(scenario.input)
        inventory.append(
            {
                "agent": name,
                "contract": measure(supplied.model_dump_json()),
                "model_boundary": definition.live_agent_factory is not None,
            }
        )
        agent_factory = definition.mock_agent_factory or definition.live_agent_factory
        if name == "ExtractionAgent":
            continue  # Persisted page reads are exercised by the separate SDK replay audit.
        if agent_factory is None:
            continue
        agent = agent_factory(settings)
        if not hasattr(agent, "model_runner"):
            continue
        delegate = agent.model_runner if definition.mock_agent_factory else None
        agent.model_runner = CaptureRunner(delegate, records)
        try:
            await agent.run(supplied)
        except CaptureComplete:
            pass
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        from app.agents.live_verifier_critic import _build_verifier_critic_agent

        verifier_input = VerificationAgentInput.model_validate(
            definitions["VerifierCriticAgent"].scenarios[0].input
        )
        verifier_tools = SnapshotInterpretationTools(
            run_id=verifier_input.run_id,
            allowed_snapshot_ids=tuple(
                item.source_id for item in verifier_input.evidence
            ),
            session_factory=factory,
            agent_name="VerifierCriticAgent",
        )
        verifier_contract = _build_verifier_critic_agent(
            "offline", verifier_tools.sdk_tools()
        )
        for record in records:
            if record["agent"] == verifier_contract.name:
                record["schemas"] = measure(schema_payload(verifier_contract))
                record["support_capture"] = (
                    "Production bounded-read schema; fixture input without persisted support reload."
                )
        extraction = ExtractionAgentInput.model_validate(
            definitions["ExtractionAgent"].scenarios[0].input
        )
        owner = GeneralShoppingAgentInput.model_validate(
            definitions["GeneralShoppingAgent"].scenarios[2].input
        )
        async with factory() as session:
            for supplied in (extraction, owner):
                brief = getattr(
                    supplied,
                    "brief",
                    ShoppingBrief(original_query="Compare assigned snapshots"),
                )
                shopping_session = await SessionRepository(session).create(
                    original_input=CreateSessionRequest(query=brief.original_query),
                    current_brief=brief,
                )
                await RunRepository(session).create(
                    shopping_session.session_id, run_id=supplied.run_id
                )
            repo = SearchSourceRepository(session)
            for snapshot in extraction.workbench_snapshots:
                await repo.add_source_snapshot(extraction.run_id, snapshot)
            await session.commit()
        await LiveExtractionAgent(
            settings,
            lambda supplied: SnapshotInterpretationTools(
                run_id=supplied.run_id,
                allowed_snapshot_ids=supplied.snapshot_ids,
                session_factory=factory,
            ),
            model_runner=CaptureRunner(None, records),
        ).run(extraction)
        # Build the complete owner schemas with an intentionally fake credential.
        # CaptureComplete stops before SDK/provider execution; no .env is loaded.
        owner_settings = Settings(
            _env_file=None,
            environment=EnvironmentMode.TEST,
            live_agents_enabled=True,
            openai_api_key=SecretStr("offline-capture-only"),
            openai_model="gpt-6-sol",
            openai_agent_tracing_enabled=False,
        )  # type: ignore[call-arg]

        def research(name, run_id, region):
            return AgentResearchTools(
                agent_name=name,
                run_id=run_id,
                required_region_code=region,
                session_factory=factory,
                search_provider=FakeSearchProvider(results=()),
                extraction_provider=FakeExtractionProvider(),
            )

        await LiveGeneralShoppingAgent(
            owner_settings,
            session_factory=factory,
            regional_research_tools_factory=lambda run_id, region: research(
                "GeneralShoppingAgent", run_id, region
            ),
            technology_research_tools_factory=lambda run_id, region: research(
                "TechnologyDomainAnalystAgent", run_id, region
            ),
            model_runner=CaptureRunner(None, records),
        ).run(owner)
    finally:
        await engine.dispose()
    await SourceIntelligenceManagerAgent(
        settings, model_runner=CaptureRunner(None, records)
    ).run(
        SourceManagerInput(
            run_id=owner.run_id,
            brief=owner.brief,
            products=(),
            listings=(),
            source_snapshots=(),
            query_hints=(),
            region_code="PH",
            allowed_capabilities=tuple(SourceIntelligenceCapability),
        )
    )
    return {
        "mode": "offline",
        "estimator": "UTF-8 bytes / 3, rounded up; not a tokenizer",
        "historical_per_turn_tokens": None,
        "inventory": inventory,
        "calls": records,
        "history_audit": history_audit(),
        "duplicate_history_audit": history_audit(repeated=True),
        "retrieval_audit": retrieval_audit(),
        "boundary_reuse": {
            "recovery": "Same owner gateway and shared budget; no separately measured historical recovery turn.",
            "refinement": "Typed current brief/evidence use the same stage contracts; no historical per-turn input saved.",
            "dedupe": "Deterministic service, no model context.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(asyncio.run(audit()), indent=2) + "\n"
    if args.output:
        repo = Path(__file__).resolve().parents[4]
        target = args.output.resolve()
        if not target.is_relative_to(repo / "data" / "artifacts"):
            parser.error("Reports must be under repository data/artifacts.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report)
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
