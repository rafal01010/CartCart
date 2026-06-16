# CartCart Source-Quality Policy Seed

**Version:** MVP seed  
**Date:** 2026-06-13  
**Scope:** Philippines, United States, South Korea, Canada, Japan, Singapore, Macao, Australia, New Zealand, Hong Kong, Taiwan

---

## A. Recommended policy decisions and scoring behavior

Use a **two-layer score**:

1. **Source/domain quality score**
   - `official_manufacturer`: strongest for specifications, model identity, product variants, compatibility, warranty terms for that brand only.
   - `established_retailer_first_party`: strong purchase evidence when the retailer is the seller of record.
   - `established_retailer_mixed`: domain is reputable, but listing-level trust is required.
   - `open_marketplace`: useful for price discovery only after seller/listing checks.
   - `review_testing`: strong supporting evidence for quality/performance, not purchase availability.
   - `community`: qualitative weak evidence only.
   - `unknown`: weak until verified.

2. **Offer/listing quality score**
   - Always evaluate seller, fulfillment, warranty, return path, shipping origin, currency, model number, and condition separately from domain reputation.
   - Amazon, Walmart, Best Buy marketplace, Target Plus, Rakuten, Yahoo Shopping Japan, Shopee, Lazada, eBay, HKTVmall, The Warehouse Marketplace, Kmart Marketplace, Rakuten, Gmarket, Coupang, and similar services must never be treated as uniformly first-party.

Recommended MVP scoring:

| Evidence type | Baseline behavior |
|---|---|
| Official manufacturer page matching shopper region | Highest spec/product-identity evidence |
| Official manufacturer page from another country | Strong spec evidence, weak price/availability/warranty evidence |
| Established retailer, sold by retailer | Strong purchase evidence |
| Established retailer, third-party seller | Medium until seller checks pass |
| Marketplace listing with official store badge | Medium-high, but not guaranteed |
| Marketplace listing with unknown seller | Weak-medium at best |
| Classifieds / peer-to-peer | Weak purchase evidence; qualitative only unless user explicitly wants used/local |
| Proxy/import/reseller aggregator | Usually exclude as purchase evidence |
| Review lab testing | Strong performance evidence |
| Editorial buying guide | Medium supporting evidence |
| User/community reviews | Weak qualitative evidence |

Important current-market findings: many “established retailer” domains now have marketplace inventory mixed into normal search results. The policy should therefore score the domain and the offer separately: domain reputation helps, but seller/fulfillment/return details still control purchase confidence.

---

## B. Target-region table

