import { describe, expect, it } from 'vitest';
import { decisionContext } from './decision-history.js';
import type { ShoppingBrief } from '$lib/api/types.js';

const brief: ShoppingBrief = {
	schema_version: 1,
	original_query: 'Which monitor should I buy?',
	category: 'monitor',
	constraints: [],
	preferences: [],
};

describe('decision history context', () => {
	it('shows the saved budget, buying region, and requirements in shopper language', () => {
		expect(decisionContext({
			...brief,
			region: { region: { country_code: 'CA' }, source: 'user_provided' },
			budget: { amount: { amount: '400', currency: 'CAD' }, mode: 'hard_cap' },
			preferences: [{ text: 'easy returns', mode: 'soft' }],
		})).toBe('monitor · Canada · CAD 400 maximum · easy returns');
	});
	it('keeps an assumed region distinct and omits unknown budget facts', () => {
		expect(decisionContext({ ...brief, region: { region: { country_code: 'US' }, source: 'defaulted' } }))
			.toBe('monitor · United States (assumed region)');
	});
	it('uses the saved question when the context has no known details', () => {
		expect(decisionContext({ ...brief, category: null })).toBe(brief.original_query);
	});
});
