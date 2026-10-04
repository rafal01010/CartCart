import { describe, expect, it } from 'vitest';
import type { SessionResultsResponse } from '$lib/api/types.js';
import { buildResultView, neutralOutboundUrl, selectModeView } from './result-view.js';

const comparisonMatrix: SessionResultsResponse['comparison_matrix'] = {
	schema_version: 1,
	criteria: [{ name: 'fit', weight: 1, higher_is_better: true }],
	rows: [
		{ product_id: 'product-dell', listing_id: 'listing-dell', scores: { fit: 0.9 }, evidence_ids: ['evidence-dell'], summary: 'Strong fit.' },
		{ product_id: 'product-asus', listing_id: 'listing-asus', scores: { fit: 0.8 }, evidence_ids: ['evidence-asus'], summary: 'Lower price with credible evidence.' },
		{ product_id: 'product-lg', listing_id: 'listing-lg', scores: { fit: 0.75 }, evidence_ids: ['evidence-lg'], summary: 'More resolution for a higher price.' },
	],
};

const baseResult: SessionResultsResponse = {
	result_version: {
		result_version_id: 'result-version-1',
		run_id: 'run-1',
		version: 2,
		recommendation_bundle_id: 'bundle-1',
		comparison_matrix_id: 'matrix-1',
		refinement_id: null,
		prior_result_version_id: null,
		requested_result_mode: null,
	},
	trust_assessments: [
		{
			schema_version: 1,
			listing_id: 'listing-dell',
			level: 'reasonable',
			confidence: { level: 'high', score: 0.82 },
			summary: 'Official seller listing has clear warranty support.',
			red_flags: [],
			positive_signals: ['Official seller'],
			evidence_ids: ['evidence-dell'],
			source_ids: ['source-dell'],
			assessed_at: '2026-05-31T00:00:00Z',
		},
	],
	category_analyses: [],
	agent_records: [],
	comparison_matrix: comparisonMatrix,
	recommendation_bundle: {
		schema_version: 1,
		bundle_id: 'bundle-1',
		final_product_id: 'product-dell',
		final_listing_id: 'listing-dell',
		no_strong_buy: false,
		final_rationale: 'Best balance of fit and seller trust.',
		runner_up_product_ids: ['product-asus'],
		mode_results: [
			{
				mode: 'best_overall',
				product_id: 'product-dell',
				listing_id: 'listing-dell',
				title: 'Best overall',
				rationale: 'Best blend of features and seller safety.',
				confidence: { level: 'high', score: 0.84 },
				evidence_ids: ['evidence-dell'],
				source_ids: ['source-dell'],
			},
			{
				mode: 'best_value',
				product_id: 'product-asus',
				listing_id: 'listing-asus',
				title: 'Best value',
				rationale: 'Lower price with credible evidence.',
				confidence: { level: 'medium', score: 0.72 },
				evidence_ids: ['evidence-asus'],
				source_ids: ['source-asus'],
			},
			{
				mode: 'within_budget',
				product_id: 'product-asus',
				listing_id: 'listing-asus',
				title: 'Best within budget',
				rationale: 'Stays inside the stated budget with credible evidence.',
				confidence: { level: 'medium', score: 0.72 },
				evidence_ids: ['evidence-asus'],
				source_ids: ['source-asus'],
			},
			{
				mode: 'stretch_pick',
				product_id: 'product-lg',
				listing_id: 'listing-lg',
				title: 'Stretch upgrade',
				rationale: 'Costs more, so it only works if the budget tradeoff is acceptable.',
				confidence: { level: 'medium', score: 0.7 },
				evidence_ids: ['evidence-lg'],
				source_ids: ['source-lg'],
			},
		],
		comparison_matrix: comparisonMatrix,
		rejected_items: [],
		warnings: [],
		evidence_ids: ['evidence-dell', 'evidence-asus', 'evidence-lg'],
		source_ids: ['source-dell', 'source-asus', 'source-lg'],
	},
	products: [
		{
			schema_version: 1,
			product_id: 'product-dell',
			name: 'Dell UltraSharp U2724DE',
			brand: 'Dell',
			model: 'U2724DE',
			category: 'monitor',
			source_ids: ['source-dell'],
			listing_ids: ['listing-dell'],
		},
		{
			schema_version: 1,
			product_id: 'product-asus',
			name: 'ASUS ProArt PA278CV',
			brand: 'ASUS',
			model: 'PA278CV',
			category: 'monitor',
			source_ids: ['source-asus'],
			listing_ids: ['listing-asus'],
		},
		{
			schema_version: 1,
			product_id: 'product-lg',
			name: 'LG 27UP850',
			brand: 'LG',
			model: '27UP850',
			category: 'monitor',
			source_ids: ['source-lg'],
			listing_ids: ['listing-lg'],
		},
	],
	listings: [
		listing('listing-dell', 'product-dell', 'Dell UltraSharp U2724DE — Official', 'Dell Official', 499, 'source-dell'),
		listing('listing-asus', 'product-asus', 'ASUS ProArt PA278CV', 'ASUS Store', 349, 'source-asus'),
		listing('listing-lg', 'product-lg', 'LG 27UP850', 'LG Store', 579, 'source-lg'),
	],
	shortlist: [
		{ candidate_id: 'candidate-dell', product_id: 'product-dell', listing_id: 'listing-dell', position: 1 },
		{ candidate_id: 'candidate-asus', product_id: 'product-asus', listing_id: 'listing-asus', position: 2 },
	],
	considered_products: [],
	source_snapshots: [
		{
			schema_version: 1,
			source_id: 'source-dell',
			url: 'https://example.test/dell',
			source_type: 'official_brand_page',
			provider: { provider_name: 'fixture' },
			title: 'Dell source',
			extraction_status: 'succeeded',
			quality: { level: 'strong', score: 0.9 },
			captured_at: '2026-05-31T00:00:00Z',
		},
		{
			schema_version: 1,
			source_id: 'source-asus',
			url: 'https://example.test/asus',
			source_type: 'retailer_listing',
			provider: { provider_name: 'fixture' },
			title: 'ASUS source',
			extraction_status: 'succeeded',
			quality: { level: 'adequate', score: 0.75 },
			captured_at: '2026-05-31T00:00:00Z',
		},
		{
			schema_version: 1,
			source_id: 'source-lg',
			url: 'https://example.test/lg',
			source_type: 'retailer_listing',
			provider: { provider_name: 'fixture' },
			title: 'LG source',
			extraction_status: 'succeeded',
			quality: { level: 'adequate', score: 0.73 },
			captured_at: '2026-05-31T00:00:00Z',
		},
	],
	source_evidence: [
		{
			evidence_id: 'evidence-dell',
			source_id: 'source-dell',
			target: { target_type: 'product', product_id: 'product-dell' },
			evidence_type: 'product_spec',
			claim: 'Dell has USB-C support.',
			confidence: { level: 'high', score: 0.86 },
			source_quality: { level: 'strong', score: 0.9 },
		},
		{
			evidence_id: 'evidence-asus',
			source_id: 'source-asus',
			target: { target_type: 'product', product_id: 'product-asus' },
			evidence_type: 'review_claim',
			claim: 'ASUS is a credible value pick.',
			confidence: { level: 'medium', score: 0.72 },
			source_quality: { level: 'adequate', score: 0.75 },
		},
		{
			evidence_id: 'evidence-lg',
			source_id: 'source-lg',
			target: { target_type: 'product', product_id: 'product-lg' },
			evidence_type: 'review_claim',
			claim: 'LG is a credible stretch pick.',
			confidence: { level: 'medium', score: 0.7 },
			source_quality: { level: 'adequate', score: 0.73 },
		},
	],
};

