# Provider fixtures

Provider tests replay versioned JSON cassettes from this directory without
network access. Each cassette contains only the expected HTTP method, URL,
query parameters or sanitized JSON request, status code, and sanitized JSON
response. A provider may replay multiple cassettes when one logical operation
requires more than one HTTP request.

See `docs/PROVIDERS.md` for the complete provider setup, replay, compliance, and
raw-artifact storage policy.

Recording rules:

- Use synthetic, non-personal search queries suitable for a committed test.
- Never add headers, cookies, API keys, access tokens, or other credentials.
- The recorder removes secret-like fields, generated answers, images, and raw
  page content. It limits lists to 20 items and strings to 1,000 characters.
- Inspect the complete fixture diff before committing it. Automated scrubbing
  does not replace review for personal, licensed, or otherwise sensitive text.
- Keep only fields needed to exercise the provider contract.

The YouTube metadata fixtures are synthetic GET responses for `search.list`
and `videos.list`. API keys are sent by the adapter in the `X-Goog-Api-Key`
header and are never stored in fixture URLs or payloads. These fixtures contain
metadata only and do not imply that transcripts were checked or available.

`youtube_transcript_en.vtt` is a short synthetic WebVTT caption fixture. It
contains rolling-caption overlap, inline timing markup, and HTML entities so
the deterministic parser can be exercised without invoking `yt-dlp` or making
a YouTube request. It is not a transcript copied from a real video.

The Reddit community fixture replays a domain-scoped Tavily search response.
It contains synthetic public thread/comment URLs and search excerpts only. It
does not represent a direct Reddit API call or a fetched Reddit page, so missing
recency, engagement, and full-content extraction remain explicit evidence gaps.

The Amazon fixtures replay SerpApi's documented Amazon Search and Amazon Product
API shapes using a synthetic product. Replay covers conservative product
matching, ASIN and marketplace identity, seller/ship-from context, regional
delivery text, product-page facts, ratings/review summaries, variant ambiguity,
and neutral Amazon product URLs. SerpApi keys and Amazon affiliate parameters
are never retained in fixture requests or normalized evidence links.

The IKEA fixtures replay regional, domain-scoped Tavily searches against
official IKEA country paths. They cover an available product with local price
and delivery/store context and an unavailable product with an explicit stock
gap. Unsupported-region coverage does not make a search request. Search
metadata is not treated as proof of global shipping or availability.

Tavily recording is an explicit live operation. From `apps/backend`, run:

```sh
CARTCART_RECORD_PROVIDER_FIXTURES=1 uv run python \
  -m app.tools.record_tavily_search_fixture \
  tests/fixtures/providers/tavily_search.json \
  "best monitor reviews" \
  --region PH \
  --max-results 5
```

The command reads `CARTCART_TAVILY_API_KEY` from the shell or the ignored
`apps/backend/.env` file. Do not run it as part of routine tests or section
gates because it makes a live provider call and spends quota.