| Region | Currency / tax notes | Strong first-party retail seeds | Mixed marketplace seeds | Main concerns |
|---|---:|---|---|---|
| Philippines | PHP; prices generally VAT-inclusive for consumer retail | `abenson.com`, `ansons.ph`, `smstore.com`, `wilcon.com.ph`, `acehardware.ph`, `ikea.com/ph/en`, `rustans.com`, `zalora.com.ph` | `shopee.ph`, `lazada.com.ph`, `carousell.ph`, `facebook.com/marketplace` | COD scams, gray-market electronics, no local warranty, fake beauty/skincare, “Mall” badge over-trust, imported plug/voltage |
| United States | USD; sales tax usually calculated by state at checkout | `target.com`, `costco.com`, `homedepot.com`, `lowes.com`, `bestbuy.com`, `ikea.com/us/en`, `wayfair.com`, `chewy.com`, `ulta.com` | `amazon.com`, `walmart.com`, `ebay.com`, `bestbuy.com`, `target.com`, `etsy.com` | Third-party marketplace safety, counterfeit beauty/supplements, refurbished/open-box confusion, state tax/shipping |
| South Korea | KRW; VAT normally included in displayed consumer prices | `coupang.com`, `ssg.com`, `lotteon.com`, `oliveyoung.co.kr`, `musinsa.com`, `emart.ssg.com`, `ikea.com/kr/en` | `coupang.com`, `gmarket.co.kr`, `11st.co.kr`, `auction.co.kr`, `naver.com` shopping listings | Parallel imports, Korean-only model variants, plug type C/F, returns/account requirements, local AS availability |
| Canada | CAD; GST/HST/PST often added/varies by province | `canadiantire.ca`, `costco.ca`, `homedepot.ca`, `lowes.ca`, `ikea.com/ca/en`, `shoppersdrugmart.ca`, `londondrugs.com` | `amazon.ca`, `walmart.ca`, `bestbuy.ca`, `ebay.ca`, `thebay.com` | Province tax, bilingual packaging, US-import listings, warranty validity, marketplace sellers on retailer domains |
| Japan | JPY; tax-inclusive display common | `yodobashi.com`, `biccamera.com`, `nitori-net.jp`, `muji.com/jp`, `zozo.jp`, `aeonretail.com`, `ikea.com/jp/en` | `amazon.co.jp`, `rakuten.co.jp`, `shopping.yahoo.co.jp`, `mercari.com/jp`, `kakaku.com` shop links | Domestic-only warranty, Japanese keyboard/model, 100V appliances, proxy buying, marketplace store reputation |
| Singapore | SGD; GST included or shown depending retailer | `courts.com.sg`, `harveynorman.com.sg`, `gaincity.com`, `challenger.sg`, `ikea.com/sg/en`, `fairprice.com.sg`, `watsons.com.sg` | `amazon.sg`, `shopee.sg`, `lazada.sg`, `qoo10.sg`, `carousell.sg` | Parallel imports, GST/import threshold, seller origin, local service center, fake beauty/personal care |
| Macao | MOP/HKD; many HK-based retailers serve Macau | `ikea.com.hk`, `fortress.com.hk`, `broadwaylifestyle.com`, `watsons.com.hk`, `hktvmall.com` | `hktvmall.com`, `carousell.com.hk`, `taobao.com`, `tmall.com` | HK vs Macau delivery, MOP/HKD, customs/import, service center availability, CN/HK variant differences |
| Australia | AUD; GST generally included in consumer prices | `jbhifi.com.au`, `thegoodguys.com.au`, `bunnings.com.au`, `officeworks.com.au`, `kmart.com.au`, `bigw.com.au`, `ikea.com/au/en`, `petbarn.com.au` | `amazon.com.au`, `ebay.com.au`, `catch.com.au`, `kmart.com.au`, `mydeal.com.au` | Marketplace dropshippers, Australian plug/safety marks, warranty under ACL, gray imports, button-battery/toy safety |
| New Zealand | NZD; GST generally included | `thewarehouse.co.nz`, `noelleeming.co.nz`, `mitre10.co.nz`, `briscoes.co.nz`, `farmers.co.nz`, `ikea.com/nz/en` | `trademe.co.nz`, `thewarehouse.co.nz`, `themarket.com`, `mightyape.co.nz` where marketplace seller present | NZ warranty/CG Act, AU imports, shipping to islands/rural, plug compliance, marketplace badge |
| Hong Kong | HKD; no VAT/GST | `fortress.com.hk`, `broadwaylifestyle.com`, `hktvmall.com`, `watsons.com.hk`, `mannings.com.hk`, `ikea.com.hk` | `hktvmall.com`, `carousell.com.hk`, `taobao.com`, `tmall.com`, `amazon.com` cross-border | Parallel imports, official HK warranty, CN/HK plug, stock location, “water goods” electronics |
| Taiwan | TWD; VAT typically included in retail display | `pchome.com.tw`, `momoshop.com.tw`, `books.com.tw`, `tk3c.com`, `senao.com.tw`, `ikea.com.tw`, `watsons.com.tw` | `shopee.tw`, `ruten.com.tw`, `rakuten.com.tw`, `momo` seller/merchant pages where applicable | Marketplace seller identity, warranty card region, 110V appliances, Mandarin-only models/manuals, cross-border listings |

---

## C. Reseller/import-only exclusion domains

Normally exclude these as **purchase evidence** unless the user explicitly wants proxy buying, resale, collectibles, secondhand, or hard-to-find imports.

| Domain | Exclusion reason |
|---|---|
| `buyee.jp` | Proxy/import service; not original seller. |
| `jauce.com` | Proxy access to Yahoo Japan Auctions / Japanese malls; seller identity and warranty not direct. |
| `zenmarket.jp` | Proxy/import purchasing; use only as logistics evidence, not product trust. |
| `fromjapan.co.jp` | Proxy/import purchasing. |
| `neokyo.com` | Proxy/import purchasing. |
| `sendico.com` | Proxy/import purchasing. |
| `stockx.com` | Resale marketplace; useful for authenticity/market pricing only in narrow categories. |
| `goat.com` | Resale sneakers/apparel marketplace. |
| `grailed.com` | Peer/resale fashion. |
| `carousell.ph`, `carousell.sg`, `carousell.com.hk` | Peer-to-peer/classifieds style; weak purchase evidence unless user wants used/local. |
| `mercari.com`, `jp.mercari.com` | Resale/peer marketplace; not normal retailer evidence. |
| `facebook.com/marketplace` | Local classifieds; high seller-specific risk. |
| `aliexpress.com`, `temu.com`, `shein.com` | Cross-border/marketplace or import-heavy platforms; may be useful for low-price discovery but should be weak evidence for quality, safety, warranty, and authenticity. |

