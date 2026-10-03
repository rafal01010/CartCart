"""One synthetic case that checks harness wiring, not shopping quality."""

from pathlib import Path

from pydantic_evals import Dataset
from pydantic_evals.evaluators import EqualsExpected

from app.evals.fixtures import EvalSearchInput
from app.evals.schemas import EvalMetadata, LocalEvalCase
from app.schemas.search_sources import SearchQuery, SearchIntent
from app.providers.contracts import SearchProviderOptions

SMOKE_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "search_smoke.json"


def smoke_dataset() -> Dataset[EvalSearchInput, tuple[str, ...], EvalMetadata]:
    case = LocalEvalCase[EvalSearchInput, tuple[str, ...]](
        name="scaffolding/fixture-search",
        inputs=EvalSearchInput(
            query=SearchQuery(
                query="fixture shopping source",
                intent=SearchIntent.DISCOVERY,
                region_code="PH",
            ),
            options=SearchProviderOptions(region_code="PH", max_results=1),
        ),
        expected_output=("https://example.com/cartcart-eval-fixture",),
        metadata=EvalMetadata(
            description="Load a synthetic search fixture and preserve its URL.",
            tags=("scaffolding", "offline"),
        ),
    )
    return Dataset(
        name="cartcart-scaffolding",
        cases=[case.to_case()],
        evaluators=[EqualsExpected()],
    )
