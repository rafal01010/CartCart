from dataclasses import dataclass
from typing import Any

import pytest
from agents import Agent, RunConfig

from app.agents.contracts import RedditCommunityIntelligenceAgentInput
from app.agents.live_reddit_community_intelligence import (
    InterpretedCommunitySignal,
    OpenAIAgentsSDKRedditCommunityModelRunner,
    RedditCommunityIntelligenceAgent,
    RedditCommunityModelOutput,
    SelectedDiscussion,
)
from app.agents.reddit_community_tools import RedditCommunityTools
from app.agents.workbench import (
    _WorkbenchRedditCommunityProvider,
    _scenario_reddit_headphones_recurring_complaint,
    _workbench_reddit_recurring_complaint_bundle,
)
from app.core.settings import Settings
from app.providers import FakeCommunityDiscussionProvider
from app.schemas.ids import new_id
from app.schemas.search_sources import (
    CommunityDiscussionEvidenceBundle,
    CommunitySupportingQuote,
    ExtractedPageContent,
    ExtractionStatus,
    ProviderMetadata,
    SourceSnapshot,
    SourceType,
)


def _input() -> RedditCommunityIntelligenceAgentInput:
    return RedditCommunityIntelligenceAgentInput.model_validate(
        _scenario_reddit_headphones_recurring_complaint().input
    )


@dataclass
class _SelectingRunner:
    fabricated_quote: bool = False
    wrong_source: bool = False
    one_thread: bool = False
    skip_read: bool = False
    calls: int = 0

    async def run(
        self,
        agent: Agent[Any],
        model_input: str,
        *,
        run_config: Any,
        max_turns: int,
        tools: RedditCommunityTools,
    ) -> Any:
        del model_input, run_config, max_turns
        self.calls += 1
        assert agent.name == "RedditCommunityIntelligenceAgent"
        assert {tool.name for tool in agent.tools} == {
            "search_community_discussions",
            "read_community_discussion",
        }
        await tools.search("fixture headphones recurring complaint reddit")
        discussions = tools.bundle.discussions[: (1 if self.one_thread else 2)]
        if not self.skip_read:
            for discussion in discussions:
                await tools.read(str(discussion.source_id))
        source_id = new_id() if self.wrong_source else discussions[0].source_id
        return type(
            "Result",
            (),
            {
                "final_output": RedditCommunityModelOutput(
                    selected_discussions=tuple(
                        SelectedDiscussion(
                            source_id=item.source_id,
                            relevance_reason="Relevant owner report",
                        )
                        for item in discussions
                    ),
                    signals=(
                        InterpretedCommunitySignal(
                            source_id=source_id,
                            claim="Some owners describe ear-pad splitting; the rate is unknown.",
                            supporting_quotes=tuple(
                                CommunitySupportingQuote(
                                    source_id=item.source_id,
                                    quote="invented defect"
                                    if self.fabricated_quote
                                    else "ear pads split after a few months",
                                )
                                for item in discussions
                            ),
                            recurring_signal=True,
                        ),
                    ),
                )
            },
        )()


@pytest.mark.asyncio
async def test_model_selects_cited_independent_threads_through_tools() -> None:
    runner = _SelectingRunner()
    agent = RedditCommunityIntelligenceAgent(
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        community_provider=_WorkbenchRedditCommunityProvider(),
        model_runner=runner,
    )
    output = await agent.run(_input())
    assert runner.calls == 1
    assert len(output.evidence) == 1
    claim = output.evidence[0]
    assert claim.recurring_signal is True
    assert claim.qualitative_signal is True
    assert len(claim.supporting_quotes) == 2
    assert {item.source_id for item in claim.supporting_quotes} == set(
        claim.context_source_ids
    )
    assert {item.thread_id for item in output.discussions} == {"hp123", "hp456"}
    assert {item.community_name for item in output.discussions} == {
        "headphones",
        "HeadphoneAdvice",
    }
    assert output.discussions[1].comment_id == "comment789"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["fabricated_quote", "wrong_source", "one_thread", "skip_read"]
)
async def test_ungrounded_model_output_becomes_gap(failure: str) -> None:
    agent = RedditCommunityIntelligenceAgent(
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        community_provider=_WorkbenchRedditCommunityProvider(),
        model_runner=_SelectingRunner(**{failure: True}),
    )
    output = await agent.run(_input())
    assert output.evidence == ()
    assert output.evidence_gaps
    assert agent.workbench_activity[-1]["status"] == "model_or_validation_failure_gap"