Do **not** automatically exclude ordinary retailers just because they sell imported goods. Exclude only where the platform primarily obscures or intermediates the real seller, is resale/classifieds, or does not provide reliable local warranty/return evidence.

---

## D. Mixed marketplace domains by region

| Region | Mixed marketplace domains | Required checks |
|---|---|---|
| Philippines | `shopee.ph`, `lazada.com.ph`, `carousell.ph`, `facebook.com/marketplace` | Seller age, badge, ratings distribution, fulfillment, local return address, warranty card, price sanity |
| US | `amazon.com`, `walmart.com`, `ebay.com`, `target.com`, `bestbuy.com`, `etsy.com` | Sold-by, ships-from, FBA/Walmart Fulfilled/Target Plus/Best Buy Marketplace status, return party, counterfeit risk |
| Korea | `coupang.com`, `gmarket.co.kr`, `11st.co.kr`, `auction.co.kr`, Naver shopping merchants | Rocket/Jikgu distinction, seller identity, Korean warranty, parallel import labels |
| Canada | `amazon.ca`, `walmart.ca`, `bestbuy.ca`, `ebay.ca`, `thebay.com` | Sold-by, marketplace badge, province shipping, Canadian warranty |
| Japan | `amazon.co.jp`, `rakuten.co.jp`, `shopping.yahoo.co.jp`, `mercari.com/jp`, `kakaku.com` linked stores | Store score, condition, domestic warranty, proxy/import warning |
| Singapore | `amazon.sg`, `shopee.sg`, `lazada.sg`, `qoo10.sg`, `carousell.sg` | Local seller, SG plug, GST/import, official-store badge |
| Macao | `hktvmall.com`, `carousell.com.hk`, `taobao.com`, `tmall.com` | Macau delivery, HK/MO warranty, mainland import status |
| Australia | `amazon.com.au`, `ebay.com.au`, `catch.com.au`, `kmart.com.au`, `mydeal.com.au` | Seller identity, AU stock, AU plug/compliance, ACL returns |
| New Zealand | `trademe.co.nz`, `thewarehouse.co.nz`, `themarket.com`, `mightyape.co.nz` where seller is not retailer | NZ-based seller, CGA warranty, import shipping |
| Hong Kong | `hktvmall.com`, `carousell.com.hk`, `taobao.com`, `tmall.com` | Merchant identity, HK warranty, water-goods label |
| Taiwan | `shopee.tw`, `ruten.com.tw`, `rakuten.com.tw`, merchant listings on `momoshop.com.tw` where applicable | Seller identity, local warranty, invoice, cross-border origin |

---

## E. Established retailer domains by region and category

Use these as MVP seeds. Classification still depends on the specific listing.

