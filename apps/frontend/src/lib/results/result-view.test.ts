import { describe, expect, it } from 'vitest';
import type { SessionResultsResponse } from '$lib/api/types.js';
import { buildResultView, neutralOutboundUrl, selectModeView } from './result-view.js';

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
		comparison_matrix: {
			schema_version: 1,
			criteria: [{ name: 'fit', weight: 1, higher_is_better: true }],
			rows: [],
		},
		rejected_items: [],
		warnings: [],
		evidence_ids: ['evidence-dell', 'evidence-asus', 'evidence-lg'],
		source_ids: ['source-dell', 'source-asus', 'source-lg'],
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

describe('result view helpers', () => {
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
		expect(view.finalMode?.mode).toBe('best_overall');
		expect(view.whyItWins).toBe('Best balance of fit and seller trust.');
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
		expect(view.finalMode?.rationale).toBe('rationale.');
		expect(view.warnings.map((warning) => warning.text)).toEqual(['Avoid this seller.']);
	});
});
