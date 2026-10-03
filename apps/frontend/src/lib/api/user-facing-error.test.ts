import { describe, expect, it } from 'vitest';
import { ApiError } from './errors.js';
import { userFacingErrorMessage } from './user-facing-error.js';

describe('research errors', () => {
	it.each([
		['research_mode_mismatch', 'CartCart is using sample-data mode with live research settings. Enable live research or use sample data, then restart the app.'],
		['live_agents_not_configured', 'Live research is not ready. Check the local research configuration and restart CartCart.'],
		['network_error', 'CartCart could not connect. Check your connection and try again.'],
	])('explains %s without exposing internal error text', (code, expected) => {
		expect(userFacingErrorMessage(new ApiError({ status: 409, code, message: 'Internal diagnostic' }))).toBe(expected);
	});

	it('keeps unknown error details private', () => {
		expect(userFacingErrorMessage(new Error('Internal diagnostic'))).toBe('CartCart could not continue. Try again.');
	});
});
