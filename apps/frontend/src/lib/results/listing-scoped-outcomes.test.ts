import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';
import type { SessionResultsResponse } from '$lib/api/types.js';
import RecommendationResult from './RecommendationResult.svelte';
import { buildResultView } from './result-view.js';

function savedOffers(): SessionResultsResponse {
	const product = { schema_version: 1, product_id: 'kettle', name: 'Shared kettle', source_ids: [], listing_ids: ['rejected', 'confirmed'] };
	const offers: SessionResultsResponse['listings'] = ['rejected', 'confirmed'].map((id) => ({
		schema_version: 1, listing_id: id, product_id: 'kettle', title: `Shared kettle at ${id}`,
		url: `https://shop.example/${id}`, seller: { seller_name: id === 'confirmed' ? 'Authorized shop' : 'Unverified shop', trust_signal: 'unknown', source_ids: [] },
		region_availability: [], source_quality: { level: 'unknown' }, source_ids: [], captured_at: '2026-10-21T00:00:00Z',
	}));
	const matrix: SessionResultsResponse['comparison_matrix'] = {
		schema_version: 1, criteria: [], rows: offers.map((offer) => ({ product_id: 'kettle', listing_id: offer.listing_id, scores: {}, evidence_ids: [], summary: offer.title })),
	};
	return {
		result_version: { result_version_id: 'result', run_id: 'run', version: 1, recommendation_bundle_id: 'bundle', comparison_matrix_id: 'matrix', refinement_id: null, prior_result_version_id: null, requested_result_mode: null },
		products: [product], listings: offers, shortlist: [{ candidate_id: 'candidate-confirmed', product_id: 'kettle', listing_id: 'confirmed', position: 1 }],
		considered_products: offers.map((offer) => ({
			candidate: { schema_version: 1, candidate_id: `candidate-${offer.listing_id}`, product, listing: offer, input_text: offer.title, created_at: '2026-10-21T00:00:00Z' },
			status: offer.listing_id === 'confirmed' ? 'confirmed' : 'excluded',
			exclusion_reason: offer.listing_id === 'confirmed' ? null : 'Unverified shop has no verifiable seller identity.',
		})),
		trust_assessments: offers.map((offer) => ({
			schema_version: 1, listing_id: offer.listing_id, level: offer.listing_id === 'confirmed' ? 'reasonable' : 'suspicious',
			confidence: { level: 'high', score: 0.9 }, summary: offer.listing_id === 'confirmed' ? 'Authorized shop has documented warranty support.' : 'Unverified seller identity.',
			red_flags: offer.listing_id === 'confirmed' ? [] : ['Seller identity cannot be verified.'], positive_signals: [], evidence_ids: [], source_ids: [], assessed_at: '2026-10-21T00:00:00Z',
		})),
		comparison_matrix: matrix,
		recommendation_bundle: {
			schema_version: 1, bundle_id: 'bundle', final_product_id: 'kettle', final_listing_id: 'confirmed', no_strong_buy: false,
			final_rationale: 'Consider the authorized offer.', primary_product_ids: ['kettle'], runner_up_product_ids: [],
			mode_results: [{ mode: 'best_overall', product_id: 'kettle', listing_id: 'confirmed', title: 'Best overall', rationale: 'Consider the authorized offer.', confidence: { level: 'high', score: 0.9 }, evidence_ids: [], source_ids: [] }],
			comparison_matrix: matrix,
			rejected_items: [{ product_id: 'kettle', listing_id: 'rejected', reason_code: 'suspicious_listing', reason: 'Unverified shop has no verifiable seller identity.', severity: 'high', evidence_ids: [], source_ids: [] }],
			warnings: [], evidence_ids: [], source_ids: [],
		},
		category_analyses: [], agent_records: [], source_snapshots: [], source_evidence: [],
	};
}

describe('saved seller offer outcomes', () => {
	it('projects independent statuses and trust for two offers of one canonical product', () => {
		const view = buildResultView(savedOffers());
		expect(view.consideredProducts.map(({ candidateId, status, exclusionReason, listingRisk, inComparison }) => ({ candidateId, status, exclusionReason, listingRisk, inComparison }))).toEqual([
			{ candidateId: 'candidate-rejected', status: 'excluded', exclusionReason: 'Unverified shop has no verifiable seller identity.', listingRisk: 'Unverified seller identity.', inComparison: true },
			{ candidateId: 'candidate-confirmed', status: 'confirmed', exclusionReason: null, listingRisk: null, inComparison: true },
		]);
		expect(view.recommendedOptions[0]).toMatchObject({ listingId: 'confirmed', sellerName: 'Authorized shop', purchaseUrl: 'https://shop.example/confirmed' });
		expect(view.rejectedItems[0].label).toBe('Shared kettle at rejected (Unverified shop)');
	});

	it('keeps a product-wide rejection labeled with the product', () => {
		const result = savedOffers();
		result.recommendation_bundle.rejected_items[0].listing_id = null;
		expect(buildResultView(result).rejectedItems[0].label).toBe('Shared kettle');
	});

	it('renders the authorized offer separately from rejected seller warnings', () => {
		const result = savedOffers();
		const original = JSON.stringify(result);
		const output = render(RecommendationResult, { props: { result: buildResultView(result), onStartOver: () => {} } }).body;
		const recommendation = output.slice(output.indexOf('aria-label="Recommended options"'), output.indexOf('id="listing-concerns-title"'));
		expect(recommendation).toContain('Authorized shop');
		expect(recommendation).toContain('https://shop.example/confirmed');
		expect(recommendation).not.toContain('Unverified seller identity.');
		expect(output).toContain('Unverified seller identity.');
		expect(output).toContain('Unverified shop has no verifiable seller identity.');
		expect(output).toContain('Shared kettle at rejected (Unverified shop)');
		expect(output.indexOf('Unverified shop has no verifiable seller identity.')).toBeGreaterThan(output.indexOf('id="avoid-title"'));
		expect(JSON.stringify(result)).toBe(original);
	});
});