| Region | Domain | Categories | Status |
|---|---|---|---|
| Philippines | `abenson.com` | Electronics, appliances, furniture | First-party retailer |
| Philippines | `ansons.ph` | Electronics, appliances | First-party retailer |
| Philippines | `smstore.com` | Department store, fashion, home, beauty, toys | First-party / possible marketplace-like assortment; verify listing |
| Philippines | `wilcon.com.ph` | Tools, home improvement, bath, building materials | First-party retailer |
| Philippines | `acehardware.ph` | Tools, home improvement, outdoor | First-party retailer |
| Philippines | `ikea.com/ph/en` | Furniture, home, kitchen | Official regional IKEA |
| Philippines | `rustans.com` | Department store, beauty, fashion, home | First-party retailer |
| Philippines | `petexpress.com.ph` | Pet products | First-party retailer |
| US | `target.com` | General, home, baby, toys, clothing, beauty | Both; Target Plus marketplace requires listing checks |
| US | `walmart.com` | General, grocery, home, electronics, toys | Both; Marketplace requires seller checks |
| US | `costco.com` | General, appliances, furniture, electronics | Membership first-party retail |
| US | `bestbuy.com` | Electronics, appliances, cameras, office | Both; Best Buy Marketplace now exists |
| US | `homedepot.com` | Tools, home improvement, appliances, outdoor | First-party / marketplace-like special order; listing checks |
| US | `lowes.com` | Tools, home improvement, appliances, outdoor | First-party / marketplace-like special order; listing checks |
| US | `chewy.com` | Pet products | First-party retailer |
| US | `ulta.com` | Beauty, personal care | First-party retailer / brand retail |
| Korea | `coupang.com` | General, electronics, household, baby, pet | Both |
| Korea | `ssg.com` | Department store, grocery, home, beauty | Both / group retail |
| Korea | `lotteon.com` | Department store, fashion, beauty, electronics | Both |
| Korea | `oliveyoung.co.kr` | Beauty, personal care | First-party / brand platform |
| Korea | `musinsa.com` | Clothing, footwear, beauty | Fashion marketplace/retailer; listing checks |
| Canada | `canadiantire.ca` | Home, tools, automotive, sports, outdoor | First-party / marketplace-like assortment; listing checks |
| Canada | `costco.ca` | General, appliances, furniture, electronics | Membership first-party retail |
| Canada | `bestbuy.ca` | Electronics, appliances, cameras | Both; official marketplace source confirms third-party sellers |
| Canada | `homedepot.ca` | Tools, home improvement, appliances | First-party / marketplace-like assortment |
| Canada | `shoppersdrugmart.ca` | Beauty, personal care, baby, pharmacy retail | First-party retailer |
| Japan | `yodobashi.com` | Electronics, cameras, appliances, toys, office | First-party retailer |
| Japan | `biccamera.com` | Electronics, cameras, appliances, toys | First-party retailer |
| Japan | `nitori-net.jp` | Furniture, home, kitchen | First-party retailer |
| Japan | `muji.com/jp` | Home, clothing, beauty, stationery | Official regional store |
| Japan | `zozo.jp` | Clothing, footwear | Fashion marketplace/retailer; listing checks |
| Singapore | `courts.com.sg` | Electronics, appliances, furniture | First-party retailer |
| Singapore | `harveynorman.com.sg` | Electronics, appliances, furniture | First-party retailer |
| Singapore | `gaincity.com` | Electronics, appliances, furniture | First-party retailer |
| Singapore | `challenger.sg` | Electronics, office, accessories | First-party retailer |
| Singapore | `fairprice.com.sg` | Grocery, household, baby, pet | First-party retailer |
| Macao/HK | `fortress.com.hk` | Electronics, appliances | First-party retailer |
| Macao/HK | `broadwaylifestyle.com` | Electronics, appliances | First-party retailer |
| Macao/HK | `hktvmall.com` | General, grocery, beauty, home, electronics | Mixed marketplace/merchant mall |
| Macao/HK | `watsons.com.hk` | Beauty, personal care, baby | First-party retailer |
| Australia | `jbhifi.com.au` | Electronics, cameras, appliances | First-party retailer |
| Australia | `thegoodguys.com.au` | Appliances, electronics | First-party retailer |
| Australia | `bunnings.com.au` | Tools, home improvement, outdoor | First-party / marketplace-like special order; listing checks |
| Australia | `officeworks.com.au` | Office, tech, stationery | First-party retailer |
| Australia | `kmart.com.au` | Home, toys, clothing, kitchen | Both; official marketplace terms/returns exist |
| Australia | `bigw.com.au` | General, toys, baby, clothing, home | First-party / possible marketplace-like; verify seller |
| New Zealand | `thewarehouse.co.nz` | General, home, toys, clothing, electronics | Both; official marketplace page says verified marketplace stores |
| New Zealand | `noelleeming.co.nz` | Electronics, appliances | First-party retailer |
| New Zealand | `mitre10.co.nz` | Tools, home improvement, garden | First-party retailer |
| New Zealand | `briscoes.co.nz` | Home, kitchen, bedding | First-party retailer |
| New Zealand | `farmers.co.nz` | Department store, fashion, beauty, home | First-party retailer |
| Hong Kong | `fortress.com.hk` | Electronics, appliances | First-party retailer |
| Hong Kong | `broadwaylifestyle.com` | Electronics, appliances | First-party retailer |
| Hong Kong | `hktvmall.com` | General, grocery, beauty, home, electronics | Mixed marketplace |
| Hong Kong | `mannings.com.hk` | Beauty, personal care, baby | First-party retailer |
| Taiwan | `pchome.com.tw` | Electronics, home, daily goods | First-party B2C / group e-commerce |
| Taiwan | `momoshop.com.tw` | 3C, appliances, household, beauty, fashion, sports | B2C e-commerce |
| Taiwan | `books.com.tw` | Books, stationery, lifestyle, home | First-party retailer / platform |
| Taiwan | `tk3c.com` | Electronics, appliances | First-party retailer |
| Taiwan | `watsons.com.tw` | Beauty, personal care | First-party retailer |

---

## F. Official manufacturer/store seed domains by category

Rule: official domains are authoritative **only for their own products**. Regional paths matter for price, stock, warranty, delivery, plug/voltage, cellular bands, keyboard layout, language, and return policy.

