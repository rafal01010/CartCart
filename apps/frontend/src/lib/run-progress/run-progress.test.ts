import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';
import ProcessingState from './ProcessingState.svelte';
import {
	applyRunEvent,
	createInitialRunProgress,
	isTerminalRunEvent,
	shopperProgressHeadline,
	shopperProgressFromEvents,
} from './run-progress.js';
import type { RunEvent } from '$lib/api/types.js';

describe('run progress helpers', () => {
	it('marks previous stages succeeded and current event stage running', () => {
		const progress = applyRunEvent(
			createInitialRunProgress(),
			runEvent({ stage: 'discovery', status: 'running', message: 'Searching sources.' }),
		);

		expect(progress.find((item) => item.stage === 'intake')?.status).toBe('succeeded');
		expect(progress.find((item) => item.stage === 'general_owner')?.status).toBe('succeeded');
		expect(progress.find((item) => item.stage === 'query_planning')?.status).toBe('succeeded');
		expect(progress.find((item) => item.stage === 'discovery')).toMatchObject({
			status: 'running',
			message: 'Searching sources.',
		});
		expect(progress.find((item) => item.stage === 'extraction')?.status).toBe('pending');
	});

	it('marks all stages complete when the complete event arrives', () => {
		const progress = applyRunEvent(
			createInitialRunProgress(),
			runEvent({ stage: 'complete', status: 'succeeded', message: 'Fixture shopping run completed.' }),
		);

		expect(progress.every((item) => item.status === 'succeeded')).toBe(true);
		expect(progress.at(-1)?.message).toBe('Fixture shopping run completed.');
	});

	it('keeps the failed stage visible and identifies terminal events', () => {
		const event = runEvent({
			stage: 'listing_trust',
			status: 'failed',
			message: 'Seller review failed.',
		});
		const progress = applyRunEvent(createInitialRunProgress(), event);

		expect(progress.find((item) => item.stage === 'listing_trust')).toMatchObject({
			status: 'failed',
			message: 'Seller review failed.',
		});
		expect(isTerminalRunEvent(event)).toBe(true);
	});
});

const fixtureStageEvents: Pick<RunEvent, 'stage' | 'status' | 'message'>[] = [
	{ stage: 'intake', status: 'running', message: 'Fixture intake stage recorded.' },
	{ stage: 'general_owner', status: 'running', message: 'Shopping request reviewed.' },
	{ stage: 'query_planning', status: 'running', message: 'Search queries planned.' },
	{ stage: 'discovery', status: 'running', message: 'Search provider discovery completed.' },
	{ stage: 'extraction', status: 'running', message: 'Shopping sources checked.' },
	{ stage: 'deduplication', status: 'running', message: 'Product candidates grouped.' },
	{ stage: 'source_intelligence', status: 'running', message: 'Reusable source evidence checked.' },
	{ stage: 'listing_trust', status: 'running', message: 'Seller and listing trust checked.' },
	{ stage: 'category_analysis', status: 'running', message: 'Fixture category analysis stage recorded.' },
	{ stage: 'comparison_decision', status: 'running', message: 'Fixture comparison decision stage recorded.' },
	{ stage: 'complete', status: 'succeeded', message: 'Fixture shopping run completed.' },
];
const fixtureEvents = fixtureStageEvents.map((event, index) => ({
	...runEvent(event), event_id: `event-${index + 1}`, sequence: index + 1,
}));

