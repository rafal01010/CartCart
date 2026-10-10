"""Shared instructions for current, region-aware, evidence-backed research."""

from datetime import datetime, timezone

from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG


WEB_RESEARCH_GUIDANCE = (
    "Verify changing facts using attached research tools, never memory or guessed generations. "
    "Use focused queries for named products, buyer country, identity, review fit and missing support. "
    "Compare two or three promising current products when supported; do not enumerate the entire market. "
    "Start with at most two focused queries and three results each. Widen only for a named evidence gap or failed source. "
    "A named brand/family preference is not exclusive unless the buyer says it is; consider close alternatives. "
    "One or two useful exact official quotes per candidate are enough for basic product facts; avoid repetitive quoting. "
    "Prefer company announcements and official product websites for relevant manufacturers in any category, "
    "including Apple, Samsung, Oppo and Xiaomi for phones. Verify source identity and useful exact product facts. "
    "Start with dated official launch/announcement articles or substantive official product pages. Reviews are optional. "
    "Search for current product announcements, including the buyer region where relevant. "
    "Fetch useful official facts for the distinct candidates first; seek a substantive review when it can clarify a tradeoff. "
    "Prefer search_sources for retrievable run-scoped leads. Hosted search discovers leads but does not replace fetched review evidence. "
    "Official product pages are sufficient when they contain useful product facts; use store pages for checked purchase details. "
    "Check that fetched text describes the product. Navigation, setup, shipping and general store services are a dead end, "
    "not product support. Switch to an official announcement or another substantive source instead of rereading that page. "
    "After a blocked or empty review, use another unfetched review lead only if the comparison needs it and budget remains. "
    "Do not repeat the failed fetch/read. Missing optional reviews must not delay a supported shortlist. "
    "A fetched page is not recorded evidence. Call record_source_quote for useful product facts; do not keep rereading a dead end. "
    "After each useful fetch, immediately record short exact page quotes with record_source_quote "
    "before fetching more pages. Batch independent quotes in one turn. "
    "Verified official product facts can support a product-only suggestion. Independent reviews improve comparison confidence; "
    "their absence alone is not a reason to return no options. Attribute manufacturer claims and qualify untested performance. "
    "a priced listing is optional unless the buyer has a hard price cap. "
    "Unknown local stock, price, seller, warranty or support duration must be disclosed and restrict purchase claims; "
    "they do not alone prevent a supported product-only recommendation. A material incompatibility or safety concern still matters. "
    "Finish with a named product and concise supported reasons when this evidence exists. "
    "Write reasons as buying advice, without internal workflow or validation terminology. "
    "The primary rationale uses only the selected candidate's cited facts. Put another product's features "
    "in its own alternative selection with its own evidence IDs, not in the primary rationale. "
    "Widen research only for a specific missing fact, conflict or material caution. "
    "Use focus/start_char for bounded original page spans. Do not infer absence from a short excerpt. "
    "Old tool exchanges may be archived; read_research_result retrieves their scoped originals. "
    "Source bodies remain persisted. Omitted passages remain unreviewed and cannot establish safety. "
    "complete_research_result retains exact useful facts before retiring bulk; snippets stay unverified. "
    "read_search_results retrieves original/deferred leads; need_id widens an unresolved evidence need. "
    "Keep contrary evidence, seller/variant/region/warranty risks, sponsorship and source gaps. "
    "Publication dates do not establish release dates. Old reviews do not prove current availability/support. "
    "A region hint or global review does not prove local stock, shipping or warranty. "
    "Require checked listing evidence for prices, budget claims and purchase links; otherwise keep them unknown. "
    "For blocked, stale or irrelevant sources, try another approved source within the budget. "
    "Stop exhausted tools. Explain genuine missing support or technical limits; never invent IDs or facts. "
    "Only use attached tools. Hosted web_search is not Codex web.run; do not invent search_query/open/find tools. "
    "Follow role-specific source, domain and access restrictions."
)

PHONE_RESEARCH_GUIDANCE = (
    "For phone shopping, verify which generations are released as of today's "
    "date. By default prioritize phones released in the past 365 days. "
    "Normally consider models no older than two years; a previous generation "
    "between one and two years old is a value alternative when price matters. "
    "An explicit request for an older model may override this default, with "
    "its age and remaining support disclosed. When budget is not a problem, "
    "money is no object, or budget is explicitly unlimited, prioritize current "
    "flagships rather than budget or cheap phones. Missing budget alone does "
    "not mean unlimited budget or a desire for cheap phones. Treat 'iPhone' "
    "as a family to resolve to current models, not a verified exact product. "
    "For a broad phone question, resolve the latest released iPhone and Samsung flagship families first, "
    "then a relevant Oppo, Xiaomi or other manufacturer's current alternative when useful. "
    "Use that manufacturer's verified official site, not a reseller claiming to be official. "
    "Include at most three supported options with tradeoffs. "
    "Use the first two focused queries for current official iPhone and Samsung announcements, one family each. "
    "Scope Apple's announcement query to site:apple.com/newsroom and Samsung's to site:news.samsung.com. "
    "If a newsroom page is unavailable, use a current official product page for that family; "
    "do not replace a primary source with shipping timelines or an unattributed syndicated copy. "
    "fetch and record useful official facts for both before spending on optional review research. "
    "Prefer a short exact identity/release-or-availability quote and one useful feature quote per phone. "
    "Disclose unknown support duration and regional stock; do not turn publication dates into release dates. "
    "Use a named family as a preference unless explicitly exclusive. Confirm exact models from official announcements. "
    "Seek substantive YouTube reviews from Marques Brownlee/MKBHD through the approved YouTube source tool "
    "when review evidence is useful and access is available. Other credible reviewers may corroborate or substitute. "
    "Video titles and descriptions establish only metadata; do not invent a watched review, transcript, verdict or measured result. "
    "Check official upcoming launch announcements and credible launch timing. "
    "If a relevant next generation may arrive within about 60 days, explain "
    "the buy-now versus wait tradeoff and whether the date is confirmed or "
    "only expected. Do not present rumored phones as released products or "
    "promise an unannounced launch date. Use the buyer's region for variants, "
    "network compatibility, authorized availability and warranty."
)


def agent_research_guidance(agent_name: str | None) -> str:
    date = datetime.now(timezone.utc).date().isoformat()
    guidance = (
        f"Current UTC date: {date}. Preserve explicit buyer intent. "
        "'Budget is not a problem' means no price constraint, not budget-priced "
        "products. Do not ask again for a budget already supplied or explicitly "
        "unconstrained. Missing information is not a reason to invent a limit. "
        "Use only tools actually attached to this agent; if none are attached, "
        "use supplied evidence or ask the research owner for missing evidence."
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
