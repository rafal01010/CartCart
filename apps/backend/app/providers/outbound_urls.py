import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.providers.source_quality import normalize_source_url


_PRODUCT_QUERY_KEYS = frozenset(
    {"sku", "variant", "product_id", "productid", "pid", "item_id"}
)
_CREDENTIAL_QUERY_KEYS = frozenset(
    {
        "token",
        "access_token",
        "auth",
        "authorization",
        "api_key",
        "apikey",
        "password",
        "secret",
        "session",
        "sessionid",
    }
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9._~-]{1,200}\Z")


def neutral_outbound_url(url: str) -> str | None:
    """Return an approved destination, or withhold unsupported URL identity."""
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        normalized, _domain = normalize_source_url(url)
        normalized_parts = urlsplit(normalized)
    except ValueError:
        return None
    youtube_watch = (
        parsed.hostname.lower() in {"youtube.com", "www.youtube.com"}
        and parsed.path == "/watch"
    )
    query = []
    for key, value in parse_qsl(normalized_parts.query, keep_blank_values=True):
        if key.casefold() in _CREDENTIAL_QUERY_KEYS:
            continue
        if not (
            key.casefold() in _PRODUCT_QUERY_KEYS or youtube_watch and key == "v"
        ) or not _IDENTIFIER.fullmatch(value):
            return None
        query.append((key, value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
