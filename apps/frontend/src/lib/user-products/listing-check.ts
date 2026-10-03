import type { SessionResultsResponse, UserAddedProduct } from '$lib/api/types.js';

export type ListingCheckStatus = 'checked' | 'unreadable' | 'uncertain';

export interface ListingCheckOutcome {
	status: ListingCheckStatus;
	title: string;
	detail: string;
	seller: string | null;
	trust: string | null;
	url: string;
}

export function normalizeListingLink(value: string): string | null {
	try {
		const parsed = new URL(value.trim());
		if (!['https:', 'http:'].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password) {
			return null;
		}
		return parsed.href;
	} catch {
		return null;
	}
}

export function listingCheckOutcome(
	candidate: UserAddedProduct,
	result: SessionResultsResponse,
): ListingCheckOutcome | null {
	if (!candidate.url || !candidate.research_attempted) return null;
	const snapshot = result.source_snapshots.find((source) => {
		const raw = source.provider.raw;
		return raw && typeof raw === 'object' && !Array.isArray(raw)
			? raw.user_added_candidate_id === candidate.candidate_id
			: false;
	});
	const listing = candidate.listing;
	if (listing) {
		const trust = result.trust_assessments.find((item) => item.listing_id === listing.listing_id);
		return {
			status: 'checked',
			title: listing.title,
			detail: 'CartCart found this listing. Check the seller and evidence before buying.',
			seller: listing.seller.seller_name,
			trust: trust?.summary ?? 'Seller safety is not confirmed.',
			url: candidate.url,
		};
	}
	if (
		candidate.possible_product_ids?.length
		|| (['succeeded', 'partial'].includes(snapshot?.extraction_status ?? '') && snapshot?.extracted_content)
	) {
		return {
			status: 'uncertain',
			title: 'The match is uncertain',
			detail: 'CartCart could read the page but could not confirm which product or offer it describes. You can try another listing.',
			seller: null,
			trust: null,
			url: candidate.url,
		};
	}
	return {
		status: 'unreadable',
		title: 'This link could not be checked',
		detail: 'CartCart could not read enough from this page. Try another listing link for the same product.',
		seller: null,
		trust: null,
		url: candidate.url,
	};
}
