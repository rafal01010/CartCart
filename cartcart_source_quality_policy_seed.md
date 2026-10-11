# CartCart source-quality policy seed

Version `cartcart_source_quality_v2_2026-10-10` replaces recommendation eligibility rules with advisory context.

Prefer company announcements and official product pages for current product information, including Apple, Samsung, Oppo, Xiaomi and relevant manufacturers in every category. Independent reviews are optional. Search snippets, fetched pages and specialist context can inform the owning model without recorded quotations.

The runtime domain tables retain known manufacturer, retailer, review, community and marketplace classes across PH, US, KR, CA, JP, SG, MO, AU, NZ, HK and TW. A class or reputation does not establish product suitability or seller acceptability. Unknown domains and historical reseller/import/proxy flags remain usable context. No seeded domain is automatically excluded from search, retrieval or recommendations.

Quality scores remain advisory. Strong begins at 0.75, adequate at 0.50 and mixed at 0.25. These lower thresholds describe useful context more generously than the former 0.85, 0.65 and 0.40 values. Unknown sources can retain unknown quality. None of these values is a recommendation threshold.

An official store is acceptable seller context. Listing identity, fulfillment, return terms, warranty and source cautions help the model when available. Missing details do not require a background check or exclude an option. Multiple reviews without meaningful adverse findings can provide positive context. Strong actual adverse information must retain its product, variant, seller or offer scope for model judgment.

Requested budget, known price, currency and over-budget amounts inform the model. Slightly over-budget options are allowed with explanation. Unlimited budget remains unconstrained. Unknown or incomparable prices cannot be labeled within budget.

Safe network access, supported provider operations, bounded content and spending, and run-scoped saved records remain necessary operational boundaries. Domain reputation policies are advisory rather than retrieval filters.
