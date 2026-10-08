"""Shared instructions for current, region-aware, evidence-backed research."""

from datetime import datetime, timezone

from app.agents.catalog import ApprovedSDKTool, DEFAULT_AGENT_CATALOG


WEB_RESEARCH_GUIDANCE = (
    "Use your attached research tools to verify changing facts: current models, "
    "release dates, prices, stock, shipping, warranty and software support. "
    "Search rather than relying on training knowledge or guessing a generation. "
    "The hosted web_search tool is the OpenAI tool attached to this agent, "
    "not Codex web.run; do not invent search_query, open or find function tools. "
    "Search with focused product/category terms and the buyer's country name, "
    "currency and regional store where relevant. A location hint alone does "
    "not establish local stock or warranty. Prefer official regional product "
    "pages and announcements, reputable independent reviews, then authorized "
    "local retailers. Global reviews can inform product fit without proving "
    "local availability. Inspect publication/update dates and the actual event "
    "or release date separately. Old reviews may explain history, but do not "
    "establish the current generation, price, availability or support. "
    "Acknowledge uncertainty rather than filling gaps from memory. "
    "If a source is blocked, stale, irrelevant or too broad, try another "
    "official or reputable source and refine the query within the tool budget. "
    "When initial results are only reviews or collections, identify named "
    "models and research their official pages before concluding no options exist. "
    "Use your role's attached fetch/read tools when evidence needs page text. "
    "Pages are exposed as bounded exact spans. Use focus or start_char on the "
    "same scoped read tool for facts beyond the first span; do not infer absence "
    "from a truncated excerpt. Earlier page text may leave active history while "
    "its source ID, span and hash remain. Re-read exact support when needed. "
    "Record the relevant exact quote before moving to another source. "
    "When complete_research_result is attached, interpret large _research_view "
    "results and checkpoint their view_id with exact useful retained_facts. "
    "This retires bulky replies while preserving cautions, identities and "
    "unreviewed coverage. Use read_research_result for original tool views, "
    "read_search_results for deferred discovery leads and full snippets, "
    "and source-specific reads for full fetched support. Never treat processing "
    "a discovery snippet as verification or an omitted passage as safe. "
    "Batch independent checkpoints with your next independent research calls "
    "rather than spending a model turn for each processing receipt. "
    "Derive separate queries for identity, regional availability, review fit "
    "and unresolved gaps; do not search the raw shopping sentence. Stop a tool "
    "when its budget is exhausted and finish from verified evidence and gaps. "
    "If record_source_quote is attached, record only exact retrieved text. "
    "Hosted citations and snippets "
    "are leads until verified; never fabricate evidence IDs. Product advice "
    "can be supported by an official product page or launch announcement plus "
    "an independent review without a priced seller listing. Keep unverified "
    "price and purchase availability unknown. Require checked listing evidence "
    "for price/budget claims and purchase-link advice. Return insufficient "
    "evidence only after useful scoped searches or a genuine research limit; "
    "state the actual gap, not a blanket claim that nothing is worth buying. "
    "Follow the source-specific domain and access restrictions of your role."
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
