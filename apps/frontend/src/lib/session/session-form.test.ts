import { describe, expect, it } from 'vitest';
import {
	buildCreateSessionRequest,
	defaultSessionFormState,
	parseBudget,
	REGION_OPTIONS,
	regionByCode,
	sessionFormStateFromResponse,
	shortSessionId,
} from './session-form.js';
import type { SessionStateResponse } from '$lib/api/types.js';

describe('session form helpers', () => {
	it('builds a create-session request with region, budget, and preferences', () => {
		const request = buildCreateSessionRequest({
			query: '  Reliable monitor for coding  ',
			regionCode: 'GB',
			currency: 'gbp',
			budget: '$450',
			budgetMode: 'hard_cap',
			priorities: 'text clarity, reliable seller',
		});

		expect(request).toEqual({
			query: 'Reliable monitor for coding',
			region: {
				region: {
					country_code: 'GB',
					currency: 'GBP',
					locale: 'en-GB',
				},
				source: 'user_provided',
			},
			budget: {
				amount: {
					amount: 450,
					currency: 'GBP',
				},
				mode: 'hard_cap',
				source: 'user_provided',
			},
			preferences: [
				{
					text: 'text clarity, reliable seller',
					mode: 'soft',
					source: 'user_provided',
				},
			],
			constraints: [],
		});
	});

	it('hydrates form state from a persisted session response', () => {
		const session: SessionStateResponse = {
			schema_version: 1,
			session_id: '12345678-1234-1234-1234-123456789abc',
			original_input: { query: 'monitor' },
			current_brief: {
				schema_version: 1,
				original_query: 'monitor',
				region: {
					region: { country_code: 'CA', currency: 'CAD', locale: 'en-CA' },
					source: 'user_provided',
				},
				budget: {
					amount: { amount: '399.00', currency: 'CAD' },
					mode: 'preferred',
					source: 'user_provided',
				},
				constraints: [],
				preferences: [{ text: 'USB-C', mode: 'soft', source: 'user_provided' }],
			},
			created_at: '2026-05-31T00:00:00Z',
			updated_at: '2026-05-31T00:00:00Z',
			user_added_products: [],
		};

		expect(sessionFormStateFromResponse(session)).toMatchObject({
			query: 'monitor',
			regionCode: 'CA',
			currency: 'CAD',
			budget: '399.00',
			budgetMode: 'preferred',
			priorities: 'USB-C',
		});
	});

	it('keeps optional budget empty when input is blank or invalid', () => {
		expect(parseBudget('')).toBeNull();
		expect(parseBudget('not a number')).toBeNull();
		expect(parseBudget('1,299.50')).toBe(1299.5);
	});

	it('shortens long session IDs for display', () => {
		expect(shortSessionId('12345678-1234')).toBe('12345678');
		expect(shortSessionId('abc')).toBe('abc');
		expect(defaultSessionFormState().regionCode).toBe('US');
	});

	it('builds a complete region list from ISO codes and CLDR display names', () => {
		expect(REGION_OPTIONS.length).toBeGreaterThan(200);
		expect(regionByCode('PH')).toMatchObject({
			code: 'PH',
			label: 'Philippines',
			currency: 'PHP',
			locale: 'en-PH',
		});
		expect(regionByCode('JP')).toMatchObject({
			code: 'JP',
			label: 'Japan',
			currency: 'JPY',
			locale: 'ja-JP',
		});
	});
});
