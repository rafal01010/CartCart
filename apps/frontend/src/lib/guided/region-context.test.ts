import { describe, expect, it } from 'vitest';
import type { GuidedIntakeState, ShoppingBrief } from '$lib/api/types.js';
import { regionByCode } from '$lib/session/session-form.js';
import { regionContextLabel } from './region-context.js';

const usBrief: ShoppingBrief = {
	schema_version: 1,
	original_query: 'A monitor for work',
	region: { source: 'user_provided', region: { country_code: 'US', currency: 'USD' } },
	constraints: [],
	preferences: [],
};
const phPreference = { status: 'provided', region: regionByCode('PH') } satisfies NonNullable<Parameters<typeof regionContextLabel>[0]['preference']>;

function context(overrides: Partial<Parameters<typeof regionContextLabel>[0]> = {}): Parameters<typeof regionContextLabel>[0] {
	return { decisionBrief: undefined, sessionBrief: undefined, guide: null, preference: phPreference, ...overrides };
}

describe('buying region labels', () => {
	it('keeps a saved decision region above later session and future preferences', () => {
		expect(regionContextLabel(context({ decisionBrief: usBrief, sessionBrief: { ...usBrief, region: null } }))).toBe('United States');
	});

	it('keeps absent saved region explicit instead of borrowing a future preference', () => {
		expect(regionContextLabel(context({ decisionBrief: { ...usBrief, region: null }, sessionBrief: usBrief }))).toBe('Region not set');
		expect(regionContextLabel(context({ decisionBrief: null, sessionBrief: usBrief }))).toBe('Region not set');
	});

	it('uses the accepted session region before the future preference', () => {
		expect(regionContextLabel(context({ sessionBrief: usBrief }))).toBe('United States');
		expect(regionContextLabel(context({ sessionBrief: { ...usBrief, region: null } }))).toBe('Region not set');
	});

	it('uses active guided region and retains explicit refusal', () => {
		const guide: GuidedIntakeState = {
			schema_version: 1,
			status: 'collecting',
			current_question: { schema_version: 1, question_id: 'budget', text: 'Your budget?', purpose: 'budget', answer_surface: 'textbox', capture_targets: ['budget'] },
			navigation: { can_go_back: false, reanswerable_questions: [] },
			skippable_question: { can_skip: true, label: 'Skip question' },
			analysis_start: { enough_information: true, can_skip_all_and_start_analysis: true, label: 'Skip all and start analysis' },
			region_setup: { status: 'provided', region: { country_code: 'US', currency: 'USD' }, can_refuse: true, resumes_pending_question: true },
		};
		expect(regionContextLabel(context({ guide }))).toBe('United States');
		expect(regionContextLabel(context({ guide: { ...guide, region_setup: { status: 'refused', can_refuse: true, resumes_pending_question: true } } }))).toBe('Region not set');
	});

	it('uses the future preference only without active context', () => {
		expect(regionContextLabel(context())).toBe('Philippines');
		expect(regionContextLabel(context({ preference: { status: 'refused' } }))).toBe('Region not set');
		expect(regionContextLabel(context({ preference: null }))).toBe('Set buying region');
	});
});
