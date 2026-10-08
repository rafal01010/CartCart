from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.agents.research_history import bounded_cautions, material_cautions
from app.schemas.ids import SourceId
from app.schemas.intake import ShoppingBrief
from app.schemas.search_sources import SearchIntent, SearchResult, SourceType


_STOP_WORDS = frozenset(
    "a an and are as at be best buy buying by can for from good have i in is it "
    "me my need of on or please recommend should that the this to want what with "
    "would budget problem unlimited money price review reviews official source "
    "check latest current product products shopping".split()
)


class ResearchFact(StrEnum):
    WARRANTY = "warranty"
    PRICE = "price"
    AVAILABILITY = "availability"
    VARIANT = "variant"
    SELLER = "seller"
    RELEASE = "release"
    SUPPORT = "support"


_FACT_CUES = {
    ResearchFact.WARRANTY: r"\bwarrant(?:y|ies)\b",
    ResearchFact.PRICE: r"\b(?:price|prices|cost|costs|budget|priced)\b",
    ResearchFact.AVAILABILITY: r"\b(?:stock|availability|available|shipping|delivery|region|regional)\b",
    ResearchFact.VARIANT: r"\b(?:variant|variants|import|imported|capacity|storage|ram|\d+\s*gb)\b",
    ResearchFact.SELLER: r"\b(?:seller|trust|legitimacy|legitimate|counterfeit|authentic|safety|safe)\b",
    ResearchFact.RELEASE: r"\b(?:release|released|launch|launched|generation)\b",
    ResearchFact.SUPPORT: r"\b(?:updates|support)\b",
}
_FACT_ASSERTIONS = {
    ResearchFact.WARRANTY: r"\b(?:no|without|includes?|has|provides?|offers?|with|covered by|comes with|does not have|does not include)\b[^.!?]{0,55}\bwarranty\b|\bwarranty\b[^.!?]{0,65}\b(?:included|available|valid|covered|unavailable|excluded|limited|unverified|uncertain|\d+\s*(?:years?|months?))\b",
    ResearchFact.PRICE: r"\b(?:price|costs?|priced|sells?|sale)\b[^.!?]{0,55}\d|(?:\b[A-Z]{3}\s*|[$€£₱])\d[\d,.]*",
    ResearchFact.AVAILABILITY: r"\b(?:in (?:local )?stock|out of stock|available|not available|unavailable|ships? to|delivers? to|delivery (?:available|unavailable)|pickup only)\b",
    ResearchFact.VARIANT: r"\b(?:imported|\d+\s*gb)\b|\b(?:variant|model|capacity|storage|ram)\b\s+(?:is|of|[:=])\s+\w+|\b(?:has|uses?|includes?)\s+(?:a |an |the )?\w+(?:\s+\w+){0,2}\s+(?:variant|model|capacity|storage|ram)\b",
    ResearchFact.SELLER: r"\b(?:seller|listing|offer)\b[^.!?]{0,60}\b(?:verified|unverified|legitimate|illegitimate|suspicious|counterfeit|authentic|unknown|unsafe|risk)\b|\b(?:unverified|suspicious|counterfeit|unknown)\b[^.!?]{0,30}\b(?:seller|listing|offer)\b",
    ResearchFact.RELEASE: r"\b(?:released|launched|announced|launches|releases)\b[^.!?]{0,70}\b(?:\d{4}|today|yesterday|tomorrow)\b|\b\d{4}\b[^.!?]{0,70}\b(?:release|launch)\b",
    ResearchFact.SUPPORT: r"\b(?:support|updates)\b[^.!?]{0,65}\b(?:until|through|ends?|ended|\d+\s*(?:years?|months?))\b|\b\d+\s*(?:years?|months?)\b[^.!?]{0,35}\b(?:support|updates)\b",
}
_FACT_CONTEXT_WORDS = frozenset(
    "find show tell compare comparison information details specs specifications "
    "features official review reviews check status warranty warranties price prices cost "
    "costs budget stock availability available shipping delivery region regional variant "
    "variants import imported capacity storage ram seller trust legitimacy legitimate "
    "counterfeit authentic safety safe release released launch launched generation "
    "updates support".split()
)


