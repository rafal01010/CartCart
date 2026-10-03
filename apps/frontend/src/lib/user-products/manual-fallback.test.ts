import { describe, expect, it } from 'vitest';
import type { SessionResultsResponse, UserAddedProduct } from '$lib/api/types.js';
import { manualCandidateViews, manualFallbackRequest } from './manual-fallback.js';

const unresolved = {
	candidate_id: 'unresolved', input_text: 'Acme Mini Kettle', research_attempted: true,
} as UserAddedProduct;
const result = { source_snapshots: [] } as unknown as SessionResultsResponse;

describe('manual product fallback', () => {
	it('offers researched unresolved leads and preserves a separate wrong-match correction path', () => {
		const views = manualCandidateViews([
			{ ...unresolved, candidate_id: 'pending', research_attempted: false },
			unresolved,
			{ ...unresolved, candidate_id: 'ambiguous', possible_product_ids: ['one', 'two'] },
			{ ...unresolved, candidate_id: 'url', input_text: null, url: 'https://shop.example/item', possible_product_ids: [] },
			{ ...unresolved, candidate_id: 'matched', listing: { title: 'Wrong product' } as UserAddedProduct['listing'] },
		], result);
		expect(views.map((view) => view.candidate.candidate_id)).toEqual(['unresolved', 'ambiguous', 'url', 'matched']);
		expect(views.map((view) => view.reason)).toEqual([
			'retrieval_insufficient', 'retrieval_insufficient', 'retrieval_unavailable', null,
		]);
		expect(views[3].matchedName).toBe('Wrong product');
	});

	it('sends shopper details against the same candidate without a listing URL', () => {
		const values = {
			name: ' Correct Kettle ', seller: ' Local shop ', price: '49.00', currency: 'usd',
			availability: '', review: '', warranty: ' One year ', specifications: '',
		};
		expect(manualFallbackRequest(unresolved, 'user_correction', values)).toEqual({
			fallback_candidate_id: 'unresolved', input_text: 'Correct Kettle', name: 'Correct Kettle',
			manual_fallback_reason: 'user_correction',
			manual_details: { seller: 'Local shop', price: { amount: '49.00', currency: 'USD' }, warranty: 'One year' },
		});
		expect(manualFallbackRequest(unresolved, 'user_correction', { ...values, name: '' })).toBeNull();
		expect(manualFallbackRequest(unresolved, 'user_correction', { ...values, currency: '' })).toBeNull();
	});
});
