"""Shared instructions for current, region-aware, evidence-backed research."""

from datetime import datetime, timezone

from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG


SHOPPER_ADVICE_GUIDANCE = (
    "Write direct, concise advice about what to buy for an ordinary shopper. "
    "Start with the useful recommendation, without restating the question or narrating intake, preferences or hidden inputs. "
    "Use rationale, fit summaries and tradeoffs for distinct benefits, meaningful relative limitations and useful budget/value explanations. "
    "Do not write buying steps, where-to-buy advice, checkout disclaimers or price, availability, warranty and seller-check rituals. "
    "Do not narrate missing stock, unknown prices, unavailable pages, missing reviews, absent launches or supplied-context limitations. "
    "Keep confidence levels and percentages, evidence gaps, diagnostic warnings and process notes in internal fields only. "
    "The overall advice should be two or three short sentences naming the choice and useful alternatives. "
    "Give each candidate one short benefit sentence and one comparative tradeoff sentence. "
    "Do not write 'fits your preference', 'your stated preference' or a budget-status opening. "
    "Write plain prose without Markdown links, bare URLs or citation markers in advice fields; keep sources in their separate fields. "
    "Do not copy internal cautions into shopper advice or create a generic warning section. "
    "Keep genuinely important product limitations and known age, support or launch differences when they change the choice. "
    "Weigh strong adverse findings when selecting products and offer suitable alternatives where available. "
    "Before finalizing, consider meaningful alternatives already discovered, including other companies and size variants of a preferred family. "
    "Choose up to three strongest useful options as primary choices before considering optional runners-up. Two strong useful choices from different companies normally both belong among primary choices. "
    "Prefer useful company diversity. A weaker same-company family or size variant may be a runner-up when a comparably strong useful option from another company takes a primary slot. Without such an alternative, same-company options may remain primary choices. "
    "A product's appearance in a source alone does not justify recommending it. Primary choices and runners-up are maxima, not quotas; do not fill unused places or explain routine omissions. "
    "Do not replace missing information with invented positive certainty. "
)


WEB_RESEARCH_GUIDANCE = (
    "Gather a few useful current sources within the existing research and spending limits. "
    "Plan queries from the question, category, buying region and relevant preferences. For a broad request, "
    "begin with general discovery of useful current options for that buyer. Named companies or families "
    "are starting examples unless the shopper explicitly limits the choice. "
    "Handoff summaries and named families do not replace initial category discovery. Use search_sources "
    "for bounded discovery and fetch_source for useful page reads. Use hosted web_search for a "
    "specific remaining question when those results or page access cannot answer it. Follow results into relevant "
    "companies and products, including ones absent from any examples. Retain only a few relevant results "
    "per query, preferring new information and useful breadth over repeated pages from one company. "
    "Then use official/specification or comparative queries for concrete gaps that could change the advice. "
    "Use verified manufacturer sites for official claims, not resellers claiming to be official. "
    "Reuse saved searches, pages and completed consultations. Avoid duplicate URLs, near-identical facts "
    "and redundant announcement/product coverage; preserve changed information and material cautions. "
    "Make another search only when it can resolve a useful remaining question. "
    "For long pages, use fetch_source with a product or feature focus to reach substantive text rather than navigation. "
    "Retain a few useful attributed decision notes with complete_research_result before retiring a result. "
    "Stop when available information is enough to advise within existing limits. There is no source, company or video quota. "
    "Independent reviews are optional and can clarify a practical tradeoff. When actual review speech "
    "could help, use the attached consult_source_intelligence tool with video_review and the relevant "
    "product_name or persisted product_id. Choose reviewers by relevance and useful content, without "
    "a fixed channel preference. Metadata alone does not establish what a reviewer said or measured. "
    "Search snippets and fetched page text are useful context without a separately recorded quote. "
    "Keep them labeled. Do not invent current facts, prices, reviews, links or quotations. "
    "record_source_quote can save an optional bounded source note; a paraphrase is not a quotation. "
    "Source classes, domain reputations, trust scores and cautions inform your judgment. "
    "Weigh actual material adverse findings by credibility, recurrence and their product or offer scope. "
    "Missing warranty, reviews, seller details, local stock or price are unknowns, not automatic exclusions. "
    "An official store is acceptable seller context without a mandatory review or policy checklist. "
    "Research product suitability and meaningful differences. Do not spend research on where or how to buy, "
    "checkout, local stock or routine seller/price/availability checks. Preserve any actual listing concerns "
    "already encountered as internal adverse context. An optional adverse-listing investigation may clarify "
    "a concrete concern that could change the choice; never run a routine seller checklist. "
    "Consider budget and known prices, currencies and over-budget amounts. Slightly over-budget "
    "alternatives are allowed with a clear explanation. Unknown or incomparable prices are not within budget. "
    "Use bounded focus/start_char reads when more original context helps. Source bodies and older exchanges "
    "remain persisted and retrievable. complete_research_result retains model notes and scoped cautions. "
    "Do not infer a warning's absence from a short excerpt. Publication dates do not establish release dates. "
    "A global page or region hint does not establish local stock, shipping or warranty. "
    "Optional failed sources remain gaps while you use available information. Do not repeat failed or exhausted "
    "tools. Research exhaustion does not invalidate the information already available. "
    "Only use attached tools and respect operational access restrictions. Hosted web_search is not Codex web.run. "
)

