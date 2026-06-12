import { describe, expect, it } from 'vitest';
import {
	applyShopperProgressEvent,
	applyRunEvent,
	createInitialRunProgress,
	createInitialShopperProgress,
	isTerminalRunEvent,
	shopperProgressHeadline,
} from './run-progress.js';
import type { RunEvent } from '$lib/api/types.js';

describe('run progress helpers', () => {
	it('marks previous stages succeeded and current event stage running', () => {
		const progress = applyRunEvent(
			createInitialRunProgress(),
			runEvent({ stage: 'discovery', status: 'running', message: 'Searching sources.' }),
		);

		expect(progress.find((item) => item.stage === 'intake')?.status).toBe('succeeded');
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

	it('maps technical run stages to shopper-safe progress copy', () => {
		let progress = createInitialShopperProgress();

		progress = applyShopperProgressEvent(
			progress,
			runEvent({
				stage: 'discovery',
				status: 'running',
				message: 'Fixture discovery stage recorded.',
			}),
		);
		progress = applyShopperProgressEvent(
			progress,
			runEvent({
				stage: 'listing_trust',
				status: 'running',
				message: 'Fixture listing trust stage recorded.',
			}),
		);

		expect(shopperProgressHeadline(progress)).toBe('Checking risky listings');
		expect(progress.map((item) => item.label)).toEqual([
			'Checking options',
			'Checking risky listings',
			'Comparing evidence',
			'Preparing recommendation',
			'Recommendation ready',
		]);
		expect(progress.map((item) => `${item.label} ${item.message}`).join(' ')).not.toMatch(
			/fixture|run|stage|agent|provider|trace/i,
		);
	});

	it('shows a ready headline when the final event arrives', () => {
		const progress = applyShopperProgressEvent(
			createInitialShopperProgress(),
			runEvent({ stage: 'complete', status: 'succeeded', message: 'Fixture shopping run completed.' }),
		);

		expect(shopperProgressHeadline(progress)).toBe('Your recommendation is ready.');
		expect(progress.every((item) => item.status === 'succeeded')).toBe(true);
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