| Category | Seed official domains | Region note |
|---|---|---|
| Electronics / phones | `apple.com`, `samsung.com`, `sony.com`, `lg.com`, `panasonic.com`, `lenovo.com`, `hp.com`, `dell.com`, `asus.com`, `acer.com` | Use country selector/path: e.g. Apple PH vs US vs JP; Samsung KR vs SG etc. |
| Appliances | `whirlpool.com`, `electrolux.com`, `bosch-home.com`, `haier.com`, `midea.com`, `lg.com`, `samsung.com`, `panasonic.com` | Check local voltage, warranty, service-center pages. |
| Furniture/home | `ikea.com`, `muji.com`, `nitori-net.jp`, `hermanmiller.com`, `steelcase.com`, `koala.com`, `ecosa.com` | IKEA must be country-path specific. |
| Kitchen | `ninjakitchen.com`, `kitchenaid.com`, `zwilling.com`, `tefal.com`, `philips.com`, `zojirushi.com`, `tiger-corporation.com` | Appliances may differ by voltage and plug. |
| Clothing/footwear | `nike.com`, `adidas.com`, `uniqlo.com`, `hm.com`, `zara.com`, `newbalance.com`, `asics.com`, `skechers.com` | Size charts and return rules vary by country. |
| Beauty/personal care | `sephora.com`, `ulta.com`, `watsons.com`, `oliveyoung.co.kr`, `lorealparisusa.com`, `nivea.com`, `theordinary.com`, `laroche-posay.com` | Ingredient formulas and sunscreen approvals can differ by region. |
| Baby | `gracobaby.com`, `chiccousa.com`, `maxi-cosi.com`, `cybex-online.com`, `philips.com`, `pigeon.com` | Safety standards and car-seat legality are region-specific. |
| Sports/outdoor | `decathlon.com`, `thenorthface.com`, `patagonia.com`, `columbia.com`, `salomon.com`, `garmin.com`, `coleman.com` | Local warranty and sizing matter. |
| Tools/home improvement | `makitatools.com`, `dewalt.com`, `boschtools.com`, `stanleytools.com`, `milwaukeetool.com`, `ryobitools.com` | Battery ecosystem, charger voltage, plug type. |
| Cameras | `canon.com`, `nikon.com`, `sony.com`, `fujifilm-x.com`, `om-digitalsolutions.com`, `panasonic.com` | Gray-market camera warranty is a major risk. |
| Office | `staples.com`, `officedepot.com`, `epson.com`, `brother.com`, `canon.com`, `logitech.com` | Printer ink/toner region locks can matter. |
| Toys/games | `lego.com`, `mattel.com`, `hasbro.com`, `nintendo.com`, `playstation.com`, `xbox.com` | Age ratings, plug/adapter, DLC region locks. |
| Pet | `royalcanin.com`, `purina.com`, `hillspet.com`, `kongcompany.com`, `chewy.com` | Pet food formulation and distribution vary by country. |

---

## G. Review/testing domains by category and evidence type

| Domain | Categories | Evidence type | Policy treatment |
|---|---|---|---|
| `consumerreports.org` | Appliances, cars, electronics, baby, home, safety | Independent testing/reviews | Strong performance/safety evidence; may be paywalled. |
| `nytimes.com/wirecutter` | Broad consumer categories | Editorial testing + affiliate buying guides | Medium-high; useful but affiliate model should be disclosed in evidence. |
| `rtings.com` | TVs, monitors, headphones, cameras, vacuums, appliances | Lab-style testing | Strong for measured categories. |
| `reviewed.usatoday.com` | Home, kitchen, appliances, tech | Testing/editorial reviews | Medium-high; use test-method pages where available. |
| `choice.com.au` | Australia/NZ-relevant consumer products, appliances, baby, safety | Independent consumer testing | Strong for AU/NZ safety/performance context. |
| `which.co.uk` | Appliances, home, tech, baby | Independent consumer testing | Strong, but UK-centric for price/warranty. |
| `goodhousekeeping.com` | Kitchen, home, beauty, cleaning, parenting | Editorial testing | Medium; useful supporting source. |
| `outdoorgearlab.com` | Sports/outdoor | Field/lab reviews | Medium-high for outdoor. |
| `babygearlab.com` | Baby products | Testing/reviews | Medium-high for baby gear. |
| `cameralabs.com`, `dpreview.com` | Cameras | Specialist reviews | Strong for camera performance; weaker for local price/stock. |
| `techgearlab.com`, `tomsguide.com`, `cnet.com` | Tech, office, appliances | Editorial reviews | Medium; verify recency and test depth. |
| `makeupalley.com`, `incidecoder.com` | Beauty | User reviews / ingredient reference | Weak-to-medium; not authoritative for safety claims. |