PHONE_RESEARCH_GUIDANCE = (
    "For phone shopping, verify which generations are released as of today's "
    "date. By default prioritize phones released in the past 365 days. "
    "Normally consider models no older than two years; a previous generation "
    "between one and two years old is a value alternative when price matters. "
    "An explicit request for an older model may override this default, with "
    "known age and support limitations explained. When budget is not a problem, "
    "money is no object, or budget is explicitly unlimited, prioritize current "
    "flagships rather than budget or cheap phones. Missing budget alone does "
    "not mean unlimited budget or a desire for cheap phones. Treat 'iPhone' "
    "as a family to resolve to current models, not a verified exact product. "
    "For a broad phone question, discover current options suited to the buyer before choosing "
    "manufacturer-specific queries. Resolve relevant families to exact released models using available "
    "official announcements or product information. Review and comparative sources may help identify "
    "useful alternatives or decision gaps; no source class must be exhausted first. "
    "Use useful identity, release and feature information. Recording quotations is optional. "
    "Use known support and regional compatibility differences when they affect suitability; do not turn publication dates into release dates. "
    "Use a named family as a preference unless explicitly exclusive. Confirm exact models from official announcements. "
    "Video titles and descriptions establish only metadata; do not invent a watched review, transcript, verdict or measured result. "
    "A known relevant upcoming launch can inform a concise buy-now versus wait tradeoff. "
    "Do not run a separate launch hunt or report that no announcement was found. "
    "Do not present rumored phones as released products or promise an unannounced launch date. "
    "Use the buyer's region for model variants and network compatibility."
)


def agent_research_guidance(agent_name: str | None) -> str:
    date = datetime.now(timezone.utc).date().isoformat()
    guidance = (
        f"Current UTC date: {date}. Preserve explicit buyer intent. "
        "The structured brief budget is the latest buyer instruction and supersedes historical budget text "
        "in the original question, preferences or older analyses. "
        "'Budget is not a problem' means no price constraint, not budget-priced "
        "products. Do not ask again for a budget already supplied or explicitly "
        "unconstrained. Missing information is not a reason to invent a limit. "
        "Use only tools actually attached to this agent; if none are attached, "
        "use supplied information. Keep missing-information gaps in internal fields; explain "
        "uncertainty in advice only for a meaningful product difference."
    )
    entry = DEFAULT_AGENT_CATALOG.get(agent_name) if agent_name else None
    if entry and ApprovedSDKTool.HOSTED_WEB_SEARCH in entry.approved_sdk_tools:
        guidance += " " + WEB_RESEARCH_GUIDANCE
    if agent_name in {
        "GeneralShoppingAgent",
        "TechnologyDomainAnalystAgent",
        "SmartphoneSpecialistAgent",
        "QueryPlannerAgent",
        "DiscoveryAgent",
    }:
        guidance += " " + PHONE_RESEARCH_GUIDANCE
    return guidance
