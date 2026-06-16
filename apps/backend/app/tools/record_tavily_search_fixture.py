from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

from app.core.settings import BACKEND_ROOT, Settings
from app.providers.contracts import SearchProviderOptions
from app.providers.fixtures import write_provider_fixture
from app.providers.tavily import TavilySearchProvider
from app.schemas.search_sources import SearchIntent, SearchQuery


FIXTURE_ROOT = BACKEND_ROOT / "tests" / "fixtures" / "providers"


async def record_tavily_search_fixture(
    *,
    output_path: Path,
    query_text: str,
    region_code: str,
    max_results: int,
) -> None:
    if os.getenv("CARTCART_RECORD_PROVIDER_FIXTURES") != "1":
        raise RuntimeError(
            "Set CARTCART_RECORD_PROVIDER_FIXTURES=1 to allow a live recording."
        )

    resolved_output = output_path.expanduser().resolve()
    if not resolved_output.is_relative_to(FIXTURE_ROOT.resolve()):
        raise RuntimeError(f"Fixture output must be under {FIXTURE_ROOT}.")

    settings = Settings()
    if settings.tavily_api_key is None:
        raise RuntimeError("CARTCART_TAVILY_API_KEY is not configured.")
    api_key = settings.tavily_api_key.get_secret_value()
    captured: dict[str, Any] = {}

    async def capture_response(response: httpx.Response) -> None:
        await response.aread()
        captured["request_url"] = str(response.request.url)
        captured["request_json"] = json.loads(response.request.content)
        captured["response_status_code"] = response.status_code
        captured["response_json"] = response.json()

    async with httpx.AsyncClient(
        event_hooks={"response": [capture_response]},
    ) as client:
        provider = TavilySearchProvider(
            api_key=api_key,
            timeout_seconds=settings.provider_timeout_seconds,
            client=client,
        )
        await provider.search(
            SearchQuery(
                query=query_text,
                intent=SearchIntent.DISCOVERY,
                region_code=region_code,
            ),
            SearchProviderOptions(max_results=max_results),
        )

    request_json = captured.get("request_json")
    response_json = captured.get("response_json")
    if not isinstance(request_json, dict) or not isinstance(response_json, dict):
        raise RuntimeError("Tavily response capture did not produce JSON objects.")

    write_provider_fixture(
        resolved_output,
        provider_name="tavily",
        request_method="POST",
        request_url=str(captured["request_url"]),
        request_json=request_json,
        response_status_code=int(captured["response_status_code"]),
        response_json=response_json,
        secret_values=(api_key,),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record a sanitized Tavily search response for deterministic tests."
    )
    parser.add_argument("output_path", type=Path)
    parser.add_argument("query")
    parser.add_argument("--region", default="US")
    parser.add_argument("--max-results", type=int, default=5, choices=range(1, 21))
    return parser


def main() -> int:
    args = _parser().parse_args()
    asyncio.run(
        record_tavily_search_fixture(
            output_path=args.output_path,
            query_text=args.query,
            region_code=args.region,
            max_results=args.max_results,
        )
    )
    print(f"Wrote sanitized Tavily fixture to {args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