@pytest.mark.asyncio
async def test_tools_reject_unknown_sources_enforce_search_budget_and_filter_non_reddit() -> (
    None
):
    bundle = _workbench_reddit_recurring_complaint_bundle("headphones")
    bad = bundle.discussions[0].model_copy(
        update={"url": "https://example.com/r/headphones/comments/hp123/"}
    )
    ref = bundle.source_references[0].model_copy(update={"url": bad.url})
    unsafe_bundle = CommunityDiscussionEvidenceBundle(
        source_references=(ref, *bundle.source_references[1:]),
        discussions=(bad, *bundle.discussions[1:]),
    )
    tools = RedditCommunityTools(
        _input(), FakeCommunityDiscussionProvider(bundle=unsafe_bundle)
    )
    assert (await tools.read(str(new_id())))["status"] == "unknown_source"
    assert (await tools.search(""))["status"] == "invalid_query"
    assert (await tools.search("headphones owners"))["status"] == "succeeded"
    assert len(tools.bundle.discussions) == 1
    assert (await tools.read(str(bad.source_id)))["status"] == "unknown_source"
    assert (await tools.search("headphones pads"))["status"] == "succeeded"
    assert (await tools.search("third query"))["status"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_persisted_public_snapshot_is_readable_but_failed_extraction_is_not() -> (
    None
):
    source_id = new_id()
    snapshot = SourceSnapshot(
        source_id=source_id,
        url="https://www.reddit.com/r/headphones/comments/hp789/owner_notes/",
        source_type=SourceType.COMMUNITY_DISCUSSION,
        provider=ProviderMetadata(provider_name="persisted-fixture"),
        title="Owner notes",
        extraction_status=ExtractionStatus.SUCCEEDED,
        extracted_content=ExtractedPageContent(
            text="The ear pads wore down after regular use.",
            extractor="recorded-public-fixture",
            word_count=9,
        ),
    )
    input_data = _input().model_copy(update={"source_snapshots": (snapshot,)})
    tools = RedditCommunityTools(
        input_data, FakeCommunityDiscussionProvider(disabled=True)
    )
    assert (await tools.read(str(source_id)))["status"] == "ok"
    failed = snapshot.model_copy(update={"extraction_status": ExtractionStatus.FAILED})
    blocked = RedditCommunityTools(
        _input().model_copy(update={"source_snapshots": (failed,)}),
        FakeCommunityDiscussionProvider(disabled=True),
    )
    result = await blocked.read(str(source_id))
    assert result["status"] == "inaccessible"
    assert result["discussion"]["extracted_public_summary"] is None


@pytest.mark.asyncio
async def test_sdk_runner_invokes_agents_sdk_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int] = []

    async def fake_run(agent: Agent[Any], model_input: str, **kwargs: Any) -> object:
        assert agent.name == "RedditCommunityIntelligenceAgent"
        assert model_input == "fixture"
        seen.append(kwargs["max_turns"])
        return object()

    monkeypatch.setattr(
        "app.agents.context_management.Runner.run", fake_run
    )
    tools = RedditCommunityTools(_input(), _WorkbenchRedditCommunityProvider())
    await OpenAIAgentsSDKRedditCommunityModelRunner().run(
        Agent(name="RedditCommunityIntelligenceAgent", instructions="test"),
        "fixture",
        run_config=RunConfig(tracing_disabled=True),
        max_turns=4,
        tools=tools,
    )
    assert seen == [4]

@pytest.mark.asyncio
async def test_exact_late_public_quote_requires_an_observed_span():
    class LongDiscussionProvider(_WorkbenchRedditCommunityProvider):
        async def search_discussions(self, query, products=(), options=None):
            result = await super().search_discussions(query, products, options)
            return result.model_copy(update={"bundle": result.bundle.model_copy(update={
                "discussions": tuple(discussion.model_copy(update={
                    "extracted_public_summary": "Setup. " * 240 + discussion.extracted_public_summary,
                }) for discussion in result.bundle.discussions),
            })})

    class RecordingRunner(_SelectingRunner):
        async def run(self, *args, **kwargs):
            self.tools = kwargs["tools"]
            result = await super().run(*args, **kwargs)
            self.decision = result.final_output
            return result

    runner = RecordingRunner()
    supplied = _input()
    agent = RedditCommunityIntelligenceAgent(settings=Settings(_env_file=None),
        community_provider=LongDiscussionProvider(), model_runner=runner)
    result = await agent.run(supplied)
    assert result.evidence == ()
    assert result.evidence_gaps[0].reason == "Model interpretation failed; no community claim was accepted."
    from app.agents.live_reddit_community_intelligence import _validated_bundle
    with pytest.raises(ValueError, match="observed exact span"):
        _validated_bundle(supplied, runner.tools, runner.decision)
    assert all("ear pads split after a few months" in discussion.extracted_public_summary for discussion in result.discussions)
