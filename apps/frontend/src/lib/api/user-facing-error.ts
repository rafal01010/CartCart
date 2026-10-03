import { ApiError } from './errors.js';

export function userFacingErrorMessage(error: unknown): string {
	if (error instanceof ApiError) {
		switch (error.code) {
			case 'research_mode_mismatch':
				return 'CartCart is using sample-data mode with live research settings. Enable live research or use sample data, then restart the app.';
			case 'live_agents_not_configured':
				return 'Live research is not ready. Check the local research configuration and restart CartCart.';
			case 'network_error':
				return 'CartCart could not connect. Check your connection and try again.';
		}
	}
	return 'CartCart could not continue. Try again.';
}
