"""Strict recorded search responses with no runtime/provider selection."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, model_validator

from app.providers.contracts import SearchProviderOptions
from app.schemas.base import CartCartBaseModel, VersionedSchema
from app.schemas.search_sources import SearchQuery, SearchResult


class EvalSearchInput(CartCartBaseModel):
    query: SearchQuery
    options: SearchProviderOptions = Field(default_factory=SearchProviderOptions)


class SearchFixture(VersionedSchema):
    request: EvalSearchInput
    results: tuple[SearchResult, ...]

    @model_validator(mode="after")
    def matching_queries(self) -> "SearchFixture":
        if any(result.query != self.request.query for result in self.results):
            raise ValueError("Fixture results must reference the recorded query.")
        return self


@dataclass(frozen=True)
class EvalFixtureSearchProvider:
    """Implements SearchProvider; unmatched requests fail rather than go online."""

    fixture: SearchFixture

    @classmethod
    def from_file(cls, path: Path) -> "EvalFixtureSearchProvider":
        return cls(SearchFixture.model_validate_json(path.read_text(encoding="utf-8")))

    async def search(
        self,
        query: SearchQuery,
        options: SearchProviderOptions | None = None,
    ) -> tuple[SearchResult, ...]:
        request = EvalSearchInput(
            query=query, options=options or SearchProviderOptions()
        )
        if request != self.fixture.request:
            raise ValueError("No eval search fixture matches this query and options.")
        return tuple(result.model_copy(deep=True) for result in self.fixture.results)
