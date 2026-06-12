import type {
	CreateUserAddedProductRequest,
	GuidedAnswer,
	UserAddedProduct,
} from '$lib/api/types.js';

const URL_PATTERN = /https?:\/\/\S+|www\.\S+/i;

export interface ConsideredProductPromptDraft {
	text: string;
}

export function defaultConsideredProductPromptDraft(): ConsideredProductPromptDraft {
	return { text: '' };
}

export function consideredProductPromptCanContinue(draft: ConsideredProductPromptDraft): boolean {
	return draft.text.trim().length > 0 && !isUrlOnlyText(draft.text);
}

export function buildUserAddedProductRequestFromPrompt(
	draft: ConsideredProductPromptDraft,
): CreateUserAddedProductRequest {
	const inputText = normalizePromptText(draft.text);
	if (!inputText) {
		throw new Error('Enter the product name or description.');
	}
	if (isUrlOnlyText(inputText)) {
		throw new Error('Use a product name or description instead of a link.');
	}
	return {
		input_text: inputText,
		name: inputText,
	};
}

export function buildUserAddedProductRequestFromGuidedAnswer(
	answer: GuidedAnswer,
): CreateUserAddedProductRequest | null {
	const text = guidedAnswerText(answer);
	if (!text || isUrlOnlyText(text)) return null;
	return {
		input_text: text,
		name: text,
	};
}

export function userAddedProductTitle(product: UserAddedProduct): string {
	return product.product?.name ?? product.input_text ?? 'Product you mentioned';
}

export function userAddedProductDetail(product: UserAddedProduct): string {
	const pieces = [
		product.product?.brand,
		product.product?.model,
		product.product?.category,
		product.notes,
		product.url ? 'Listing will be checked separately' : null,
	].filter((piece): piece is string => Boolean(piece?.trim()));

	return pieces.join(' · ') || 'Added from your answer';
}

function guidedAnswerText(answer: GuidedAnswer): string | null {
	if (answer.answer_type === 'natural_language' || answer.answer_type === 'choice_with_text') {
		return normalizePromptText(answer.text);
	}
	return null;
}

function normalizePromptText(value: string): string {
	return value.trim().replace(/\s+/g, ' ');
}

function isUrlOnlyText(value: string): boolean {
	const trimmed = normalizePromptText(value);
	return URL_PATTERN.test(trimmed) && trimmed.replace(URL_PATTERN, '').trim().length === 0;
}