def _required_facts(query: str, intent: SearchIntent) -> frozenset[ResearchFact]:
    required = {
        fact
        for fact, pattern in _FACT_CUES.items()
        if re.search(pattern, query, re.IGNORECASE)
    }
    if intent == SearchIntent.PRICE_CHECK:
        required.add(ResearchFact.PRICE)
    elif intent == SearchIntent.TRUST_CHECK:
        required.add(ResearchFact.SELLER)
    return frozenset(required)


def _supports_need(need: "EvidenceNeed", quote: str) -> bool:
    subject = terms(need.query) - _FACT_CONTEXT_WORDS
    if not subject or not subject <= terms(quote):
        return False
    return all(
        re.search(_FACT_ASSERTIONS[fact], quote, re.IGNORECASE)
        for fact in need.required_facts
    )


def terms(text: str) -> frozenset[str]:
    return frozenset(
        word
        for word in re.findall(r"[\w]+", text.casefold())
        if len(word) > 1 and word not in _STOP_WORDS
    )


def equivalent_url(url: str) -> str:
    parts = urlsplit(url)
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in {"ref", "referrer", "fbclid", "gclid"}
    )
    return urlunsplit(
        (parts.scheme, parts.netloc.casefold(), parts.path, urlencode(query), "")
    )


@dataclass
class EvidenceNeed:
    need_id: str
    intent: SearchIntent
    query: str
    required_facts: frozenset[ResearchFact]
    evidence_ids: set[SourceId] = field(default_factory=set)


@dataclass(frozen=True)
class LeadDecision:
    source_id: SourceId
    status: str
    reason: str
    need_id: str
    equivalent_source_id: SourceId | None = None

    def metadata(self) -> dict[str, str]:
        return {
            "status": self.status,
            "reason": self.reason,
            "need_id": self.need_id,
            **(
                {"equivalent_source_id": str(self.equivalent_source_id)}
                if self.equivalent_source_id is not None
                else {}
            ),
        }


