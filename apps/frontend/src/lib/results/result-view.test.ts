import { describe, expect, it } from 'vitest';
import type { SessionResultsResponse } from '$lib/api/types.js';
import { buildResultView } from './result-view.js';

const baseResult: SessionResultsResponse = {
	result_version: {
		result_version_id: 'result-version-1',
		run_id: 'run-1',
		version: 2,
		recommendation_bundle_id: 'bundle-1',
		comparison_matrix_id: 'matrix-1',
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
	comparison_matrix: {
		schema_version: 1,
		criteria: [{ name: 'fit', weight: 1, higher_is_better: true }],
		rows: [
			{
				product_id: 'product-dell',
				listing_id: 'listing-dell',
				scores: { fit: 0.9 },
				evidence_ids: ['evidence-dell'],
				summary: 'Strong fit.',
			},
		],
	},
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
		],
		comparison_matrix: {
			schema_version: 1,
			criteria: [{ name: 'fit', weight: 1, higher_is_better: true }],
			rows: [],
		},
		rejected_items: [],
		warnings: [],
		evidence_ids: ['evidence-dell', 'evidence-asus'],
		source_ids: ['source-dell', 'source-asus'],
	},
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
	],
};

describe('result view helpers', () => {
	it('derives final pick, runner-ups, and source references from one stored result', () => {
		const view = buildResultView(baseResult);

		expect(view.finalMode?.label).toBe('Best overall');
		expect(view.whyItWins).toBe('Best balance of fit and seller trust.');
		expect(view.runnerUps).toHaveLength(1);
		expect(view.runnerUps[0]?.label).toBe('Best value');
		expect(view.finalMode?.sources[0]?.url).toBe('https://example.test/dell');
		expect(view.finalMode?.evidence[0]?.claim).toBe('Dell has USB-C support.');
		expect(view.finalMode?.listingTrust?.levelLabel).toBe('Reasonable listing');
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
		expect(view.warnings).toContain('Seller details do not line up.');
		expect(view.warnings.some((warning) => warning.includes('safer seller'))).toBe(true);
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
				rejected_items: [{ reason: '   ', severity: 'low', evidence_ids: [], source_ids: [] }],
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
						reason: 'Seller trust is too weak for this listing.',
						severity: 'blocking',
						evidence_ids: ['evidence-asus'],
						source_ids: ['source-asus'],
					},
				],
			},
		});

		expect(view.rejectedItems).toHaveLength(1);
		expect(view.rejectedItems[0]?.reason).toContain('Seller trust');
		expect(view.rejectedItems[0]?.sources[0]?.url).toBe('https://example.test/asus');
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
		expect(view.finalMode?.rationale).toBe('rationale.');
		expect(view.warnings).toEqual(['Avoid this seller.']);
	});
});