describe('shopper progress from observed events', () => {
	it('replays the actual fixture stage order without completing unseen seller checks', () => {
		const expected = [
			['running', 'pending', 'pending', 'pending', 'pending'],
			['running', 'pending', 'pending', 'pending', 'pending'],
			['running', 'pending', 'pending', 'pending', 'pending'],
			['running', 'pending', 'pending', 'pending', 'pending'],
			['running', 'pending', 'pending', 'pending', 'pending'],
			['running', 'pending', 'pending', 'pending', 'pending'],
			['succeeded', 'pending', 'running', 'pending', 'pending'],
			['succeeded', 'running', 'pending', 'pending', 'pending'],
			['succeeded', 'succeeded', 'running', 'pending', 'pending'],
			['succeeded', 'succeeded', 'running', 'pending', 'pending'],
			['succeeded', 'succeeded', 'succeeded', 'skipped', 'succeeded'],
		];
		for (const [index, statuses] of expected.entries()) {
			const progress = shopperProgressFromEvents(fixtureEvents.slice(0, index + 1));
			expect(progress.map((item) => item.status), `after ${fixtureEvents[index]?.stage}`).toEqual(statuses);
			expect(progress.filter((item) => item.status === 'running').length).toBeLessThanOrEqual(1);
		}
		expect(shopperProgressHeadline(shopperProgressFromEvents(fixtureEvents))).toBe('Your recommendation is ready.');
	});

	it('waits for all contributors before completing a group from explicit succeeded events', () => {
		const events = [
			runEvent({ stage: 'source_intelligence', status: 'succeeded', message: 'SourceIntelligenceAgent completed.' }),
			runEvent({ stage: 'category_analysis', status: 'succeeded', message: 'Fixture analysis completed.' }),
			runEvent({ stage: 'comparison_decision', status: 'succeeded', message: 'Fixture comparison completed.' }),
		];
		expect(shopperProgressFromEvents(events.slice(0, 1)).map((item) => item.status)).toEqual([
			'pending', 'pending', 'pending', 'pending', 'pending',
		]);
		expect(shopperProgressFromEvents(events.slice(0, 2)).map((item) => item.status)).toEqual([
			'pending', 'pending', 'pending', 'pending', 'pending',
		]);
		expect(shopperProgressFromEvents(events).map((item) => item.status)).toEqual([
			'pending', 'pending', 'succeeded', 'pending', 'pending',
		]);
	});

	it('settles only performed groups when a shortened run succeeds', () => {
		const progress = shopperProgressFromEvents([
			runEvent({ stage: 'comparison_decision', status: 'running', message: 'Comparing saved evidence.' }),
			runEvent({ stage: 'complete', status: 'succeeded', message: 'Finished.' }),
		]);
		expect(progress.map((item) => item.status)).toEqual([
			'skipped', 'skipped', 'succeeded', 'skipped', 'succeeded',
		]);
		expect(shopperProgressFromEvents([
			runEvent({ stage: 'complete', status: 'succeeded', message: 'Finished.' }),
		]).map((item) => item.status)).toEqual(['skipped', 'skipped', 'skipped', 'skipped', 'succeeded']);
	});

	it.each(['running', 'pending'] satisfies RunEvent['status'][])('does not treat complete/%s as terminal success', (status) => {
		const event = runEvent({ stage: 'complete', status, message: 'Still working.' });
		const progress = shopperProgressFromEvents([...fixtureEvents.slice(0, 8), event]);
		expect(isTerminalRunEvent(event)).toBe(false);
		expect(progress.map((item) => item.status)).toEqual([
			'succeeded', 'running', 'pending', 'pending', 'pending',
		]);
		expect(shopperProgressHeadline(progress)).toBe('Checking risky listings');
	});

	it.each(['failed', 'cancelled'] satisfies RunEvent['status'][])('clears active work on terminal %s without inventing success', (status) => {
		const event = runEvent({ stage: 'complete', status, message: 'Provider internal trace failure.' });
		const progress = shopperProgressFromEvents([...fixtureEvents.slice(0, 8), event]);
		expect(isTerminalRunEvent(event)).toBe(true);
		expect(progress.map((item) => item.status)).toEqual([
			'succeeded', 'skipped', 'skipped', 'skipped', 'failed',
		]);
		expect(progress.some((item) => item.status === 'running')).toBe(false);
		expect(shopperProgressHeadline(progress)).toBe('CartCart could not finish checking options.');
		expect(progress.map((item) => item.message).join(' ')).not.toContain('Provider internal trace failure.');
	});

	it('clears a preceding active group when a different stage fails', () => {
		const progress = shopperProgressFromEvents([
			...fixtureEvents.slice(0, 8),
			runEvent({ stage: 'category_analysis', status: 'failed', message: 'Internal failure.' }),
		]);
		expect(progress.map((item) => item.status)).toEqual([
			'succeeded', 'skipped', 'failed', 'skipped', 'skipped',
		]);
		expect(progress.filter((item) => item.status === 'failed').map((item) => item.kind)).toEqual(['comparing_evidence']);
		expect(progress[1]?.message).toBe('This check was not completed.');
	});

	it.each(['failed', 'cancelled'] satisfies RunEvent['status'][])('marks only the current check failed on %s', (status) => {
		const progress = shopperProgressFromEvents([
			...fixtureEvents.slice(0, 8),
			runEvent({ stage: 'listing_trust', status, message: 'Internal failure.' }),
		]);
		expect(progress.map((item) => item.status)).toEqual([
			'succeeded', 'failed', 'skipped', 'skipped', 'skipped',
		]);
		expect(progress.filter((item) => item.status === 'failed').map((item) => item.kind)).toEqual(['verifying_risky_listings']);
	});

	it('keeps empty history pending and ignores events after a terminal result', () => {
		expect(shopperProgressFromEvents([]).map((item) => item.status)).toEqual([
			'pending', 'pending', 'pending', 'pending', 'pending',
		]);
		expect(shopperProgressFromEvents([
			...fixtureEvents,
			runEvent({ stage: 'verification', status: 'running', message: 'Late event.' }),
		])).toEqual(shopperProgressFromEvents(fixtureEvents));
	});
});

