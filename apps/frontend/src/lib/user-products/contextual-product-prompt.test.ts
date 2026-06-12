import { describe, expect, it } from 'vitest';
import {
	buildUserAddedProductRequestFromGuidedAnswer,
	buildUserAddedProductRequestFromPrompt,
	consideredProductPromptCanContinue,
	defaultConsideredProductPromptDraft,
	userAddedProductDetail,
	userAddedProductTitle,
} from './contextual-product-prompt.js';

describe('contextual considered-product prompt helpers', () => {
	it('builds a user-added product request from a product name or description', () => {
		const request = buildUserAddedProductRequestFromPrompt({
			text: '  ASUS ProArt PA278CV monitor  ',
		});

		expect(request).toEqual({
			input_text: 'ASUS ProArt PA278CV monitor',
			name: 'ASUS ProArt PA278CV monitor',
		});
	});

	it('keeps normal considered-product prompts away from URL-only input', () => {
		expect(consideredProductPromptCanContinue(defaultConsideredProductPromptDraft())).toBe(false);
		expect(consideredProductPromptCanContinue({ text: 'https://example.test/product' })).toBe(false);
		expect(() =>
			buildUserAddedProductRequestFromPrompt({ text: 'https://example.test/product' }),
		).toThrow('Use a product name or description instead of a link.');
	});

	it('builds product requests from guided natural-language answers', () => {
		expect(
			buildUserAddedProductRequestFromGuidedAnswer({
				answer_type: 'natural_language',
				text: 'I am considering the IKEA Bekant and FlexiSpot E7.',
			}),
		).toEqual({
			input_text: 'I am considering the IKEA Bekant and FlexiSpot E7.',
			name: 'I am considering the IKEA Bekant and FlexiSpot E7.',
		});

		expect(
			buildUserAddedProductRequestFromGuidedAnswer({
				answer_type: 'choice',
				choice_id: 'best-value',
			}),
		).toBeNull();
	});

	it('formats persisted user-added products without exposing link-first language', () => {
		const product = {
			schema_version: 1,
			candidate_id: 'candidate-1',
			input_text: 'ASUS ProArt PA278CV',
			url: null,
			product: {
				schema_version: 1,
				product_id: 'product-1',
				name: 'ASUS ProArt PA278CV',
				brand: 'ASUS',
				model: 'PA278CV',
				category: 'monitor',
				source_ids: [],
				listing_ids: [],
			},
			listing: null,
			notes: 'Compare for USB-C reliability',
			created_at: '2026-05-31T00:00:00Z',
		};

		expect(userAddedProductTitle(product)).toBe('ASUS ProArt PA278CV');
		expect(userAddedProductDetail(product)).toBe(
			'ASUS · PA278CV · monitor · Compare for USB-C reliability',
		);
	});
});
