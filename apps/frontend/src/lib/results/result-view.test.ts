import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';
import RecommendationResult from './RecommendationResult.svelte';
import EvidenceDetails from './EvidenceDetails.svelte';
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

describe('recommendation grouping', () => {
	it.each([
		{ primary: ['product-dell'], runners: [] },
		{ primary: ['product-dell', 'product-asus'], runners: [] },
		{ primary: ['product-dell'], runners: ['product-asus'] },
		{ primary: ['product-dell', 'product-asus', 'product-lg'], runners: ['product-four', 'product-five'] },
	])('keeps explicit primary $primary and optional runners $runners separate', ({ primary, runners }) => {
		const result: SessionResultsResponse = {
			...baseResult,
			products: [...baseResult.products,
				{ ...baseResult.products[0], product_id: 'product-four', name: 'Compact alternative', source_ids: [], listing_ids: [] },
				{ ...baseResult.products[0], product_id: 'product-five', name: 'Larger alternative', source_ids: [], listing_ids: [] },
			],
			recommendation_bundle: {
				...baseResult.recommendation_bundle, primary_product_ids: primary, runner_up_product_ids: runners,
			},
		};
		const original = JSON.stringify(result);
		const view = buildResultView(result);
		expect(view.recommendedOptions.map((option) => option.productId)).toEqual(primary);
		expect(view.runnerUps.map((option) => option.productId)).toEqual(runners);
		expect(JSON.stringify(result)).toBe(original);
	});

	it('keeps authored grouping despite unused modes and recovers reasons without citations or listings', () => {
		const view = buildResultView({
			...baseResult, listings: [], source_snapshots: [], source_evidence: [],
			comparison_matrix: { schema_version: 1, criteria: [], rows: [
				{ product_id: 'product-asus', scores: {}, evidence_ids: [], summary: 'A useful smaller choice.' },
			] },
			category_analyses: [{
				schema_version: 1, product_id: 'product-lg', listing_ids: [], category: 'monitor',
				fit_summary: 'More workspace.', strengths: [], weaknesses: ['Takes more desk space.'], warnings: [],
				confidence: { level: 'unknown' }, evidence_ids: [], source_ids: [],
			}],
			recommendation_bundle: {
				...baseResult.recommendation_bundle, primary_product_ids: ['product-dell', 'product-asus'],
				runner_up_product_ids: ['product-lg'], mode_results: [baseResult.recommendation_bundle.mode_results[0]],
			},
		});
		expect(view.recommendedOptions.map((option) => option.productId)).toEqual(['product-dell', 'product-asus']);
		expect(view.recommendedOptions[1]).toMatchObject({ rationale: 'A useful smaller choice.', listingId: null });
		expect(view.runnerUps.map((option) => option.productId)).toEqual(['product-lg']);
		expect(view.runnerUps[0]).toMatchObject({ rationale: 'More workspace.', tradeoffs: ['Takes more desk space.'] });
	});

	it.each([undefined, null])('infers saved legacy grouping when primary IDs are %s', (primaryIds) => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: { ...baseResult.recommendation_bundle, primary_product_ids: primaryIds },
		});
		expect(view.recommendedOptions.map((option) => option.productId)).toEqual(['product-dell', 'product-lg']);
		expect(view.runnerUps.map((option) => option.productId)).toEqual(['product-asus']);
	});

	it('deduplicates legacy groups and excludes runner-mode membership from primary choices', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle, runner_up_product_ids: ['product-dell', 'product-asus', 'product-asus'],
				mode_results: [...baseResult.recommendation_bundle.mode_results,
					{ ...baseResult.recommendation_bundle.mode_results[3], mode: 'runner_up' },
				],
			},
		});
		expect(view.recommendedOptions.map((option) => option.productId)).toEqual(['product-dell']);
		expect(view.runnerUps.map((option) => option.productId)).toEqual(['product-asus', 'product-lg']);
	});

	it('promotes one viable legacy runner-only recommendation without adding prerequisites', () => {
		const view = buildResultView({
			...baseResult, listings: [], trust_assessments: [], source_snapshots: [], source_evidence: [],
			recommendation_bundle: {
				...baseResult.recommendation_bundle, final_product_id: null, final_listing_id: null,
				runner_up_product_ids: ['missing-product', 'product-asus', 'product-lg'], mode_results: [],
			},
		});
		expect(view.recommendedOptions.map((option) => option.productId)).toEqual(['product-asus']);
		expect(view.runnerUps.map((option) => option.productId)).toEqual(['product-lg']);
		expect(view.noStrongBuyReason).toBeNull();
	});

	it('keeps explicit empty no-strong-buy groups empty instead of inferring cards from modes', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle, primary_product_ids: [], runner_up_product_ids: [],
				final_product_id: null, final_listing_id: null, no_strong_buy: true,
				no_strong_buy_reason: 'No suitable option.',
			},
		});
		expect(view.recommendedOptions).toEqual([]);
		expect(view.runnerUps).toEqual([]);
		expect(view.noStrongBuyReason).toBe('No suitable option.');
	});

	it('does not let a stale no-strong-buy flag erase useful explicit choices', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle, primary_product_ids: ['product-dell'],
				no_strong_buy: true, no_strong_buy_reason: 'Old warning.',
			},
		});
		expect(view.recommendedOptions.map((option) => option.productId)).toEqual(['product-dell']);
		expect(view.runnerUps.map((option) => option.productId)).toEqual(['product-asus']);
		expect(view.noStrongBuyReason).toBeNull();
	});

	it('deduplicates explicit selections without promoting unrelated modes', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle, primary_product_ids: ['product-dell', 'product-dell'],
				runner_up_product_ids: ['product-dell', 'product-asus', 'product-asus'],
			},
		});
		expect(view.recommendedOptions.map((option) => option.productId)).toEqual(['product-dell']);
		expect(view.runnerUps.map((option) => option.productId)).toEqual(['product-asus']);
	});

	it('caps legacy groups at three primary choices and two runners while preserving saved records', () => {
		const result: SessionResultsResponse = {
			...baseResult,
			products: [...baseResult.products,
				{ ...baseResult.products[0], product_id: 'product-four', name: 'Fourth choice' },
				{ ...baseResult.products[0], product_id: 'product-five', name: 'Fifth choice' },
				{ ...baseResult.products[0], product_id: 'product-six', name: 'Sixth choice' },
				{ ...baseResult.products[0], product_id: 'product-seven', name: 'Seventh choice' },
			],
			recommendation_bundle: {
				...baseResult.recommendation_bundle, runner_up_product_ids: ['product-asus', 'product-six', 'product-seven'],
				mode_results: [...baseResult.recommendation_bundle.mode_results,
					{ ...baseResult.recommendation_bundle.mode_results[0], product_id: 'product-four' },
					{ ...baseResult.recommendation_bundle.mode_results[0], product_id: 'product-five' },
				],
			},
		};
		const original = JSON.stringify(result);
		const view = buildResultView(result);
		expect(view.recommendedOptions.map((option) => option.productId)).toEqual(['product-dell', 'product-lg', 'product-four']);
		expect(view.runnerUps.map((option) => option.productId)).toEqual(['product-asus', 'product-six']);
		expect(JSON.stringify(result)).toBe(original);
	});
});

