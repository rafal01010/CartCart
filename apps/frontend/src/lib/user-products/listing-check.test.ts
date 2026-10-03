import { describe, expect, it } from 'vitest';
import type { SessionResultsResponse, UserAddedProduct } from '$lib/api/types.js';
import { listingCheckOutcome, normalizeListingLink } from './listing-check.js';

const candidate = {
	candidate_id: 'candidate-1',
	url: 'https://shop.example/item/one',
	research_attempted: true,
} as UserAddedProduct;
const result = {
	source_snapshots: [{
		provider: { raw: { user_added_candidate_id: 'candidate-1' } },
		extraction_status: 'failed',
	}],
	trust_assessments: [],
} as unknown as SessionResultsResponse;

describe('listing correction', () => {
	it('accepts only standalone HTTP(S) links', () => {
		expect(normalizeListingLink(' https://shop.example/item/one ')).toBe('https://shop.example/item/one');
		expect(normalizeListingLink('javascript:alert(1)')).toBeNull();
		expect(normalizeListingLink('See https://shop.example/item/one')).toBeNull();
	});

	it('distinguishes unreadable pages, uncertain matches, and checked listings', () => {
		expect(listingCheckOutcome(candidate, result)?.status).toBe('unreadable');
		expect(listingCheckOutcome(
			{ ...candidate, possible_product_ids: ['product-1'] },
			result,
		)?.status).toBe('uncertain');
		expect(listingCheckOutcome(candidate, {
			...result,
			source_snapshots: [{
				...result.source_snapshots[0],
				extraction_status: 'partial',
				extracted_content: { text: 'Product details without a confirmed offer' },
			}],
		} as SessionResultsResponse)?.status).toBe('uncertain');
		const checked = listingCheckOutcome({
			...candidate,
			listing: {
				listing_id: 'listing-1', title: 'Example kettle', seller: { seller_name: 'Example seller' },
			} as UserAddedProduct['listing'],
		}, {
			...result,
			trust_assessments: [{ listing_id: 'listing-1', summary: 'Seller details remain mixed.' }],
		} as SessionResultsResponse);
		expect(checked?.status).toBe('checked');
		expect(checked?.seller).toBe('Example seller');
		expect(checked?.trust).toBe('Seller details remain mixed.');
	});
});
