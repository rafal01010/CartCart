import { describe, expect, it } from 'vitest';
import {
	buildRefinementRequestFromPrompt,
	refinementDraftFromSession,
	refinementPromptCanContinue,
	refinementPromptSpec,
} from './contextual-refinement-prompt.js';
import type { SessionStateResponse } from '$lib/api/types.js';

const session: SessionStateResponse = {
	schema_version: 1,
	session_id: 'session-1',
	original_input: { query: 'monitor' },
	current_brief: {
		schema_version: 1,
		original_query: 'monitor',
		category: 'display',
		category_source: 'inferred',
		region: {
			region: { country_code: 'GB', currency: 'GBP', locale: 'en-GB' },
			source: 'user_provided',
		},
		budget: {
			amount: { amount: '300', currency: 'GBP' },
			mode: 'preferred',
			source: 'user_provided',
		},
		constraints: [],
		preferences: [{ text: 'flat panel', mode: 'soft', source: 'user_provided' }],
	},
	created_at: '2026-05-31T00:00:00Z',
	updated_at: '2026-05-31T00:00:00Z',
	user_added_products: [],
};

describe('contextual refinement prompt helpers', () => {
	it('describes single-purpose prompts instead of a permanent refinement form', () => {
		expect(refinementPromptSpec('category')).toEqual({
			kind: 'category',
			question: 'What kind of product should CartCart compare instead?',
			placeholder: 'Type the corrected category.',
			usesRegionChoice: false,
		});
		expect(refinementPromptSpec('region').usesRegionChoice).toBe(true);
	});

	it('prefills only contextual defaults from the loaded session', () => {
		expect(refinementDraftFromSession('budget', session)).toEqual({
			kind: 'budget',
			text: '',
			regionCode: 'GB',
			currency: 'GBP',
			budgetMode: 'preferred',
		});
	});

	it('builds a budget refinement from one answer', () => {
		const request = buildRefinementRequestFromPrompt({
			...refinementDraftFromSession('budget', session),
			text: '450',
			budgetMode: 'hard_cap',
		});

		expect(request.instruction).toBe('Use a hard budget of GBP 450.');
		expect(request.budget?.amount.amount).toBe(450);
		expect(request.budget?.amount.currency).toBe('GBP');
		expect(request.budget?.mode).toBe('hard_cap');
	});

	it('builds a region refinement from an inline region choice', () => {
		const request = buildRefinementRequestFromPrompt({
			...refinementDraftFromSession('region', session),
			regionCode: 'CA',
			text: 'prefer stores with easy returns',
		});

		expect(request.instruction).toBe(
			'Use Canada results. Also keep in mind: prefer stores with easy returns.',
		);
		expect(request.region?.region.country_code).toBe('CA');
		expect(request.region?.region.currency).toBe('CAD');
	});

	it('builds a category correction without adding a multi-field edit panel', () => {
		const draft = {
			...refinementDraftFromSession('category', session),
			text: 'office chair',
		};

		expect(refinementPromptCanContinue(draft)).toBe(true);
		expect(buildRefinementRequestFromPrompt(draft)).toEqual({
			instruction: 'Compare office chair instead.',
			constraints: [],
			preferences: [
				{
					text: 'Correct product category: office chair',
					mode: 'soft',
					source: 'user_provided',
				},
			],
		});
	});

	it('requires the current contextual prompt to be answered', () => {
		expect(refinementPromptCanContinue(refinementDraftFromSession('budget', session))).toBe(false);
		expect(() => buildRefinementRequestFromPrompt(refinementDraftFromSession('budget', session))).toThrow(
			'Answer the current refinement prompt',
		);
	});
});