---

## H. Community domains and cautions

| Domain/community | Useful for | Cautions |
|---|---|---|
| `reddit.com` | Real owner experiences, defect patterns, return experiences, sizing, local store complaints | Qualitative only; not specs, price, safety, or warranty authority |
| `forums.redflagdeals.com` | Canada deals and retailer experiences | Deal-focused; verify retailer and model separately |
| `ozbargain.com.au` | Australia pricing/deal history | Deal quality can be good; still verify seller and model |
| `cheapies.nz` | New Zealand deals | Same caution as OzBargain |
| `price.com.hk` forums/listings | HK price/shop discovery | Use only to discover shops/prices; verify seller separately |
| `ptt.cc`, `dcard.tw`, `mobile01.com` | Taiwan user experiences | Strong local qualitative signal; not official specs |
| `dcinside.com`, `clien.net`, Naver cafes | Korea owner discussions | Korean-language community; verify official model/warranty |
| `hardwarezone.com.sg` | Singapore tech/local purchase discussions | Useful local context; not authoritative |
| `pinoydvd.com`, PH Reddit communities | Philippines electronics/home owner discussions | Sparse/subjective; verify retailer and warranty |

Community evidence should be stored as `evidence_type: community_qualitative`, never as `authoritative_spec`, `official_price`, or `safety_certification`.

---

## I. Amazon-specific rules

Amazon must always be listing-specific:

1. Parse and score:
   - `sold_by`
   - `ships_from`
   - `fulfilled_by`
   - condition: new/used/refurbished/renewed
   - return policy
   - seller country/business name
   - brand registry or official store signals
   - review distribution and review hijacking risk

2. Scoring:
   - “Ships from and sold by Amazon” = strongest Amazon purchase evidence.
   - “Sold by brand official store, fulfilled by Amazon” = good, but verify official store identity.
   - “Sold by third-party, fulfilled by Amazon” = medium; FBA is logistics, not authenticity guarantee.
   - “Sold and shipped by unknown third-party” = weak unless seller is verified.
   - Amazon Renewed, Warehouse, Used, Open Box = separate condition-specific path.

3. Do not treat Prime/FBA as a guarantee. Amazon’s own help pages distinguish third-party seller fulfillment/customer-service responsibilities, and public safety cases show that third-party marketplace products can still create product-safety issues.

---

## J. IKEA-specific rules

IKEA must be treated as an **official source only for the matching country/region path**.

| Region | IKEA source |
|---|---|
| Philippines | `ikea.com/ph/en` |
| US | `ikea.com/us/en` |
| Korea | `ikea.com/kr/en` |
| Canada | `ikea.com/ca/en` |
| Japan | `ikea.com/jp/en` |
| Singapore | `ikea.com/sg/en` |
| Macao | `ikea.com.hk/en` / Hong Kong & Macau app or site |
| Australia | `ikea.com/au/en` |
| New Zealand | `ikea.com/nz/en` |
| Hong Kong | `ikea.com.hk/en` |
| Taiwan | `ikea.com.tw` |

Reason: IKEA is a global franchise system, and local pages differ for price, stock, delivery, services, returns, and availability.

---

## K. Region-relevance rules

1. **Official specs**
   - Global official page can identify product family.
   - Regional official page is required for price, stock, warranty, delivery, plug, cellular bands, keyboard layout, and included accessories.

2. **Currency/tax**
   - Reject or down-rank listings when currency does not match shopper region unless cross-border shopping is explicitly allowed.
   - Flag “tax not included,” “import fees due,” or unclear GST/VAT/sales-tax status.

3. **Shipping/customs**
   - Require landed cost where possible: item price + shipping + import duties/taxes + brokerage + return shipping.
   - Down-rank listings with unclear origin or long cross-border shipping for regulated/safety-sensitive goods.

4. **Warranty/service**
   - Require local authorized service for electronics, cameras, appliances, baby gear, tools, and expensive items.
   - Gray-market imports should not be recommended as default best purchase even when cheaper.

5. **Electrical**
   - Philippines/Taiwan/Japan/US/Canada often involve 100–120V ecosystems.
   - Korea/Singapore/HK/Macao/Australia/NZ generally 220–240V.
   - Always check plug type and frequency where relevant.

6. **Cellular**
   - Phones/tablets/watches require region band and eSIM/VoLTE support checks.
   - Do not assume an imported model supports local 5G/LTE bands or warranty.

