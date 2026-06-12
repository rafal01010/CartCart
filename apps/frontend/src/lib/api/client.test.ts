import { describe, expect, it } from 'vitest';
import { ApiError } from './errors.js';
import { CartCartApiClient } from './client.js';
import { normalizeBackendBaseUrl } from './config.js';
import { subscribeToRunEvents } from './sse.js';
import type { FetchLike } from './client.js';
import type { RunEvent } from './types.js';

describe('frontend API client', () => {
	it('normalizes backend base URLs', () => {
		expect(normalizeBackendBaseUrl(' http://localhost:8000/// ')).toBe('http://localhost:8000');
		expect(normalizeBackendBaseUrl('')).toBe('http://127.0.0.1:8000');
	});

	it('posts JSON and returns typed session state', async () => {
		const responseBody = {
			schema_version: 1,
			session_id: 'session-1',
			original_input: { query: 'monitor for coding' },
			current_brief: {
				schema_version: 1,
				original_query: 'monitor for coding',
				constraints: [],
				preferences: [],
			},
			created_at: '2026-05-31T00:00:00Z',
			updated_at: '2026-05-31T00:00:00Z',
			user_added_products: [],
		};
		const fetchImpl: FetchLike = async (input, init) => {
			expect(String(input)).toBe('http://api.test/api/sessions');
			expect(init?.method).toBe('POST');
			expect((init?.headers as Headers).get('Content-Type')).toBe('application/json');
			expect(JSON.parse(String(init?.body))).toEqual({ query: 'monitor for coding' });
			return new Response(JSON.stringify(responseBody), {
				status: 201,
				headers: { 'Content-Type': 'application/json' },
			});
		};

		const client = new CartCartApiClient({ baseUrl: 'http://api.test', fetch: fetchImpl });
		const session = await client.createSession({ query: 'monitor for coding' });

		expect(session.session_id).toBe('session-1');
		expect(session.current_brief.original_query).toBe('monitor for coding');
	});

	it('turns backend error envelopes into ApiError instances', async () => {
		const fetchImpl: FetchLike = async () =>
			new Response(
				JSON.stringify({
					error: {
						code: 'result_not_ready',
						message: 'Result is not ready.',
						request_id: 'request-1',
						details: { session_id: 'session-1' },
					},
				}),
				{ status: 404, headers: { 'Content-Type': 'application/json' } },
			);
		const client = new CartCartApiClient({ baseUrl: 'http://api.test', fetch: fetchImpl });

		await expect(client.getResults('session-1')).rejects.toMatchObject({
			name: 'ApiError',
			status: 404,
			code: 'result_not_ready',
			requestId: 'request-1',
		} satisfies Partial<ApiError>);
	});

	it('posts user-added products to the session product endpoint', async () => {
		const responseBody = {
			schema_version: 1,
			session_id: 'session-1',
			original_input: { query: 'monitor for coding' },
			current_brief: {
				schema_version: 1,
				original_query: 'monitor for coding',
				constraints: [],
				preferences: [],
			},
			created_at: '2026-05-31T00:00:00Z',
			updated_at: '2026-05-31T00:00:00Z',
			user_added_products: [
				{
					schema_version: 1,
					candidate_id: 'candidate-1',
					input_text: null,
					url: 'https://example.test/product',
					product: null,
					listing: null,
					notes: null,
					created_at: '2026-05-31T00:00:00Z',
				},
			],
		};
		const fetchImpl: FetchLike = async (input, init) => {
			expect(String(input)).toBe('http://api.test/api/sessions/session-1/products');
			expect(init?.method).toBe('POST');
			expect(JSON.parse(String(init?.body))).toEqual({ url: 'https://example.test/product' });
			return new Response(JSON.stringify(responseBody), {
				status: 201,
				headers: { 'Content-Type': 'application/json' },
			});
		};
		const client = new CartCartApiClient({ baseUrl: 'http://api.test', fetch: fetchImpl });

		const session = await client.addUserProduct('session-1', {
			url: 'https://example.test/product',
		});

		expect(session.user_added_products).toHaveLength(1);
		expect(session.user_added_products[0]?.url).toBe('https://example.test/product');
	});

	it('posts refinements to the session refinement endpoint', async () => {
		const responseBody = {
			refinement: {
				schema_version: 1,
				refinement_id: 'refinement-1',
				session_id: 'session-1',
				run_id: 'run-2',
				instruction: 'Prefer cheaper options.',
				preferences: [],
				constraints: [],
				created_at: '2026-05-31T00:00:00Z',
			},
			run: {
				schema_version: 1,
				run_id: 'run-2',
				session_id: 'session-1',
				status: 'succeeded',
				current_stage: 'complete',
				created_at: '2026-05-31T00:00:00Z',
				started_at: '2026-05-31T00:00:00Z',
				completed_at: '2026-05-31T00:00:01Z',
			},
		};
		const fetchImpl: FetchLike = async (input, init) => {
			expect(String(input)).toBe('http://api.test/api/sessions/session-1/refinements');
			expect(init?.method).toBe('POST');
			expect(JSON.parse(String(init?.body))).toEqual({
				instruction: 'Prefer cheaper options.',
				preferences: [],
				constraints: [],
			});
			return new Response(JSON.stringify(responseBody), {
				status: 201,
				headers: { 'Content-Type': 'application/json' },
			});
		};
		const client = new CartCartApiClient({ baseUrl: 'http://api.test', fetch: fetchImpl });

		const refinement = await client.createRefinement('session-1', {
			instruction: 'Prefer cheaper options.',
			preferences: [],
			constraints: [],
		});

		expect(refinement.refinement.run_id).toBe('run-2');
		expect(refinement.run.status).toBe('succeeded');
	});

	it('calls guided intake endpoints with user-facing payloads', async () => {
		const calls: Array<{ url: string; method?: string; body?: unknown }> = [];
		const guide = {
			schema_version: 1,
			status: 'collecting',
			current_question: {
				schema_version: 1,
				question_id: 'optional-context',
				text: 'Anything we should keep in mind?',
				purpose: 'combined_optional',
				answer_surface: 'textbox',
				capture_targets: ['budget'],
			},
			navigation: { can_go_back: false, reanswerable_questions: [] },
			skippable_question: { can_skip: true, label: 'Skip question' },
			analysis_start: {
				enough_information: true,
				can_skip_all_and_start_analysis: true,
				label: 'Skip all and start analysis',
			},
			region_setup: { status: 'refused', can_refuse: true, resumes_pending_question: true },
		};
		const fetchImpl: FetchLike = async (input, init) => {
			calls.push({
				url: String(input),
				method: init?.method,
				body: init?.body ? JSON.parse(String(init.body)) : undefined,
			});
			if (String(input).endsWith('/guided')) {
				return Response.json({ schema_version: 1, session_id: 'session-1', guide }, { status: 201 });
			}
			return Response.json(guide);
		};
		const client = new CartCartApiClient({ baseUrl: 'http://api.test', fetch: fetchImpl });

		await client.createGuidedSession({
			query: 'Which desk should I buy?',
			region_setup: { status: 'refused' },
		});
		await client.submitGuidedAnswer('session-1', {
			question_id: 'optional-context',
			answer: { answer_type: 'natural_language', text: 'Under $300.' },
		});
		await client.skipGuidedQuestion('session-1');
		await client.skipAllGuidedQuestions('session-1');
		await client.reanswerGuidedQuestion('session-1', { question_id: 'optional-context' });
		await client.submitGuidedRegionSetup('session-1', {
			status: 'provided',
			region: { country_code: 'US', currency: 'USD', locale: 'en-US' },
		});

		expect(calls).toEqual([
			{
				url: 'http://api.test/api/sessions/guided',
				method: 'POST',
				body: {
					query: 'Which desk should I buy?',
					region_setup: { status: 'refused' },
				},
			},
			{
				url: 'http://api.test/api/sessions/session-1/answers',
				method: 'POST',
				body: {
					question_id: 'optional-context',
					answer: { answer_type: 'natural_language', text: 'Under $300.' },
				},
			},
			{
				url: 'http://api.test/api/sessions/session-1/guide/skip',
				method: 'POST',
				body: undefined,
			},
			{
				url: 'http://api.test/api/sessions/session-1/guide/skip-all',
				method: 'POST',
				body: undefined,
			},
			{
				url: 'http://api.test/api/sessions/session-1/guide/reanswer',
				method: 'POST',
				body: { question_id: 'optional-context' },
			},
			{
				url: 'http://api.test/api/sessions/session-1/guide/region',
				method: 'POST',
				body: {
					status: 'provided',
					region: { country_code: 'US', currency: 'USD', locale: 'en-US' },
				},
			},
		]);
	});

	it('subscribes to named run_event SSE messages', () => {
		let source: FakeEventSource | undefined;
		const received: RunEvent[] = [];
		class CapturingEventSource extends FakeEventSource {
			constructor(url: string) {
				super(url);
				source = this;
			}
		}

		const subscription = subscribeToRunEvents(
			{ sessionId: 'session-1', runId: 'run-1' },
			{
				baseUrl: 'http://api.test',
				eventSource: CapturingEventSource,
				onEvent: (event) => received.push(event),
			},
		);

		expect(subscription.url).toBe('http://api.test/api/sessions/session-1/runs/run-1/events');
		source?.emit('run_event', {
			schema_version: 1,
			event_id: 'event-1',
			run_id: 'run-1',
			sequence: 1,
			stage: 'complete',
			status: 'succeeded',
			message: 'Result ready.',
			occurred_at: '2026-05-31T00:00:00Z',
		});
		subscription.close();

		expect(received).toHaveLength(1);
		expect(received[0]?.stage).toBe('complete');
		expect(source?.closed).toBe(true);
	});
});

class FakeEventSource {
	readonly url: string;
	closed = false;
	private readonly listeners = new Map<string, ((event: MessageEvent) => void)[]>();

	constructor(url: string) {
		this.url = url;
	}

	addEventListener(type: string, listener: (event: MessageEvent) => void): void {
		this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
	}

	close(): void {
		this.closed = true;
	}

	emit(type: string, event: RunEvent): void {
		for (const listener of this.listeners.get(type) ?? []) {
			listener({ data: JSON.stringify(event) } as MessageEvent);
		}
	}
}