describe('result view helpers', () => {
	it('groups source originals by neutral URL and keeps cited ID aliases', () => {
		const result = structuredClone(baseResult);
		result.source_results = [
			{
				source_id: 'search-dell',
				url: 'https://example.test/dell/?utm_source=search',
				title: 'Dell discovery',
				snippet: 'Changed display support detail.',
				source_type: 'search_result',
				query: { query: 'monitor', intent: 'discovery' },
				provider: { raw: { research_selection: { status: 'deferred' } } },
				quality: { level: 'unknown' },
			},
			{
				source_id: 'unused-lead',
				url: 'https://example.test/unused',
				title: 'Unused lead',
				snippet: 'Redundant original retained in the API.',
				source_type: 'search_result',
				query: { query: 'monitor', intent: 'discovery' },
				provider: { raw: { research_selection: { status: 'deferred' } } },
				quality: { level: 'unknown' },
			},
		];
		result.recommendation_bundle.source_ids = ['search-dell', 'source-dell'];
		const original = structuredClone(result);
		const view = buildResultView(result);
		expect(view.sourceViews.map((source) => source.id)).toEqual(['source-dell', 'source-asus', 'source-lg']);
		expect(view.resultSources.map((source) => source.id)).toEqual(['source-dell', 'source-asus', 'source-lg']);
		expect(view.sourceViews[0]?.snippet).toBe('Changed display support detail.');
		expect(view.sourceViews[0]?.evidence.map((evidence) => evidence.id)).toEqual(['evidence-dell']);
		expect(result).toEqual(original);
	});

	it('keeps functional source variants and explicitly cited deferred sources', () => {
		const result = structuredClone(baseResult);
		result.source_results = ['ph', 'us'].map((variant) => ({
			source_id: `source-${variant}`,
			url: `https://example.test/monitor?variant=${variant}&utm_source=search`,
			title: `Monitor ${variant}`,
			snippet: `Variant ${variant}`,
			source_type: 'search_result',
			query: { query: 'monitor', intent: 'discovery' },
			provider: { raw: { research_selection: { status: 'deferred' } } },
			quality: { level: 'unknown' },
		}));
		result.recommendation_bundle.source_ids = ['source-ph', 'source-us'];
		const view = buildResultView(result);
		expect(view.resultSources.slice(0, 2).map((source) => source.url)).toEqual([
			'https://example.test/monitor?variant=ph', 'https://example.test/monitor?variant=us',
		]);
	});
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
		expect(view.recommendedOptions.map((item) => item.productName)).toEqual([
			'Dell UltraSharp U2724DE',
		]);
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

	it('shows distinct approved options whose exact source quotes retain source-metadata targets', () => {
		const view = buildResultView({
			...baseResult,
			source_evidence: baseResult.source_evidence.map((item) => ({
				...item, target: { target_type: 'source_metadata', source_id: item.source_id },
			})),
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				runner_up_product_ids: ['product-asus', 'product-lg'],
				mode_results: [
					{ ...baseResult.recommendation_bundle.mode_results[1], mode: 'runner_up' },
					{ ...baseResult.recommendation_bundle.mode_results[3], mode: 'runner_up' },
				],
			},
		});
		expect(view.recommendedOptions.map((item) => item.productId)).toEqual(['product-dell']);
		expect([...view.recommendedOptions, ...view.runnerUps].map((item) => item.rationale)).toEqual([
			'Best balance of fit and seller trust.',
			'Lower price with credible evidence.',
			'Costs more, so it only works if the budget tradeoff is acceptable.',
		]);
		expect(view.recommendedOptions[0]?.productUrl).toBe('https://example.test/dell');
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
		expect(view.recommendedOptions.map((item) => item.productId)).toEqual(['product-dell']);
		expect(view.runnerUps[0]?.rationale).not.toContain('Lower price');
		expect(view.runnerUps[0]?.evidence).toEqual([]);
		expect(view.runnerUps[0]?.sources.map((item) => item.id)).not.toContain('source-dell');
	});

	it.each(['suspicious', 'over-cap', 'safe'])('keeps a runner-up product-only when only the shortlist supplies its %s offer', (risk) => {
		const rows = baseResult.comparison_matrix.rows.filter((row) => row.product_id !== 'product-asus');
		const trustLevel = risk === 'suspicious' ? 'suspicious' : 'reasonable';
		const result: SessionResultsResponse = {
			...baseResult,
			listings: baseResult.listings.map((item) => item.listing_id === 'listing-dell'
				? { ...item, price: { amount: 249, currency: 'USD' } }
				: item.listing_id === 'listing-asus'
					? { ...item, seller: { ...item.seller, trust_signal: trustLevel }, price: { amount: risk === 'over-cap' ? 399 : 349, currency: 'USD' } }
					: item),
			trust_assessments: [...baseResult.trust_assessments, {
				...baseResult.trust_assessments[0], listing_id: 'listing-asus', level: trustLevel,
				summary: risk === 'suspicious' ? 'Seller identity could not be confirmed.' : 'Seller details were checked.',
				positive_signals: risk === 'suspicious' ? [] : ['Checked seller'],
				red_flags: risk === 'suspicious' ? ['Unconfirmed seller identity'] : [],
				evidence_ids: ['evidence-asus'], source_ids: ['source-asus'],
			}],
			comparison_matrix: { ...baseResult.comparison_matrix, rows },
			category_analyses: [{
				schema_version: 1, product_id: 'product-asus', listing_ids: ['listing-asus'], category: 'monitor',
				fit_summary: 'The product fits the design workspace.', strengths: [], weaknesses: [], warnings: [],
				confidence: { level: 'medium', score: 0.72 }, evidence_ids: ['evidence-asus'], source_ids: ['source-asus'],
			}],
			recommendation_bundle: {
				...baseResult.recommendation_bundle, mode_results: [],
				comparison_matrix: { ...baseResult.comparison_matrix, rows },
			},
		};
		const view = buildResultView(result);
		expect(view.runnerUps).toHaveLength(1);
		expect(view.runnerUps[0]).toMatchObject({
			productId: 'product-asus', productName: 'ASUS ProArt PA278CV',
			listingId: null, listingTitle: null, sellerName: null, priceLabel: null, purchaseUrl: null, listingTrust: null,
			rationale: 'The product fits the design workspace.', confidence: 'medium 72%',
		});
		expect(view.runnerUps[0]?.evidence.map((item) => item.id)).toEqual(['evidence-asus']);
		expect(view.runnerUps[0]?.sources.map((item) => item.id)).toEqual(['source-asus']);
	});

	it('preserves saved alternate choices when the legacy no-option flag is also present', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle, no_strong_buy: true,
				no_strong_buy_reason: 'The listings need more checks.', final_product_id: null, final_listing_id: null,
			},
		});
		expect(view.finalMode).toBeNull();
		expect(view.recommendedOptions.map((item) => item.productId)).toEqual(['product-dell', 'product-lg']);
		expect(selectModeView(view, null)?.productId).toBe('product-dell');
		expect(view.noStrongBuyReason).toBeNull();
	});

	it('shows saved choices without requiring a final reference', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: { ...baseResult.recommendation_bundle, final_product_id: null, final_listing_id: null },
		});
		expect(view.finalMode).toBeNull();
		expect(selectModeView(view, null)?.productId).toBe('product-dell');
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

	it('grouping keeps one runner-up per product while retaining distinct saved offers', () => {
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
		expect(view.runnerUps.map((item) => item.listingId)).toEqual(['listing-asus-other']);
		expect(view.modeViews.filter((item) => item.productId === 'product-asus').map((item) => item.listingId)).toEqual(['listing-asus', 'listing-asus', 'listing-asus-other']);
		expect(view.runnerUps.map((item) => item.evidence.map((evidence) => evidence.id))).toEqual([
			['evidence-asus-other'],
		]);
		expect(view.runnerUps.map((item) => item.sources.map((source) => source.id))).toEqual([
			['source-asus-other'],
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
		expect(view.recommendedOptions.map((item) => item.productId)).toEqual([
			'product-dell', 'product-lg',
		]);
		expect(view.recommendedOptions[0]?.productUrl).toBe('https://example.test/dell');
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
			'ASUS ProArt PA278CV: Seller details do not line up.',
		);
		expect(view.warnings.some((warning) => warning.text.includes('safer seller'))).toBe(true);
		expect(
			view.warnings.find((warning) => warning.text === 'ASUS ProArt PA278CV: Seller details do not line up.')?.evidence[0]
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
				mode_results: [], runner_up_product_ids: [],
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

	it('deduplicates warnings within their product or offer scope and retains optional sources', () => {
		const view = buildResultView({
			...baseResult,
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				warnings: ['Check return coverage.', 'Check delivery costs.', 'Check return coverage.'],
				evidence_ids: ['evidence-dell'], source_ids: ['source-dell'],
			},
			category_analyses: [{
				schema_version: 1, product_id: 'product-asus', listing_ids: ['listing-asus'], category: 'monitor',
				fit_summary: 'Fits the workspace.', strengths: [], weaknesses: [],
				warnings: ['Check return coverage.'], confidence: { level: 'medium', score: 0.7 },
				evidence_ids: ['evidence-asus', 'evidence-dell'], source_ids: ['source-asus', 'source-dell'],
			}],
			trust_assessments: baseResult.trust_assessments.map((trust) => ({
				...trust, red_flags: ['Check return coverage.', 'Check warranty coverage.'],
				evidence_ids: ['evidence-lg', 'evidence-asus'], source_ids: ['source-lg', 'source-asus'],
			})),
		});

		expect(view.warnings.map((warning) => ({
			text: warning.text,
			claims: warning.evidence.map((evidence) => evidence.claim),
			urls: warning.sources.map((source) => source.url),
		}))).toEqual([
			{
				text: 'Check return coverage.',
				claims: ['Dell has USB-C support.'],
				urls: ['https://example.test/dell'],
			},
			{
				text: 'Check delivery costs.', claims: ['Dell has USB-C support.'], urls: ['https://example.test/dell'],
			},
			{
				text: 'ASUS ProArt PA278CV: Check return coverage.',
				claims: ['ASUS is a credible value pick.', 'Dell has USB-C support.'],
				urls: ['https://example.test/asus', 'https://example.test/dell'],
			},
			{
				text: 'Dell UltraSharp U2724DE — Official: Check return coverage.',
				claims: ['LG is a credible stretch pick.', 'ASUS is a credible value pick.'],
				urls: ['https://example.test/lg', 'https://example.test/asus'],
			},
			{
				text: 'Dell UltraSharp U2724DE — Official: Check warranty coverage.',
				claims: ['LG is a credible stretch pick.', 'ASUS is a credible value pick.'],
				urls: ['https://example.test/lg', 'https://example.test/asus'],
			},
		]);
	});

	it('preserves advice with no citations, checked listing, known price or final mode', () => {
		const view = buildResultView({
			...baseResult, listings: [], trust_assessments: [], source_evidence: [], source_snapshots: [],
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				final_product_id: null, final_listing_id: null, runner_up_product_ids: [],
				evidence_ids: [], source_ids: [],
				mode_results: [{
					mode: 'runner_up', product_id: 'product-asus', title: 'For a compact desk',
					rationale: 'A practical option for this desk.', confidence: { level: 'unknown' },
					tradeoffs: ['Less workspace than a larger display.'], unknowns: ['Current local stock.'],
					evidence_ids: [], source_ids: [],
				}],
			},
		});
		expect(view.recommendedOptions).toHaveLength(1);
		expect(view.recommendedOptions[0]).toMatchObject({
			productId: 'product-asus', listingTrust: null, priceLabel: null, evidence: [], sources: [],
			rationale: 'A practical option for this desk.', tradeoffs: ['Less workspace than a larger display.'],
			unknowns: ['Current local stock.'],
		});
	});

	it.each([
		{ price: null, label: 'Recommended option', note: null },
		{ price: { amount: 349, currency: 'PHP' }, label: 'Recommended option', note: null },
		{ price: { amount: 370, currency: 'USD' }, label: 'Recommended option', note: '$20 above the requested budget of $350.' },
		{ price: { amount: 349, currency: 'USD' }, label: 'Best within budget', note: null },
	])('normalizes affordability labels while retaining advice for $note', ({ price, label, note }) => {
		const view = buildResultView({
			...baseResult,
			source_evidence: [], source_snapshots: [], source_results: [],
			shopping_brief: {
				schema_version: 1, original_query: 'A monitor around $350.', constraints: [], preferences: [],
				budget: { amount: { amount: 350, currency: 'USD' }, mode: 'hard_cap' },
			},
			listings: baseResult.listings.map((listing) => listing.listing_id === 'listing-asus' ? { ...listing, price } : listing),
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				final_product_id: null, final_listing_id: null, runner_up_product_ids: [],
				mode_results: [{
					...baseResult.recommendation_bundle.mode_results[2],
					rationale: 'A useful option for the requested workspace.', evidence_ids: [], source_ids: [],
				}],
			},
		});
		expect(view.recommendedOptions.map((option) => option.productId)).toEqual(['product-asus']);
		expect(view.recommendedOptions[0]).toMatchObject({
			label, budgetNote: note, rationale: 'A useful option for the requested workspace.',
			purchaseUrl: 'https://example.test/listing-asus',
		});
	});

	it('uses neutral affordability labels without a saved requested budget', () => {
		const view = buildResultView(baseResult);
		expect(view.modeViews.find((mode) => mode.mode === 'within_budget')).toMatchObject({
			label: 'Recommended option', budgetNote: null,
			rationale: 'Stays inside the stated budget with credible evidence.',
		});
	});

	it('keeps a model-selected over-budget offer with its scoped caution and neutral link', () => {
		const view = buildResultView({
			...baseResult,
			trust_assessments: [{
				...baseResult.trust_assessments[0], level: 'suspicious',
				red_flags: ['Check the seller identity before paying.'],
			}],
			recommendation_bundle: {
				...baseResult.recommendation_bundle,
				mode_results: [{
					...baseResult.recommendation_bundle.mode_results[0], mode: 'stretch_pick',
					tradeoffs: ['Costs $20 more than the requested budget.'], evidence_ids: [], source_ids: [],
				}],
				evidence_ids: [], source_ids: [],
			},
		});
		expect(view.recommendedOptions[0]?.purchaseUrl).toBe('https://example.test/listing-dell');
		expect(view.recommendedOptions[0]?.tradeoffs).toEqual(['Costs $20 more than the requested budget.']);
		expect(view.warnings.map((item) => item.text)).toContain('Dell UltraSharp U2724DE — Official: Check the seller identity before paying.');
	});

	it('retains source snippets below advice without requiring captured quotes', () => {
		const view = buildResultView({
			...baseResult, source_snapshots: [], source_evidence: [],
			source_results: [{
				source_id: 'search-source', title: 'Product announcement',
				url: 'https://example.test/announcement?tag=affiliate&color=black', source_type: 'search_result',
				provider: { provider_name: 'search' }, quality: { level: 'unknown' }, snippet: 'Available announcement details.',
			}],
		});
		expect(view.recommendedOptions.map((item) => item.productId)).toEqual(['product-dell', 'product-lg']);
		expect(view.sourceViews[0]).toMatchObject({
			typeLabel: 'Search result', snippet: 'Available announcement details.', evidence: [],
			url: 'https://example.test/announcement?color=black',
		});
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

	it('preserves literal fixture words in shopping identities, evidence and authored advice', () => {
		const result = structuredClone(baseResult);
		result.products[0].name = 'Pendant light fixture';
		result.listings[0].title = 'FixtureMaker pendant light fixture';
		result.listings[0].seller.seller_name = 'FixtureSeller Electronics';
		result.source_snapshots[0].title = 'FixtureMaker light fixture guide';
		result.source_evidence[0].claim = 'The light fixture uses a replaceable bulb.';
		result.source_results = [{
			source_id: 'source-light-search', title: 'FixtureMaker light fixture review',
			url: 'https://example.test/light', source_type: 'search_result',
			snippet: 'This light fixture has two mounting choices.',
			provider: { provider_name: 'fixture-search' },
			quality: { level: 'adequate', score: 0.7 },
		}];
		result.recommendation_bundle.final_rationale = 'Choose the light fixture for adjustable lighting.  Keep its bulb type in mind.';
		result.recommendation_bundle.mode_results[0].rationale = 'Choose the light fixture for adjustable lighting.  Keep its bulb type in mind.';
		result.recommendation_bundle.mode_results[0].tradeoffs = ['The light fixture is larger than the desk lamp.'];
		result.recommendation_bundle.warnings = ['The light fixture needs a grounded connection.'];
		result.considered_products = [{
			status: 'manual', exclusion_reason: null,
			candidate: {
				schema_version: 1, candidate_id: 'candidate-light', created_at: '2026-05-31T00:00:00Z',
				input_text: 'Compare this light fixture with FixtureMaker Mini.',
				manual_details: { seller: 'FixtureSeller Electronics' },
			},
		}];
		const before = JSON.stringify(result);
		const view = buildResultView(result);
		expect(view.finalMode).toMatchObject({
			productName: 'Pendant light fixture', listingTitle: 'FixtureMaker pendant light fixture',
			sellerName: 'FixtureSeller Electronics',
			rationale: 'Choose the light fixture for adjustable lighting.  Keep its bulb type in mind.',
			tradeoffs: ['The light fixture is larger than the desk lamp.'],
			purchaseUrl: 'https://example.test/listing-dell',
		});
		expect(view.sourceViews[0]).toMatchObject({ title: 'FixtureMaker light fixture guide', url: 'https://example.test/dell' });
		expect(view.evidenceViews[0]).toMatchObject({ claim: 'The light fixture uses a replaceable bulb.', sourceTitle: 'FixtureMaker light fixture guide', sourceUrl: 'https://example.test/dell' });
		expect(view.consideredProducts[0]).toMatchObject({ askedFor: 'Compare this light fixture with FixtureMaker Mini.', manualSeller: 'FixtureSeller Electronics' });
		expect(view.sourceViews.find((source) => source.id === 'source-light-search')).toMatchObject({
			title: 'FixtureMaker light fixture review', snippet: 'This light fixture has two mounting choices.', url: 'https://example.test/light',
		});
		expect(view.whyItWins).toBe('Choose the light fixture for adjustable lighting.  Keep its bulb type in mind.');
		expect(view.warnings[0]?.text).toBe('The light fixture needs a grounded connection.');
		expect(JSON.stringify(result)).toBe(before);
	});

	it('renders authored advice without aggregating diagnostic warnings or generated buying rituals', () => {
		const result = structuredClone(baseResult);
		result.recommendation_bundle.warnings = ['A diagnostic-only absence statement.'];
		result.recommendation_bundle.mode_results[0].unknowns = ['Another diagnostic-only absence statement.'];
		result.recommendation_bundle.mode_results[0].tradeoffs = ['Costs $20 more for a better adjustable stand.'];
		result.source_snapshots[0].extraction_status = 'partial';
		result.source_evidence[0].confidence = { level: 'low', score: 0.2 };
		result.source_evidence[0].claim = 'Conflicting published measurements remain in the source record.';
		const view = buildResultView(result);
		const output = render(RecommendationResult, { props: {
			result: view, onStartOver: () => {},
		} }).body;
		expect(output).toContain('Dell UltraSharp U2724DE');
		expect(output).toContain('Best blend of features and seller safety.');
		expect(output).toContain('Costs $20 more for a better adjustable stand.');
		expect(output).not.toContain('A diagnostic-only absence statement.');
		expect(output).not.toContain('Another diagnostic-only absence statement.');
		expect(output).not.toContain('What to watch');
		expect(output).not.toContain('Some sources disagree');
		expect(output).not.toContain('Some source details are uncertain.');
		expect(output).not.toContain('Some pages could not be fully read.');
		expect(output).not.toContain('confidence');
		expect(output).not.toContain('Check the current price');
		expect(output).not.toContain('Check the seller, warranty');
		expect(view.warnings[0]?.text).toBe('A diagnostic-only absence statement.');
		expect(view.finalMode?.confidence).toBe('high 84%');
		expect(view.hasWeakEvidence).toBe(true);
		expect(view.hasConflictingEvidence).toBe(true);
		expect(view.hasPartialSources).toBe(true);
	});

	it('renders one result with a top restart and no legacy shopper panels', () => {
		const view = buildResultView(baseResult);
		const output = render(RecommendationResult, { props: { result: view, onStartOver: () => {} } }).body;
		expect(output).toContain('Ask another question');
		expect(output.indexOf('Ask another question')).toBeLessThan(output.indexOf('<h1'));
		expect(output.match(/Ask another question/g)).toHaveLength(1);
		expect(output).toContain('Dell UltraSharp U2724DE');
		expect(output).toContain('ASUS ProArt PA278CV');
		expect(output).toContain('Runners-up');
		expect(output).toContain('Available sources');
		for (const text of ['Decision history', 'Products considered', 'Saved comparison', 'Supporting details', 'Seller unknown', 'Price unknown', 'Price unavailable', 'No comparison criteria were saved', 'Refine this decision', 'Have a listing you want checked?', 'Add or correct product details', 'Advice for', 'Prices and availability can change', 'Seller and listing checks']) {
			expect(output).not.toContain(text);
		}
	});

	it('renders an identical single-choice reason once and preserves distinct and multi-choice reasons', () => {
		const result = structuredClone(baseResult);
		const reason = 'Choose the adjustable stand for a changing workstation.';
		result.recommendation_bundle.primary_product_ids = ['product-dell'];
		result.recommendation_bundle.runner_up_product_ids = [];
		result.recommendation_bundle.final_rationale = reason;
		result.recommendation_bundle.mode_results[0].rationale = reason;
		result.recommendation_bundle.mode_results[0].tradeoffs = ['The larger stand uses more desk space.'];
		const before = JSON.stringify(result);
		const identical = render(RecommendationResult, { props: { result: buildResultView(result), onStartOver: () => {} } }).body;
		expect(identical.split(reason)).toHaveLength(2);
		expect(identical).toContain('The larger stand uses more desk space.');
		expect(JSON.stringify(result)).toBe(before);

		result.recommendation_bundle.final_rationale = 'This monitor balances the desk setup and picture quality.';
		const distinct = render(RecommendationResult, { props: { result: buildResultView(result), onStartOver: () => {} } }).body;
		expect(distinct).toContain('This monitor balances the desk setup and picture quality.');
		expect(distinct).toContain(reason);

		result.recommendation_bundle.final_rationale = reason;
		result.recommendation_bundle.primary_product_ids = ['product-dell', 'product-lg'];
		const multiple = render(RecommendationResult, { props: { result: buildResultView(result), onStartOver: () => {} } }).body;
		expect(multiple.split(reason)).toHaveLength(3);
	});

	it('renders actual offer values and omits absent offer boilerplate', () => {
		const result = structuredClone(baseResult);
		result.listings = result.listings.map((listing) => ({ ...listing, price: null, seller: { ...listing.seller, seller_name: '' } }));
		const output = render(RecommendationResult, { props: { result: buildResultView(result), onStartOver: () => {} } }).body;
		for (const text of ['Price unavailable', 'Price unknown', 'Seller unknown']) expect(output).not.toContain(text);
		const withOffer = render(RecommendationResult, { props: { result: buildResultView(baseResult), onStartOver: () => {} } }).body;
		expect(withOffer).toContain('Dell Official');
		expect(withOffer).toContain('$499 · Dell Official');
		expect(withOffer).toContain('https://example.test/listing-dell');
	});

	it('renders source-free advice without empty details shells', () => {
		const result = structuredClone(baseResult);
		result.source_snapshots = [];
		result.source_evidence = [];
		result.source_results = [];
		result.trust_assessments = [];
		result.recommendation_bundle.rejected_items = [];
		const output = render(RecommendationResult, { props: { result: buildResultView(result), onStartOver: () => {} } }).body;
		expect(output).toContain('Best blend of features and seller safety.');
		for (const text of ['Available sources', 'Supporting details', 'Listing concerns', 'No sources were preserved', 'No additional listing checks']) expect(output).not.toContain(text);
	});

	it('renders meaningful adverse listing advice and rejection reasons without a diagnostic shell', () => {
		const result = structuredClone(baseResult);
		result.trust_assessments[0].level = 'suspicious';
		result.trust_assessments[0].summary = 'Avoid this listing because its seller identity was copied.';
		result.trust_assessments[0].red_flags = ['The payment instructions name a different company.'];
		result.recommendation_bundle.rejected_items = [{
			product_id: 'product-asus', listing_id: 'listing-asus', reason_code: 'suspicious_listing',
			reason: 'A counterfeit power adapter makes this offer unsuitable.', severity: 'blocking',
			evidence_ids: ['evidence-asus'], source_ids: ['source-asus'],
		}];
		const output = render(RecommendationResult, { props: { result: buildResultView(result), onStartOver: () => {} } }).body;
		expect(output).toContain('Avoid this listing because its seller identity was copied.');
		expect(output).toContain('The payment instructions name a different company.');
		expect(output).toContain('A counterfeit power adapter makes this offer unsuitable.');
		expect(output).toContain('https://example.test/asus');
		expect(output).not.toContain('Supporting details');
		expect(output).not.toContain('high 82%');
	});

	it('renders source facts and video disclosures without diagnostic confidence and process metrics', () => {
		const result = structuredClone(baseResult);
		result.source_evidence[0].video = {
			video_id: 'video-light', url: 'https://www.youtube.com/watch?v=video-light',
			channel_name: 'FixtureMaker Reviews', transcript_availability: 'available',
			sponsorship_disclosed: true, affiliate_links_disclosed: true,
			affiliate_bias_risk: { level: 'medium', score: 0.62 },
		};
		result.source_evidence[0].timestamp_references = [{ start_seconds: 75, end_seconds: 91 }];
		const view = buildResultView(result);
		const output = render(EvidenceDetails, { props: { evidence: [view.evidenceViews[0]], sources: [view.sourceViews[0]] } }).body;
		expect(output).toContain('Dell has USB-C support.');
		expect(output).toContain('Dell source');
		expect(output).toContain('https://example.test/dell');
		expect(output).toContain('1:15-1:31');
		expect(output).toContain('Channel: FixtureMaker Reviews');
		expect(output).toContain('Sponsorship disclosed');
		expect(output).toContain('Affiliate links disclosed by source');
		expect(output).not.toContain('confidence:');
		expect(output).not.toContain('quality:');
		expect(output).not.toContain('captured');
		expect(output).not.toContain('Transcript:');
		expect(output).not.toContain('Bias risk:');
		expect(view.evidenceViews[0]?.metadata).toContain('Bias risk: medium 62%');
		expect(view.evidenceViews[0]?.confidence).toBe('high 86%');
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