7. **Language/model**
   - Japan/Korea/Taiwan listings may have local keyboards, firmware, labels, manuals, apps, or region locks.
   - Cameras, game consoles, printers, and appliances can differ materially by country model suffix.

---

## L. Suspicious/unknown-store heuristics

Down-rank or mark `requires_manual_review` when any of these appear:

- Price is implausibly low versus official/retailer median.
- Seller name is hidden, generic, recently created, or mismatched with brand.
- No physical address, contact method, return policy, or warranty details.
- Currency/locale mismatch.
- “Ships from overseas” hidden in fine print.
- Product photos or descriptions copied from Amazon/AliExpress/brand page.
- Model number mismatch across title, specs, image, and description.
- Artificial urgency: fake countdown, “only 1 left” repeated, pressure checkout.
- Payment pushed off-platform.
- Excessive five-star reviews with repetitive language.
- Review hijacking: reviews describe a different product.
- Listing says “OEM,” “class A,” “mirror quality,” “parallel import,” “international version,” “for parts,” or “no warranty.”
- Safety-sensitive item lacks certification or local compliance markings.

Unknown sources default to **weak/unknown**, not automatic exclusion. The system should explain what is missing.

---

## M. Ambiguous entries requiring owner approval

| Domain | Why ambiguous | Default MVP action |
|---|---|---|
| `qoo10.sg` | Search/app pages still describe an online marketplace, but other public references suggest business instability/defunct history. | Mark `active_uncertain`; require live check before using. |
| `themarket.com` | Official seller page exists, but NZ retail ecosystem has shifted; confirm current consumer availability. | Mark `active_uncertain`. |
| `catch.com.au` | Marketplace history is clear, but ownership/closure/replatforming status has changed over time. | Mark `active_uncertain`; prefer Amazon AU/eBay/Kmart marketplace unless verified. |
| `wayfair.com` | Retailer with supplier/drop-ship model; not a simple first-party store. | Treat as established retailer but require fulfillment/return checks. |
| `zalora.*` | Fashion platform with brand/marketplace behavior varying by country. | Treat as established fashion marketplace; listing checks. |
| `kakaku.com` | Price-comparison/shop aggregator, not retailer. | Use for price discovery only; actual shop must be scored. |
| `price.com.hk` | Price-comparison/shop directory. | Use for discovery only; actual shop must be scored. |
| `taobao.com`, `tmall.com` outside Mainland China | Can be legitimate but cross-border for HK/Macao/Taiwan/SG shoppers. | Weak purchase evidence unless shopper explicitly accepts cross-border. |
| `mightyape.co.nz` | Known NZ retailer; may include marketplace/third-party style offers depending listing. | Treat as established, listing-check required until confirmed. |

---

## N. Machine-friendly JSON seed

