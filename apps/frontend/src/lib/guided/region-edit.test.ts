import { describe, expect, it } from 'vitest';
import { CartCartApiClient } from '$lib/api/client.js';
import type { GuidedIntakeState } from '$lib/api/types.js';
import { regionByCode } from '$lib/session/session-form.js';
import { applyRegionEdit } from './region-edit.js';
import { readLocalRegionPreference, writeProvidedRegionPreference } from './local-region.js';

class MemoryStorage implements Storage {
	private values = new Map<string, string>();
	get length(): number { return this.values.size; }
	clear(): void { this.values.clear(); }
	getItem(key: string): string | null { return this.values.get(key) ?? null; }
	key(index: number): string | null { return Array.from(this.values.keys())[index] ?? null; }
	removeItem(key: string): void { this.values.delete(key); }
	setItem(key: string, value: string): void { this.values.set(key, value); }
}

const guide: GuidedIntakeState = {
	schema_version: 1,
	status: 'collecting',
	current_question: { schema_version: 1, question_id: 'budget', text: 'Your budget?', purpose: 'budget', answer_surface: 'textbox', capture_targets: ['budget'] },
	navigation: { can_go_back: false, reanswerable_questions: [] },
	skippable_question: { can_skip: true, label: 'Skip question' },
	analysis_start: { enough_information: true, can_skip_all_and_start_analysis: true, label: 'Skip all and start analysis' },
	region_setup: { status: 'provided', region: { country_code: 'PH', currency: 'PHP' }, can_refuse: true, resumes_pending_question: true },
};
const phPreference = { status: 'provided', region: regionByCode('PH') } satisfies Parameters<typeof applyRegionEdit>[0]['preference'];

function response(value: unknown, status = 200): Response {
	return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('region editing through the API client', () => {
	it('waits for the active session update before storing the accepted preference', async () => {
		const storage = new MemoryStorage();
		writeProvidedRegionPreference(storage, 'US');
		let release: (value: Response) => void = () => { throw new Error('Request has not started.'); };
		let payload: unknown = null;
		const api = new CartCartApiClient({ baseUrl: 'http://api.test', fetch: async (input, init) => {
			expect(String(input)).toBe('http://api.test/api/sessions/session-1/guide/region');
			payload = JSON.parse(String(init?.body));
			return await new Promise<Response>((resolve) => { release = resolve; });
		} });
		const pending = applyRegionEdit({ preference: phPreference, context: { kind: 'guided', sessionId: 'session-1', api }, storage, isCurrent: () => true });
		expect(readLocalRegionPreference(storage)?.status).toBe('provided');
		expect(readLocalRegionPreference(storage)).toMatchObject({ region: { code: 'US' } });
		release(response(guide));
		const accepted = await pending;
		expect(payload).toEqual({ status: 'provided', region: { country_code: 'PH', currency: 'PHP', locale: 'en-PH' } });
		expect(accepted).toEqual({ preference: phPreference, guide });
		expect(readLocalRegionPreference(storage)).toMatchObject({ status: 'provided', region: { code: 'PH' } });
	});

	it('leaves the accepted preference intact on a failed session update', async () => {
		const storage = new MemoryStorage();
		writeProvidedRegionPreference(storage, 'US');
		const api = new CartCartApiClient({ baseUrl: 'http://api.test', fetch: async () => response({ error: { code: 'guided_intake_not_collecting', message: 'This shopping question is not waiting for another answer.', request_id: 'request-1' } }, 409) });
		await expect(applyRegionEdit({ preference: phPreference, context: { kind: 'guided', sessionId: 'session-1', api }, storage, isCurrent: () => true })).rejects.toMatchObject({ status: 409, code: 'guided_intake_not_collecting' });
		expect(readLocalRegionPreference(storage)).toMatchObject({ status: 'provided', region: { code: 'US' } });
	});

	it('submits refusal even when the active context already has a region', async () => {
		const storage = new MemoryStorage();
		writeProvidedRegionPreference(storage, 'US');
		const refusedGuide: GuidedIntakeState = { ...guide, region_setup: { status: 'refused', can_refuse: true, resumes_pending_question: true } };
		let payload: unknown = null;
		const api = new CartCartApiClient({ baseUrl: 'http://api.test', fetch: async (_input, init) => { payload = JSON.parse(String(init?.body)); return response(refusedGuide); } });
		const accepted = await applyRegionEdit({ preference: { status: 'refused' }, context: { kind: 'guided', sessionId: 'session-1', api }, storage, isCurrent: () => true });
		expect(payload).toEqual({ status: 'refused' });
		expect(accepted?.guide?.region_setup.status).toBe('refused');
		expect(readLocalRegionPreference(storage)).toEqual({ status: 'refused' });
	});

	it('ignores a late response after its shopping flow was abandoned', async () => {
		const storage = new MemoryStorage();
		writeProvidedRegionPreference(storage, 'US');
		const api = new CartCartApiClient({ baseUrl: 'http://api.test', fetch: async () => response(guide) });
		const accepted = await applyRegionEdit({ preference: phPreference, context: { kind: 'guided', sessionId: 'session-1', api }, storage, isCurrent: () => false });
		expect(accepted).toBeNull();
		expect(readLocalRegionPreference(storage)).toMatchObject({ status: 'provided', region: { code: 'US' } });
	});

	it('saves a future preference without changing a completed decision', async () => {
		const storage = new MemoryStorage();
		const accepted = await applyRegionEdit({ preference: phPreference, context: { kind: 'future' }, storage, isCurrent: () => true });
		expect(accepted).toEqual({ preference: phPreference, guide: null });
		expect(readLocalRegionPreference(storage)).toMatchObject({ status: 'provided', region: { code: 'PH' } });
	});
});
