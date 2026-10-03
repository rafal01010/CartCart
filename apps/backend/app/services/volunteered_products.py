"""Conservative, deterministic capture of shopper-volunteered candidate hints."""

import re
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from app.services.product_deduplication import canonical_listing_url


_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_HTTP_URL = TypeAdapter(AnyHttpUrl)
_NAME_PATTERNS = (
    re.compile(r"\b(?:compare|comparing)\s+(.+)", re.I),
    re.compile(r"\bbetween\s+(.+)", re.I),
    re.compile(r"\bwhich\s+(?:one\s+)?is\s+better\s*[:,]?\s*(.+)", re.I),
    re.compile(
        r"\b(?:considering|looking at|thinking about|interested in|maybe|such as|check|checking)\s+(.+)",
        re.I,
    ),
    re.compile(r"\b(?:should I buy|want to buy|what about)\s+(.+)", re.I),
)
_GENERIC = frozenset(
    {
        "a laptop",
        "a phone",
        "a monitor",
        "a camera",
        "a desk",
        "a tablet",
        "a tv",
        "a headset",
        "a product",
        "a new laptop",
        "a new phone",
        "laptop",
        "phone",
        "monitor",
        "camera",
        "desk",
        "tablet",
        "tv",
    }
)


def volunteered_urls(text: str) -> tuple[str, ...]:
    urls: dict[str, str] = {}
    for match in _URL.finditer(text):
        raw = match.group(0).rstrip(".,;:!?)]}")
        try:
            url = str(_HTTP_URL.validate_python(raw))
        except ValidationError:
            continue
        if not urlsplit(url).hostname:
            continue
        urls.setdefault(canonical_listing_url(url), url)
    return tuple(urls.values())


def text_without_urls(text: str) -> str:
    return " ".join(_URL.sub(" ", text).split())


def is_link_only(text: str) -> bool:
    return bool(volunteered_urls(text)) and not text_without_urls(text).strip(
        " .,;:!?()[]{}"
    )


def volunteered_names(text: str, *, considered_answer: bool = False) -> tuple[str, ...]:
    plain = text_without_urls(text).strip(" .,;:!?")
    if not plain:
        return ()
    if considered_answer:
        # This prompt explicitly asks for products, so a free-form description is a hint.
        if plain.casefold() in {"no", "none", "nothing", "not sure", "nope"} | _GENERIC:
            return ()
        if any(pattern.search(plain) for pattern in _NAME_PATTERNS):
            named = volunteered_names(plain)
            if named:
                return named
        first_sentence = re.split(r"[.!?]", plain, maxsplit=1)[0]
        parts = re.split(r"\s+(?:vs\.?|versus|and|or)\s+", first_sentence, flags=re.I)
        names = tuple(_clean_name(part) for part in parts)
        names = tuple(name for name in names if name)
        return names or (
            (plain[:1000],)
            if not volunteered_urls(text)
            and not re.search(
                r"\b(?:check|look at) this (?:link|listing)\b", plain, re.I
            )
            else ()
        )
    for pattern in _NAME_PATTERNS:
        match = pattern.search(plain)
        if match is None:
            continue
        candidate = re.split(
            r"[?.!;]|\b(?:for|because|with a budget|under \$)\b",
            match.group(1),
            maxsplit=1,
            flags=re.I,
        )[0]
        parts = re.split(r"\s+(?:vs\.?|versus|and|or)\s+", candidate, flags=re.I)
        names = tuple(_clean_name(part) for part in parts)
        return tuple(name for name in names if name)
    if (
        len(plain) <= 120
        and not re.search(r"[?.!;,$€£¥]", plain)
        and not re.search(
            r"\b(?:around|under|over|about|budget|maximum|minimum|up to)\b", plain, re.I
        )
        and not re.match(
            r"^(?:i|which|what|need|looking|want|help|should|can|is|are)\b",
            plain,
            re.I,
        )
    ):
        name = _clean_name(plain)
        if (
            name
            and len(name.split()) >= 2
            and (
                any(char.isdigit() for char in name)
                or re.search(r"\S+\s+[A-Z][A-Za-z]+\b", name)
            )
        ):
            return (name,)
    return ()


def _clean_name(value: str) -> str:
    name = re.sub(
        r"^(?:the|an?|my)\s+", "", value.strip(" .,;:!?\"'"), flags=re.I
    ).strip()
    if (
        name.casefold()
        in _GENERIC | {"also", "check", "this", "that", "listing", "link"}
        or len(name) < 3
    ):
        return ""
    # A named model usually contains a capitalized brand or an identifying digit.
    if not any(char.isdigit() for char in name) and not re.search(
        r"\b[A-Z][A-Za-z]+\b", name
    ):
        return ""
    return name[:1000]
