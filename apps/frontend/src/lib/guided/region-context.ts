import type { GuidedIntakeState, ShoppingBrief } from '$lib/api/types.js';
import { regionByCode } from '$lib/session/session-form.js';
import type { LocalRegionPreference } from './local-region.js';

export function regionContextLabel({ decisionBrief, sessionBrief, guide, preference }: {
	decisionBrief: ShoppingBrief | null | undefined;
	sessionBrief: ShoppingBrief | null | undefined;
	guide: GuidedIntakeState | null;
	preference: LocalRegionPreference | null;
}): string {
	if (decisionBrief !== undefined) {
		return decisionBrief?.region
			? regionByCode(decisionBrief.region.region.country_code).label : 'Region not set';
	}
	if (sessionBrief) {
		return sessionBrief.region
			? regionByCode(sessionBrief.region.region.country_code).label : 'Region not set';
	}
	if (guide) {
		return guide.region_setup.status === 'provided' && guide.region_setup.region
			? regionByCode(guide.region_setup.region.country_code).label : 'Region not set';
	}
	return preference?.status === 'provided' ? preference.region.label
		: preference?.status === 'refused' ? 'Region not set' : 'Set buying region';
}