```json
{
  "version": "cartcart_source_quality_seed_mvp_2026-06-13",
  "normalization": {
    "domain_format": "lowercase_no_protocol_no_www",
    "affiliate_policy": "strip_tracking_parameters; keep neutral canonical links only",
    "unknown_default": "weak_unknown_with_reason_not_auto_excluded"
  },
  "scoring_policy": {
    "official_manufacturer": {
      "baseline_score": 0.95,
      "strong_for": ["specifications", "product_identity", "compatibility", "brand_warranty_terms"],
      "weak_for": ["price", "stock", "shipping", "local_warranty_if_wrong_region"]
    },
    "established_retailer_first_party": {
      "baseline_score": 0.8,
      "requires_listing_checks": false,
      "strong_for": ["purchase_availability", "regional_price", "returns"]
    },
    "established_retailer_mixed": {
      "baseline_score": 0.65,
      "requires_listing_checks": true,
      "strong_for": ["purchase_discovery"],
      "caution": "domain reputation does not transfer automatically to third-party sellers"
    },
    "open_marketplace": {
      "baseline_score": 0.45,
      "requires_listing_checks": true,
      "strong_for": ["price_discovery", "availability_discovery"],
      "weak_for": ["authenticity", "warranty", "safety"]
    },
    "reseller_import_proxy": {
      "baseline_score": 0.2,
      "default_action": "exclude_as_purchase_evidence_unless_user_requests_proxy_or_used_import"
    },
    "review_testing": {
      "baseline_score": 0.75,
      "strong_for": ["performance", "durability", "comparative_quality"],
      "weak_for": ["current_price", "local_stock", "local_warranty"]
    },
    "community": {
      "baseline_score": 0.3,
      "strong_for": ["owner_experience", "defect_patterns", "local_context"],
      "weak_for": ["official_specs", "price", "stock", "safety", "warranty"]
    }
  },
  "regions": {
    "philippines": {
      "currency": "PHP",
      "retailers": [
        {
          "domain": "abenson.com",
          "source_class": "established_retailer_first_party",
          "categories": ["electronics", "appliances", "furniture"],
          "marketplace_status": "first_party_retail",
          "requires_trust_assessment": false,
          "rationale": "Established Philippine appliance and electronics retailer.",
          "source_url": "https://www.abenson.com/"
        },
        {
          "domain": "ansons.ph",
          "source_class": "established_retailer_first_party",
          "categories": ["electronics", "appliances"],
          "marketplace_status": "first_party_retail",
          "requires_trust_assessment": false,
          "rationale": "Established Philippine appliance and electronics retailer.",
          "source_url": "https://ansons.ph/"
        },
        {
          "domain": "smstore.com",
          "source_class": "established_retailer_first_party",
          "categories": ["department_store", "clothing", "beauty", "home", "toys"],
          "marketplace_status": "first_party_or_curated_retail_verify_listing",
          "requires_trust_assessment": true,
          "rationale": "Major Philippine department-store retailer; verify seller/fulfillment for online listings.",
          "source_url": "https://www.smstore.com/"
        },
        {
          "domain": "wilcon.com.ph",
          "source_class": "established_retailer_first_party",
          "categories": ["tools", "home_improvement", "bath", "building_materials"],
          "marketplace_status": "first_party_retail",
          "requires_trust_assessment": false,
          "rationale": "Philippine home improvement retailer.",
          "source_url": "https://www.wilcon.com.ph/"
        },
        {
          "domain": "ikea.com/ph/en",
          "source_class": "official_store_regional",
          "categories": ["furniture", "home_goods", "kitchen"],
          "marketplace_status": "official_regional_store",
          "requires_trust_assessment": false,
          "rationale": "Official IKEA Philippines regional store; authoritative for PH IKEA price/stock only.",
          "source_url": "https://www.ikea.com/ph/en/"
        },
        {
          "domain": "shopee.ph",
          "source_class": "open_marketplace",
          "categories": ["general"],
          "marketplace_status": "mixed_marketplace",
          "requires_trust_assessment": true,
          "rationale": "Marketplace with many sellers; official/Mall badges improve but do not guarantee trust.",
          "source_url": "https://shopee.ph/"
        },
        {
          "domain": "lazada.com.ph",
          "source_class": "open_marketplace",
          "categories": ["general"],
          "marketplace_status": "mixed_marketplace",
          "requires_trust_assessment": true,
          "rationale": "Marketplace; LazMall requires brand relationship documentation but listings still need checks.",
          "source_url": "https://www.lazada.com.ph/"
        }
      ]
    },
    "united_states": {
      "currency": "USD",
      "retailers": [
        {
          "domain": "target.com",
          "source_class": "established_retailer_mixed",
          "categories": ["general", "home", "baby", "toys", "clothing", "beauty"],
          "marketplace_status": "both_first_party_and_target_plus_marketplace",
          "requires_trust_assessment": true,
          "rationale": "Target Plus is an invite-only third-party marketplace; first-party Target listings remain stronger.",
          "source_url": "https://plus.target.com/"
        },
        {
          "domain": "walmart.com",
          "source_class": "established_retailer_mixed",
          "categories": ["general", "grocery", "home", "electronics", "toys"],
          "marketplace_status": "both_first_party_and_marketplace",
          "requires_trust_assessment": true,
          "rationale": "Walmart Marketplace and Pro Seller program exist; badges are not product guarantees.",
          "source_url": "https://marketplace.walmart.com/pro-seller/"
        },
        {
          "domain": "amazon.com",
          "source_class": "open_marketplace",
          "categories": ["general"],
          "marketplace_status": "both_first_party_and_marketplace",
          "requires_trust_assessment": true,
          "rationale": "Amazon third-party sellers require sold-by/ships-from/FBA/return checks.",
          "source_url": "https://www.amazon.com/gp/help/customer/display.html?nodeId=GEF528GN65XSJ7V8"
        }
      ]
    }
  },
  "note": "This JSON seed is intentionally compact for MVP. Expand region retailer arrays using the Markdown tables above when implementing the full seed."
}
```

---

## Implementation notes

- Treat this as an initial policy seed, not a permanent whitelist.
- Revalidate domains periodically.
- Add automated link checks.
- Add per-category source expansion only after the scoring rules are implemented.
- Keep source classification and offer/listing assessment separate.
- Preserve audit fields: `source_url`, `rationale`, `last_checked`, `region`, `source_class`, `marketplace_status`, and `requires_trust_assessment`.
