import type {
	CreateUserAddedProductRequest,
	SessionResultsResponse,
	UserAddedProduct,
} from '$lib/api/types.js';

export type ManualFallbackReason = NonNullable<CreateUserAddedProductRequest['manual_fallback_reason']>;

export interface ManualCandidateView {
	candidate: UserAddedProduct;
	label: string;
	matchedName: string | null;
	reason: ManualFallbackReason | null;
}

export function manualCandidateViews(
	candidates: UserAddedProduct[],
	result: SessionResultsResponse,
): ManualCandidateView[] {
	return candidates.filter((candidate) => candidate.research_attempted).map((candidate) => {
		const snapshot = result.source_snapshots.find((source) => {
			const raw = source.provider.raw;
			return raw && typeof raw === 'object' && !Array.isArray(raw)
				? raw.user_added_candidate_id === candidate.candidate_id
				: false;
		});
		const unreadableUrl = candidate.url && !candidate.listing
			&& !candidate.possible_product_ids?.length
			&& !snapshot?.extracted_content;
		return {
			candidate,
			label: candidate.input_text || candidate.product?.name || candidate.url || 'Product you asked us to check',
			matchedName: candidate.listing ? candidate.product?.name ?? candidate.listing.title : null,
			reason: candidate.listing ? null : unreadableUrl ? 'retrieval_unavailable' : 'retrieval_insufficient',
		};
	});
}

export function manualFallbackRequest(
	candidate: UserAddedProduct,
	reason: ManualFallbackReason,
	values: {
		name: string;
		seller: string;
		price: string;
		currency: string;
		availability: string;
		review: string;
		warranty: string;
		specifications: string;
	},
): CreateUserAddedProductRequest | null {
	const name = values.name.trim();
	if (!name || name.length > 300) return null;
	const priceText = values.price.trim();
	const currency = values.currency.trim().toUpperCase();
	if (priceText && (!/^\d{1,10}(?:\.\d{1,2})?$/.test(priceText) || !/^[A-Z]{3}$/.test(currency))) return null;
	const detail = (value: string) => value.trim() || undefined;
	return {
		fallback_candidate_id: candidate.candidate_id,
		input_text: name,
		name,
		manual_fallback_reason: reason,
		manual_details: {
			...(detail(values.seller) && { seller: detail(values.seller) }),
			...(priceText && { price: { amount: priceText, currency } }),
			...(detail(values.availability) && { availability: detail(values.availability) }),
			...(detail(values.review) && { review: detail(values.review) }),
			...(detail(values.warranty) && { warranty: detail(values.warranty) }),
			...(detail(values.specifications) && { specifications: detail(values.specifications) }),
		},
	};
}