function listing(
	listingId: string,
	productId: string,
	title: string,
	sellerName: string,
	price: number,
	sourceId: string,
) {
	return {
		schema_version: 1,
		listing_id: listingId,
		product_id: productId,
		title,
		url: `https://example.test/${listingId}`,
		canonical_url: `https://example.test/${listingId}`,
		seller: {
			seller_name: sellerName,
			trust_signal: 'reasonable' as const,
			source_ids: [sourceId],
		},
		price: { amount: price, currency: 'USD' },
		region_availability: [],
		source_quality: { level: 'strong', score: 0.9 },
		source_ids: [sourceId],
		captured_at: '2026-05-31T00:00:00Z',
	};
}

describe('result view helpers', () => {
	it('renders the authoritative final decision without optional mode records', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: { ...baseResult.recommendation_bundle, mode_results: [] },
		});
		expect(view.finalMode).toMatchObject({
			productId: 'product-dell', listingId: 'listing-dell',
			productName: 'Dell UltraSharp U2724DE', sellerName: 'Dell Official',
			priceLabel: '$499', purchaseUrl: 'https://example.test/listing-dell',
			rationale: 'Best balance of fit and seller trust.',
		});
		expect(view.finalMode?.listingTrust?.levelLabel).toBe('Reasonable listing');
		expect(view.finalMode?.evidence.map((item) => item.id)).toContain('evidence-dell');
		expect(view.finalMode?.sources.map((item) => item.id)).toContain('source-dell');
		expect(selectModeView(view, null)).toBe(view.finalMode);
		expect(view.decisionModes).toEqual([view.finalMode]);
	});

	it('keeps the final pick selectable when only alternate modes are saved', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				mode_results: baseResult.recommendation_bundle.mode_results.slice(1),
			},
		});
		expect(selectModeView(view, null)?.productId).toBe('product-dell');
		expect(view.decisionModes.map((item) => item.mode)).toEqual([
			'best_overall', 'best_value', 'within_budget', 'stretch_pick',
		]);
		const alternate = view.decisionModes.find((item) => item.mode === 'best_value');
		expect(selectModeView(view, alternate?.key ?? null)?.productId).toBe('product-asus');
		expect(selectModeView(view, view.finalMode?.key ?? null)?.productId).toBe('product-dell');
		expect(view.finalMode?.rationale).toBe('Best balance of fit and seller trust.');
	});

	it('uses the final listing identity even when best-overall names another listing', () => {
		const view = buildResultView({
			...baseResult,
			listings: [...baseResult.listings, listing('listing-dell-other', 'product-dell', 'Dell from another seller', 'Other seller', 399, 'source-dell')],
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				mode_results: [{ ...baseResult.recommendation_bundle.mode_results[0], listing_id: 'listing-dell-other' }],
			},
		});
		expect(view.finalMode).toMatchObject({ listingId: 'listing-dell', sellerName: 'Dell Official', priceLabel: '$499' });
		expect(selectModeView(view, null)?.purchaseUrl).toBe('https://example.test/listing-dell');
	});

	it('keeps a product-only final pick when a saved mode has a listing', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: { ...baseResult.recommendation_bundle, final_listing_id: null },
		});
		expect(view.finalMode).toMatchObject({
			productId: 'product-dell', listingId: null, listingTitle: null,
			sellerName: null, priceLabel: null, purchaseUrl: null, listingTrust: null,
		});
	});

	it('resolves saved runner-ups through comparison and analysis without mode duplicates', () => {
		const view = buildResultView({
			...baseResult,
			comparison_matrix: {
				...baseResult.comparison_matrix,
				rows: [...baseResult.comparison_matrix.rows.filter((row) => row.product_id !== 'product-asus' && row.product_id !== 'product-lg'), {
					product_id: 'product-asus', listing_id: 'listing-asus', scores: { fit: 0.8 },
					summary: 'Lower price with a checked fit.', evidence_ids: ['evidence-asus'],
				}],
			},
			category_analyses: [{
				schema_version: 1, product_id: 'product-lg', listing_ids: ['listing-lg'], category: 'monitor',
				fit_summary: 'Extra resolution for a higher price.', strengths: [], weaknesses: [], warnings: [],
				confidence: { level: 'medium', score: 0.7 }, evidence_ids: ['evidence-lg'], source_ids: ['source-lg'],
			}],
			recommendation_bundle: {
				...baseResult.recommendation_bundle, mode_results: [],
				runner_up_product_ids: ['product-asus', 'product-lg'],
			},
		});
		expect(view.runnerUps.map((item) => item.productName)).toEqual(['ASUS ProArt PA278CV', 'LG 27UP850']);
		expect(view.runnerUps[0]).toMatchObject({
			listingId: 'listing-asus', priceLabel: '$349', rationale: 'Lower price with a checked fit.',
		});
		expect(view.runnerUps[0]?.evidence.map((item) => item.id)).toEqual(['evidence-asus']);
		expect(view.runnerUps[0]?.sources.map((item) => item.id)).toEqual(['source-asus']);
		expect(view.runnerUps[1]).toMatchObject({
			listingId: null, purchaseUrl: null, rationale: 'Extra resolution for a higher price.', confidence: 'medium 70%',
		});
		expect(view.runnerUps[1]?.evidence.map((item) => item.id)).toEqual(['evidence-lg']);
	});

	it('does not invent runner-up details or borrow unrelated evidence', () => {
		const view = buildResultView({
			...baseResult,
			shortlist: [], comparison_matrix: { ...baseResult.comparison_matrix, rows: [] },
			recommendation_bundle: {
				...baseResult.recommendation_bundle, mode_results: [],
				runner_up_product_ids: ['product-asus', 'product-asus', 'missing-product'],
			},
		});
		expect(view.runnerUps).toHaveLength(1);
		expect(view.runnerUps[0]).toMatchObject({
			productName: 'ASUS ProArt PA278CV', listingId: null, sellerName: null,
			priceLabel: null, purchaseUrl: null, listingTrust: null, confidence: 'unknown',
			rationale: '',
		});
		expect(view.runnerUps[0]?.rationale).not.toContain('Lower price');
		expect(view.runnerUps[0]?.evidence).toEqual([]);
		expect(view.runnerUps[0]?.sources.map((item) => item.id)).not.toContain('source-dell');
	});

	it('keeps no-strong-buy unselectable even with saved alternate modes', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle, no_strong_buy: true,
				no_strong_buy_reason: 'The listings need more checks.', final_product_id: null, final_listing_id: null,
			},
		});
		expect(view.finalMode).toBeNull();
		expect(selectModeView(view, null)).toBeNull();
		expect(selectModeView(view, view.decisionModes[0]?.key ?? null)).toBeNull();
	});

	it('does not replace an unavailable final reference with a best-overall mode', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: { ...baseResult.recommendation_bundle, final_product_id: null, final_listing_id: null },
		});
		expect(view.finalMode).toBeNull();
		expect(selectModeView(view, null)).toBeNull();
	});

	it('uses final rationale even when the exact best-overall mode has different reasoning', () => {
		const view = buildResultView(baseResult);
		expect(view.finalMode?.rationale).toBe('Best balance of fit and seller trust.');
		expect(view.decisionModes[0]?.rationale).toBe('Best balance of fit and seller trust.');
	});

	it('preserves stored runner-up trust and neutral links without a mode', () => {
		const view = buildResultView({
			...baseResult,
			listings: baseResult.listings.map((item) => item.listing_id === 'listing-asus'
				? { ...item, canonical_url: 'https://example.test/asus?tag=affiliate&utm_source=test&color=black' } : item),
			trust_assessments: [...baseResult.trust_assessments, {
				...baseResult.trust_assessments[0], listing_id: 'listing-asus', level: 'suspicious',
				summary: 'Seller details do not line up.', evidence_ids: ['evidence-asus'], source_ids: ['source-asus'],
			}],
			comparison_matrix: { ...baseResult.comparison_matrix, rows: [{
				product_id: 'product-asus', listing_id: 'listing-asus', scores: { fit: 0.8 },
				summary: 'The product fits, but seller checks block this listing.', evidence_ids: ['evidence-asus'],
			}] },
			recommendation_bundle: { ...baseResult.recommendation_bundle, mode_results: [] },
		});
		expect(view.runnerUps[0]?.purchaseUrl).toBe('https://example.test/asus?color=black');
		expect(view.runnerUps[0]?.listingTrust).toMatchObject({ isBlocking: true, summary: 'Seller details do not line up.' });
		expect(view.runnerUps[0]?.listingTrust?.sources[0]?.id).toBe('source-asus');
		expect(view.runnerUps[0]?.confidence).toBe('unknown');
	});

	it('shows missing final details honestly when no saved mode or analysis explains them', () => {
		const view = buildResultView({
			...baseResult, listings: [], trust_assessments: [], source_snapshots: [], source_evidence: [],
			comparison_matrix: { ...baseResult.comparison_matrix, rows: [] },
			recommendation_bundle: {
				...baseResult.recommendation_bundle, mode_results: [], final_rationale: null,
				evidence_ids: [], source_ids: [],
			},
		});
		expect(view.finalMode).toMatchObject({
			productId: 'product-dell', listingId: 'listing-dell', productName: 'Dell UltraSharp U2724DE',
			priceLabel: null, sellerName: null, purchaseUrl: null, listingTrust: null,
			rationale: '', confidence: 'unknown', evidence: [], sources: [],
		});
	});

	it('does not choose an arbitrary runner-up listing when saved offers are ambiguous', () => {
		const view = buildResultView({
			...baseResult,
			listings: [...baseResult.listings, listing('listing-asus-other', 'product-asus', 'ASUS from another seller', 'Other seller', 299, 'source-asus')],
			shortlist: [
				{ candidate_id: 'asus-a', product_id: 'product-asus', listing_id: 'listing-asus', position: 2 },
				{ candidate_id: 'asus-b', product_id: 'product-asus', listing_id: 'listing-asus-other', position: 3 },
			],
			comparison_matrix: { ...baseResult.comparison_matrix, rows: [
				{ product_id: 'product-asus', listing_id: 'listing-asus', scores: {}, summary: 'First offer.', evidence_ids: ['evidence-asus'] },
				{ product_id: 'product-asus', listing_id: 'listing-asus-other', scores: {}, summary: 'Second offer.', evidence_ids: [] },
			] },
			recommendation_bundle: { ...baseResult.recommendation_bundle, mode_results: [] },
		});
		expect(view.runnerUps[0]).toMatchObject({
			productId: 'product-asus', listingId: null, sellerName: null, priceLabel: null, purchaseUrl: null, rationale: '',
		});
		expect(view.runnerUps[0]?.evidence.map((item) => item.id)).toEqual(['evidence-asus']);
	});

	it('preserves distinct explicit saved offers for the same runner-up product', () => {
		const view = buildResultView({
			...baseResult,
			listings: [...baseResult.listings, listing('listing-asus-other', 'product-asus', 'ASUS from another seller', 'Other seller', 299, 'source-asus-other')],
			source_snapshots: [...baseResult.source_snapshots, {
				...baseResult.source_snapshots[1], source_id: 'source-asus-other', title: 'Other ASUS offer', url: 'https://example.test/asus-other',
			}],
			source_evidence: [...baseResult.source_evidence, {
				...baseResult.source_evidence[1], evidence_id: 'evidence-asus-other', source_id: 'source-asus-other',
				target: { target_type: 'listing', product_id: 'product-asus', listing_id: 'listing-asus-other' }, claim: 'The other ASUS offer has a different price.',
			}],
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				mode_results: [...baseResult.recommendation_bundle.mode_results, {
					mode: 'runner_up', product_id: 'product-asus', listing_id: 'listing-asus-other', title: 'Runner-up',
					rationale: 'Another saved offer for the same product.', confidence: { level: 'medium', score: 0.7 },
					evidence_ids: ['evidence-asus-other'], source_ids: ['source-asus-other'],
				}],
			},
		});
		expect(view.runnerUps.map((item) => item.listingId)).toEqual(['listing-asus', 'listing-asus-other']);
		expect(view.runnerUps.map((item) => item.evidence.map((evidence) => evidence.id))).toEqual([
			['evidence-asus'], ['evidence-asus-other'],
		]);
		expect(view.runnerUps.map((item) => item.sources.map((source) => source.id))).toEqual([
			['source-asus'], ['source-asus-other'],
		]);
	});

	it('keeps a product-only runner comparison even when its shortlist has a listing', () => {
		const view = buildResultView({
			...baseResult,
			comparison_matrix: { ...baseResult.comparison_matrix, rows: [{
				product_id: 'product-asus', listing_id: null, scores: {},
				summary: 'Only the product was compared.', evidence_ids: ['evidence-asus'],
			}] },
			recommendation_bundle: { ...baseResult.recommendation_bundle, mode_results: [] },
		});
		expect(view.runnerUps[0]).toMatchObject({
			productId: 'product-asus', listingId: null, sellerName: null, priceLabel: null, purchaseUrl: null,
			rationale: 'Only the product was compared.',
		});
	});
	it('uses saved candidate links and comparison evidence without inventing manual facts or scores', () => {
		const manualProduct = {
			schema_version: 1, product_id: 'manual-product', name: 'Local Kettle', source_ids: [], listing_ids: [],
		};
		const result: SessionResultsResponse = {
			...baseResult,
			products: [...baseResult.products, manualProduct],
			shortlist: [...baseResult.shortlist, { candidate_id: 'manual-candidate', product_id: 'manual-product', listing_id: null, position: 3 }],
			comparison_matrix: {
				criteria: [{ name: 'fit', higher_is_better: true }],
				rows: [
					{ product_id: 'product-dell', listing_id: 'listing-dell', scores: { fit: 0.9 }, evidence_ids: ['evidence-dell'], summary: 'Strong fit.' },
					{ product_id: 'manual-product', listing_id: null, scores: {}, evidence_ids: [], summary: 'Details need checking.' },
				],
				schema_version: 1,
			},
			considered_products: [
				{
					candidate: { schema_version: 1, candidate_id: 'asked-dell', input_text: 'The Dell monitor', product: baseResult.products[0], listing: baseResult.listings[0], research_attempted: true, created_at: '2026-05-31T00:00:00Z' },
					status: 'confirmed', exclusion_reason: null,
				},
				{
					candidate: { schema_version: 1, candidate_id: 'asked-ambiguous', input_text: 'A ProArt monitor', possible_product_ids: ['product-dell', 'product-asus'], research_attempted: true, created_at: '2026-05-31T00:00:00Z' },
					status: 'possible', exclusion_reason: null,
				},
				{
					candidate: { schema_version: 1, candidate_id: 'asked-missing', input_text: 'Unknown model', research_attempted: true, created_at: '2026-05-31T00:00:00Z' },
					status: 'unresolved', exclusion_reason: null,
				},
				{
					candidate: { schema_version: 1, candidate_id: 'manual-candidate', input_text: 'Local Kettle', product: manualProduct, manual_fallback_reason: 'retrieval_insufficient', manual_details: { seller: 'Corner shop' }, research_attempted: true, created_at: '2026-05-31T00:00:00Z' },
					status: 'manual', exclusion_reason: null,
				},
			],
		};
		const view = buildResultView(result);
		expect(view.consideredProducts.map((item) => item.status)).toEqual(['confirmed', 'possible', 'unresolved', 'manual']);
		expect(view.consideredProducts[0].matchedName).toBe('Dell UltraSharp U2724DE');
		expect(view.consideredProducts[1].possibleNames).toHaveLength(2);
		expect(view.consideredProducts[2].matchedName).toBeNull();
		expect(view.consideredProducts[3]).toMatchObject({ manualSeller: 'Corner shop', manualPrice: null });
		expect(view.comparisonProducts.find((item) => item.productId === 'product-dell')?.criteria[0].value).toBe('90%');
		expect(view.comparisonProducts.find((item) => item.productId === 'manual-product')).toMatchObject({
			manual: true, seller: null, price: null, listingId: null, criteria: [{ name: 'fit', value: 'Unknown' }],
		});
	});
	it('derives final pick, runner-ups, and source references from one stored result', () => {
		const view = buildResultView(baseResult);

		expect(view.finalMode?.label).toBe('Best overall');
		expect(view.whyItWins).toBe('Best balance of fit and seller trust.');
		expect(view.runnerUps).toHaveLength(1);
		expect(view.runnerUps[0]?.label).toBe('Best value');
		expect(view.finalMode?.sources[0]?.url).toBe('https://example.test/dell');
		expect(view.finalMode?.evidence[0]?.claim).toBe('Dell has USB-C support.');
		expect(view.finalMode?.evidence[0]?.typeLabel).toBe('Product Spec');
		expect(view.finalMode?.evidence[0]?.targetLabel).toBe('Product detail');
		expect(view.finalMode?.listingTrust?.levelLabel).toBe('Reasonable listing');
		expect(view.finalMode?.productName).toBe('Dell UltraSharp U2724DE');
		expect(view.finalMode?.sellerName).toBe('Dell Official');
		expect(view.finalMode?.priceLabel).toBe('$499');
		expect(view.finalMode?.purchaseUrl).toBe('https://example.test/listing-dell');
	});

	it('switches recommendation modes locally while preserving best-overall reasoning', () => {
		const view = buildResultView(baseResult);
		const stretchMode = view.decisionModes.find((mode) => mode.mode === 'stretch_pick');
		const selectedMode = selectModeView(view, stretchMode?.key ?? null);

		expect(view.decisionModes.map((mode) => mode.mode)).toEqual([
			'best_overall',
			'best_value',
			'within_budget',
			'stretch_pick',
		]);
		expect(selectedMode?.mode).toBe('stretch_pick');
		expect(selectedMode?.label).toBe('Stretch upgrade');
		expect(selectedMode?.productName).toBe('LG 27UP850');
		expect(view.finalMode?.mode).toBe('best_overall');
		expect(view.whyItWins).toBe('Best balance of fit and seller trust.');
	});

	it('surfaces weak, conflicting, and partial evidence states without changing the decision', () => {
		const view = buildResultView({
			...baseResult,
			source_snapshots: baseResult.source_snapshots.map((source, index) =>
				index === 0 ? { ...source, extraction_status: 'partial' } : source,
			),
			source_evidence: baseResult.source_evidence.map((evidence, index) =>
				index === 0
					? {
							...evidence,
							claim: 'Sources conflict on USB-C charging power.',
							confidence: { level: 'low', score: 0.4 },
						}
					: evidence,
			),
		});

		expect(view.finalMode?.productName).toBe('Dell UltraSharp U2724DE');
		expect(view.hasWeakEvidence).toBe(true);
		expect(view.hasConflictingEvidence).toBe(true);
		expect(view.hasPartialSources).toBe(true);
	});

	it('attaches listing safety to modes separately from product fit', () => {
		const view = buildResultView({
			...baseResult,
			trust_assessments: [
				...baseResult.trust_assessments,
				{
					schema_version: 1,
					listing_id: 'listing-asus',
					level: 'suspicious',
					confidence: { level: 'medium', score: 0.66 },
					summary: 'The product may fit, but this marketplace listing has risky seller signals.',
					red_flags: ['Seller details do not line up.'],
					positive_signals: [],
					evidence_ids: ['evidence-asus'],
					source_ids: ['source-asus'],
					assessed_at: '2026-05-31T00:00:00Z',
				},
			],
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				warnings: [
					'Blocked a suspicious listing: The product may still be worth considering from a safer seller.',
				],
			},
		});

		expect(view.runnerUps[0]?.label).toBe('Best value');
		expect(view.runnerUps[0]?.listingTrust?.isBlocking).toBe(true);
		expect(view.runnerUps[0]?.listingTrust?.summary).toContain('product may fit');
		expect(view.warnings.map((warning) => warning.text)).toContain(
			'Seller details do not line up.',
		);
		expect(view.warnings.some((warning) => warning.text.includes('safer seller'))).toBe(true);
		expect(
			view.warnings.find((warning) => warning.text === 'Seller details do not line up.')?.evidence[0]
				?.id,
		).toBe('evidence-asus');
	});

	it('does not expose a best-pick card for no-strong-buy results', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				final_product_id: null,
				final_listing_id: null,
				no_strong_buy: true,
				no_strong_buy_reason: 'The best-matching listing is blocked by seller checks.',
				final_rationale: null,
			},
		});

		expect(view.finalMode).toBeNull();
		expect(view.noStrongBuyReason).toBe('The best-matching listing is blocked by seller checks.');
	});

	it('omits rejected items when a good-candidate fixture has no meaningful negative reason', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				rejected_items: [
					{
						reason_code: 'weak_evidence',
						reason: '   ',
						severity: 'low',
						evidence_ids: [],
						source_ids: [],
					},
				],
			},
		});

		expect(view.rejectedItems).toHaveLength(0);
	});

	it('omits low-severity rejected items from the shopper avoid section', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				rejected_items: [
					{
						product_id: 'product-asus',
						listing_id: 'listing-asus',
						reason_code: 'poor_fit',
						reason: 'Not the strongest overall winner.',
						severity: 'low',
						evidence_ids: ['evidence-asus'],
						source_ids: ['source-asus'],
					},
				],
			},
		});

		expect(view.rejectedItems).toHaveLength(0);
	});

	it('keeps meaningful why-not items with inspectable evidence links', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				rejected_items: [
					{
						product_id: 'product-asus',
						listing_id: 'listing-asus',
						reason_code: 'suspicious_listing',
						reason: 'Seller trust is too weak for this listing.',
						severity: 'blocking',
						evidence_ids: ['evidence-asus'],
						source_ids: ['source-asus'],
					},
				],
			},
		});

		expect(view.rejectedItems).toHaveLength(1);
		expect(view.rejectedItems[0]?.reasonLabel).toBe('Risky listing');
		expect(view.rejectedItems[0]?.reason).toContain('Seller trust');
		expect(view.rejectedItems[0]?.sources[0]?.url).toBe('https://example.test/asus');
	});

	it('keeps warning claims traceable to supporting evidence and sources', () => {
		const view = buildResultView({
			...baseResult,
			category_analyses: [
				{
					schema_version: 1,
					product_id: 'product-asus',
					listing_ids: ['listing-asus'],
					category: 'monitor',
					fit_summary: 'Good enough for the price.',
					strengths: [],
					weaknesses: [],
					warnings: ['Availability evidence is weaker for this option.'],
					confidence: { level: 'medium', score: 0.7 },
					evidence_ids: ['evidence-asus'],
					source_ids: [],
				},
			],
		});

		const warning = view.warnings.find((item) => item.text.includes('Availability evidence'));

		expect(warning?.evidence[0]?.claim).toBe('ASUS is a credible value pick.');
		expect(warning?.sources[0]?.id).toBe('source-asus');
	});

	it('neutralizes outbound source links and strips affiliate or tracking parameters', () => {
		const view = buildResultView({
			...baseResult,
			source_snapshots: [
				{
					...baseResult.source_snapshots[0],
					url: 'https://www.amazon.com/dp/B012345678?tag=affiliate-20&utm_source=fixture&color=black#reviews',
				},
				...baseResult.source_snapshots.slice(1),
			],
		});

		expect(view.sourceViews[0]?.url).toBe('https://www.amazon.com/dp/B012345678?color=black');
		expect(view.sourceViews[0]?.displayUrl).toBe('amazon.com');
		expect(view.finalMode?.evidence[0]?.sourceUrl).toBe(
			'https://www.amazon.com/dp/B012345678?color=black',
		);
		expect(neutralOutboundUrl('javascript:alert(1)')).toBeNull();
	});

	it('exposes video timestamps and source metadata for inspection', () => {
		const view = buildResultView({
			...baseResult,
			source_snapshots: [
				{
					...baseResult.source_snapshots[0],
					source_type: 'video',
					video: {
						video_id: 'video-1',
						url: 'https://www.youtube.com/watch?v=video-1&utm_campaign=tracking',
						title: 'Dell monitor review',
						channel_name: 'Helpful Reviews',
						transcript_availability: 'available',
						affiliate_links_disclosed: true,
						affiliate_bias_risk: { level: 'medium', score: 0.62 },
					},
				},
				...baseResult.source_snapshots.slice(1),
			],
			source_evidence: [
				{
					...baseResult.source_evidence[0],
					evidence_type: 'video_claim',
					timestamp_references: [{ start_seconds: 75, end_seconds: 91 }],
					video: {
						video_id: 'video-1',
						url: 'https://www.youtube.com/watch?v=video-1&utm_campaign=tracking',
						title: 'Dell monitor review',
						channel_name: 'Helpful Reviews',
						transcript_availability: 'available',
						affiliate_links_disclosed: true,
						affiliate_bias_risk: { level: 'medium', score: 0.62 },
					},
				},
				...baseResult.source_evidence.slice(1),
			],
		});

		expect(view.finalMode?.evidence[0]?.timestampLabels).toEqual(['1:15-1:31']);
		expect(view.finalMode?.evidence[0]?.metadata).toContain('Transcript: Available');
		expect(view.finalMode?.evidence[0]?.metadata).toContain('Channel: Helpful Reviews');
		expect(view.finalMode?.evidence[0]?.metadata).toContain('Affiliate links disclosed by source');
		expect(view.sourceViews[0]?.typeLabel).toBe('Video');
	});

	it('scrubs fixture-only wording from shopper-facing result text', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				final_rationale: 'Fixture best pick because the official listing is safer.',
				warnings: ['Avoid this fixture seller.'],
				mode_results: [
					{
						...baseResult.recommendation_bundle.mode_results[0],
						title: 'Fixture best overall',
						rationale: 'Fixture rationale.',
					},
				],
			},
		});

		expect(view.whyItWins).toBe('best pick because the official listing is safer.');
		expect(view.finalMode?.label).toBe('best overall');
		expect(view.finalMode?.rationale).toBe('best pick because the official listing is safer.');
		expect(view.modeViews[0]?.rationale).toBe('rationale.');
		expect(view.warnings.map((warning) => warning.text)).toEqual(['Avoid this seller.']);
	});

	it('renders a verified owner pick from persisted citations without exposing the handoff', () => {
		const view = buildResultView({
			...baseResult,
			products: [{ ...baseResult.products[0], name: 'Northstar Phone', category: 'smartphone', listing_ids: [] }],
			listings: [],
			trust_assessments: [],
			source_snapshots: [{ ...baseResult.source_snapshots[0], title: 'Northstar Phone product page' }],
			source_evidence: [{ ...baseResult.source_evidence[0], claim: 'Northstar Phone was described on the product page.' }],
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				result_author: 'SmartphoneSpecialistAgent',
				handoff_chain: ['GeneralShoppingAgent -> TechnologyDomainAnalystAgent', 'TechnologyDomainAnalystAgent -> SmartphoneSpecialistAgent'],
				verification_action: 'approved',
				final_listing_id: null,
				final_rationale: 'Northstar Phone fits the stated needs.',
				runner_up_product_ids: [],
				mode_results: [{ ...baseResult.recommendation_bundle.mode_results[0], listing_id: null, rationale: 'Northstar Phone fits the stated needs.' }],
				evidence_ids: ['evidence-dell'],
				source_ids: ['source-dell'],
			},
		});
		expect(view.finalMode?.productName).toBe('Northstar Phone');
		expect(view.finalMode?.purchaseUrl).toBeNull();
		expect(view.resultEvidence).toHaveLength(1);
		expect(view.resultSources).toHaveLength(1);
		expect(JSON.stringify(view)).not.toContain('SmartphoneSpecialistAgent');
	});

	it('renders an owner no-strong-buy result without a phantom pick', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				result_author: 'GeneralShoppingAgent',
				verification_action: 'approved',
				final_product_id: null,
				final_listing_id: null,
				no_strong_buy: true,
				no_strong_buy_reason: 'There is not enough checked evidence to choose a product yet.',
				mode_results: [],
				evidence_ids: [],
				source_ids: [],
				runner_up_product_ids: [],
			},
		});
		expect(view.finalMode).toBeNull();
		expect(view.noStrongBuyReason).toContain('not enough checked evidence');
		expect(JSON.stringify(view)).not.toContain('GeneralShoppingAgent');
	});
});
