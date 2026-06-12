import { REGION_OPTIONS, regionByCode, type RegionOption } from '$lib/session/session-form.js';

export const REGION_STORAGE_KEY = 'cartcart.region';

export type LocalRegionPreference =
	| {
			status: 'provided';
			region: RegionOption;
	  }
	| {
			status: 'refused';
	  };

export function readLocalRegionPreference(storage: Storage): LocalRegionPreference | null {
	const raw = storage.getItem(REGION_STORAGE_KEY);
	if (!raw) return null;

	try {
		const parsed = JSON.parse(raw) as { status?: unknown; code?: unknown };
		if (parsed.status === 'refused') {
			return { status: 'refused' };
		}
		if (parsed.status === 'provided' && typeof parsed.code === 'string') {
			return { status: 'provided', region: regionByCode(parsed.code) };
		}
	} catch {
		return null;
	}

	return null;
}

export function writeProvidedRegionPreference(storage: Storage, code: string): LocalRegionPreference {
	const region = regionByCode(code);
	storage.setItem(REGION_STORAGE_KEY, JSON.stringify({ status: 'provided', code: region.code }));
	return { status: 'provided', region };
}

export function writeRefusedRegionPreference(storage: Storage): LocalRegionPreference {
	storage.setItem(REGION_STORAGE_KEY, JSON.stringify({ status: 'refused' }));
	return { status: 'refused' };
}

export function defaultRegionCode(): string {
	return REGION_OPTIONS[0].code;
}