describe('processing display', () => {
	it('shows the actual failing check after a different active check was interrupted', () => {
		const progress = shopperProgressFromEvents([
			...fixtureEvents.slice(0, 8),
			runEvent({ stage: 'category_analysis', status: 'failed', message: 'Provider internal trace failure.' }),
		]);
		const output = render(ProcessingState, { props: {
			question: 'Find a monitor for my desk.', headline: shopperProgressHeadline(progress),
			progress, error: 'CartCart could not finish checking options. Try again.', onRetry: () => {},
		} }).body.replace(/<!--[\s\S]*?-->/g, '');
		expect(output).toContain('Comparing evidence');
		expect(output).toContain('1 of 4 checks complete');
		expect(output).toContain('CartCart could not finish this check. Try again.');
		expect(output).not.toContain('Checking risky listings');
		expect(output).not.toContain('Provider internal trace failure.');
	});

	it.each([
		{ count: 7, label: 'Comparing evidence', completed: '1 of 4 checks complete' },
		{ count: 8, label: 'Checking risky listings', completed: '1 of 4 checks complete' },
		{ count: 9, label: 'Comparing evidence', completed: '2 of 4 checks complete' },
		{ count: 11, label: 'Recommendation ready', completed: '3 of 4 checks complete' },
	])('renders truthful counts after $count fixture events', ({ count, label, completed }) => {
		const progress = shopperProgressFromEvents(fixtureEvents.slice(0, count));
		const output = render(ProcessingState, { props: {
			question: 'Find a monitor for my desk.', headline: shopperProgressHeadline(progress),
			progress, onRetry: () => {},
		} }).body.replace(/<!--[\s\S]*?-->/g, '');
		expect(output).toContain(label);
		expect(output).toContain(completed);
		expect(output).not.toMatch(/fixture|GeneralShoppingAgent|source_intelligence|listing_trust|provider|trace/i);
	});
});

function runEvent(overrides: Pick<RunEvent, 'stage' | 'status' | 'message'>): RunEvent {
	return {
		schema_version: 1,
		event_id: 'event-1',
		run_id: 'run-1',
		sequence: 1,
		occurred_at: '2026-05-31T00:00:00Z',
		...overrides,
	};
}