@dataclass
class ResearchSelection:
    brief: ShoppingBrief
    needs: dict[str, EvidenceNeed] = field(default_factory=dict)
    leads: dict[SourceId, SearchResult] = field(default_factory=dict)
    decisions: dict[SourceId, LeadDecision] = field(default_factory=dict)
    admitted: set[SourceId] = field(default_factory=set)
    fetched: set[SourceId] = field(default_factory=set)
    support_roles: set[SearchIntent] = field(default_factory=set)
    support_sites: dict[SearchIntent, set[str]] = field(default_factory=dict)
    unreviewed_cautions: dict[SourceId, tuple[str, ...]] = field(default_factory=dict)
    quotes: dict[SourceId, list[str]] = field(default_factory=dict)

    @property
    def covered(self) -> bool:
        return (
            bool(self.needs)
            and all(need.evidence_ids for need in self.needs.values())
            and {SearchIntent.OFFICIAL_SOURCE, SearchIntent.REVIEW}
            <= self.support_roles
            and any(
                official != review
                for official in self.support_sites.get(SearchIntent.OFFICIAL_SOURCE, ())
                for review in self.support_sites.get(SearchIntent.REVIEW, ())
            )
            and not any(self.unreviewed_cautions.values())
        )

    def need(self, query: str, intent: SearchIntent) -> EvidenceNeed:
        required_facts = _required_facts(query, intent)
        identity = json.dumps(
            [
                intent.value,
                " ".join(query.casefold().split()),
                sorted(fact.value for fact in required_facts),
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        key = sha256(identity.encode()).hexdigest()[:16]
        return self.needs.setdefault(
            key, EvidenceNeed(key, intent, query, required_facts)
        )

    def reject(self, lead: SearchResult, need: EvidenceNeed, reason: str) -> None:
        self.leads[lead.source_id] = lead
        self.decisions[lead.source_id] = LeadDecision(
            lead.source_id, "rejected", reason, need.need_id
        )

    def select(
        self,
        results: list[SearchResult],
        need: EvidenceNeed,
        *,
        limit: int,
        max_characters: int = 2400,
    ) -> tuple[SearchResult, ...]:
        previous_leads = dict(self.leads)
        query_terms = terms(need.query)
        buyer_terms = terms(self.brief.original_query)
        ranked = []
        for lead in results:
            content = terms(lead.title + " " + (lead.snippet or ""))
            relevance = len(content & query_terms) * 3 + len(content & buyer_terms)
            caution = bool(material_cautions(lead.snippet or ""))
            role = _role(lead)
            role_fit = role == need.intent or role not in self.support_roles
            quality = {"strong": 3, "adequate": 2, "mixed": 1}.get(
                lead.quality.level.value, 0
            )
            region = (
                self.brief.region.region.country_code.casefold()
                if self.brief.region
                else ""
            )
            region_fit = int(
                bool(
                    region
                    and (
                        region
                        in terms(
                            str(lead.url)
                            + " "
                            + lead.title
                            + " "
                            + (lead.snippet or "")
                        )
                    )
                )
            )
            freshness = _known_date(lead)
            ranked.append(
                (relevance, caution, role_fit, quality, region_fit, freshness, lead)
            )
            if relevance and caution:
                self.unreviewed_cautions[lead.source_id] = tuple(
                    passage
                    for passage in material_cautions(lead.snippet or "")
                    if not any(
                        passage in quote
                        for quote in self.quotes.get(lead.source_id, ())
                    )
                )
        ranked.sort(
            key=lambda item: (
                -int(item[0] > 0 and item[1]),
                -item[0],
                -item[2],
                -item[3],
                -item[4],
                -item[5],
                str(item[6].source_id),
            )
        )
        selected: list[SearchResult] = []
        admitted_urls = {
            equivalent_url(str(previous_leads[source_id].url)): source_id
            for source_id in self.admitted
            if source_id in previous_leads
        }
        characters = 0
        for relevance, caution, _, _, _, _, lead in ranked:
            url = equivalent_url(str(lead.url))
            equivalent = admitted_urls.get(url)
            size = len(
                json.dumps(
                    {
                        "source_id": str(lead.source_id),
                        "url": url,
                        "title": lead.title,
                        "snippet": (lead.snippet or "")[:200],
                        "provider_source_type": lead.source_type.value,
                        "provider_name": lead.provider.provider_name,
                        **bounded_cautions(lead.snippet or ""),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            reason = "resolves_open_evidence_need"
            status = "selected"
            if not relevance:
                status, reason = "deferred", "no_buyer_or_need_match"
            elif equivalent is not None and not _new_caution(
                lead, previous_leads.get(equivalent) or self.leads[equivalent]
            ):
                status, reason = "deferred", "equivalent_url_already_admitted"
            elif not caution and any(
                _redundant(lead, previous)
                for previous in [
                    *selected,
                    *(
                        previous_leads[source_id]
                        for source_id in self.admitted
                        if source_id in previous_leads
                    ),
                ]
            ):
                status, reason = "deferred", "same_site_role_repetition"
            elif len(selected) >= limit or characters + size > max_characters:
                status, reason = "deferred", "shortlist_context_budget"
            elif caution:
                reason = "material_caution_or_contrary_lead"
            decision = LeadDecision(
                lead.source_id, status, reason, need.need_id, equivalent
            )
            self.decisions[lead.source_id] = decision
            if status == "selected":
                selected.append(lead)
                characters += size
                admitted_urls[url] = lead.source_id
                self.admitted.add(lead.source_id)
            self.leads[lead.source_id] = lead
        return tuple(selected)

    def admit_fetch(
        self, source: SearchResult, need_id: str | None
    ) -> EvidenceNeed | None:
        if self.covered:
            return None
        decision = self.decisions.get(source.source_id)
        need = self.needs.get(need_id or (decision.need_id if decision else ""))
        if need is None:
            need = self.need(source.query.query, source.query.intent)
        self.fetched.add(source.source_id)
        self.admitted.add(source.source_id)
        self.leads[source.source_id] = source
        self.decisions[source.source_id] = LeadDecision(
            source.source_id, "selected", "fetch_for_open_evidence_need", need.need_id
        )
        return need

    def observe(self, source_id: SourceId, original: str) -> None:
        self.unreviewed_cautions[source_id] = tuple(
            caution
            for caution in dict.fromkeys(
                [
                    *self.unreviewed_cautions.get(source_id, ()),
                    *material_cautions(original),
                ]
            )
            if not any(caution in quote for quote in self.quotes.get(source_id, ()))
        )

    def record_support(
        self, source: SearchResult, quote: str, evidence_id: SourceId
    ) -> None:
        self.quotes.setdefault(source.source_id, []).append(quote)
        decision = self.decisions.get(source.source_id)
        supported = False
        if decision is not None:
            need = self.needs[decision.need_id]
            supported = _supports_need(need, quote)
            if supported:
                need.evidence_ids.add(evidence_id)
        if supported:
            role = _role(source)
            self.support_roles.add(role)
            self.support_sites.setdefault(role, set()).add(
                urlsplit(str(source.url)).netloc.casefold()
            )
        self.unreviewed_cautions[source.source_id] = tuple(
            caution
            for caution in self.unreviewed_cautions.get(source.source_id, ())
            if caution not in quote
        )

    def widen(self, need_id: str, *, limit: int) -> tuple[SearchResult, ...]:
        need = self.needs.get(need_id)
        if need is None or self.covered:
            return ()
        pending = [
            self.leads[source_id]
            for source_id, decision in self.decisions.items()
            if decision.status == "deferred"
            and decision.need_id == need_id
            and decision.reason
            not in {"equivalent_url_already_admitted", "no_buyer_or_need_match"}
            and (
                not need.evidence_ids
                or _role(self.leads[source_id]) not in self.support_roles
                or bool(self.unreviewed_cautions.get(source_id))
            )
        ]
        return self.select(pending, need, limit=limit)


def _role(source: SearchResult) -> SearchIntent:
    if source.source_type == SourceType.OFFICIAL_BRAND_PAGE:
        return SearchIntent.OFFICIAL_SOURCE
    if source.source_type == SourceType.PROFESSIONAL_REVIEW:
        return SearchIntent.REVIEW
    if source.source_type == SourceType.RETAILER_LISTING:
        return SearchIntent.PRICE_CHECK
    return source.query.intent


def _new_caution(lead: SearchResult, previous: SearchResult) -> bool:
    return bool(
        set(material_cautions(lead.snippet or ""))
        - set(material_cautions(previous.snippet or ""))
    )


def _redundant(lead: SearchResult, previous: SearchResult) -> bool:
    if _role(lead) != _role(previous):
        return False
    first_url, second_url = (
        urlsplit(equivalent_url(str(lead.url))),
        urlsplit(equivalent_url(str(previous.url))),
    )
    if (
        first_url.netloc == second_url.netloc
        and first_url.path == second_url.path
        and first_url.query != second_url.query
    ):
        return False
    first, second = (
        terms(lead.title + " " + (lead.snippet or "")),
        terms(previous.title + " " + (previous.snippet or "")),
    )
    return (
        bool(first and second)
        and len(first & second) / len(first | second) >= 0.85
        and (
            urlsplit(str(lead.url)).netloc == urlsplit(str(previous.url)).netloc
            or (lead.snippet is not None and lead.snippet == previous.snippet)
        )
    )


def _known_date(lead: SearchResult) -> int:
    value = lead.provider.raw.get("published_date")
    if not isinstance(value, str):
        return 0
    try:
        published = date.fromisoformat(value)
    except ValueError:
        return 0
    return published.toordinal() if published <= date.today() else 0
