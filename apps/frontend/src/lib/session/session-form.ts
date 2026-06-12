import type {
	BudgetMode,
	CreateSessionRequest,
	FieldSource,
	PreferenceConstraint,
	SessionStateResponse,
} from '$lib/api/types.js';

export interface RegionOption {
	code: string;
	label: string;
	currency: string;
	locale: string;
}

export interface SessionFormState {
	query: string;
	regionCode: string;
	currency: string;
	budget: string;
	budgetMode: BudgetMode;
	priorities: string;
}

export const REGION_OPTIONS: RegionOption[] = [
	{ code: 'US', label: 'United States', currency: 'USD', locale: 'en-US' },
	{ code: 'CA', label: 'Canada', currency: 'CAD', locale: 'en-CA' },
	{ code: 'GB', label: 'United Kingdom', currency: 'GBP', locale: 'en-GB' },
	{ code: 'AU', label: 'Australia', currency: 'AUD', locale: 'en-AU' },
];

export function defaultSessionFormState(): SessionFormState {
	const region = REGION_OPTIONS[0];
	return {
		query: '',
		regionCode: region.code,
		currency: region.currency,
		budget: '',
		budgetMode: 'preferred',
		priorities: '',
	};
}

export function buildCreateSessionRequest(form: SessionFormState): CreateSessionRequest {
	const query = form.query.trim();
	const region = regionByCode(form.regionCode);
	const priorities = form.priorities.trim();
	const budget = parseBudget(form.budget);
	const preferences: PreferenceConstraint[] = priorities
		? [{ text: priorities, mode: 'soft', source: 'user_provided' }]
		: [];

	return {
		query,
		region: {
			region: {
				country_code: region.code,
				currency: form.currency.trim().toUpperCase() || region.currency,
				locale: region.locale,
			},
			source: 'user_provided',
		},
		budget:
			budget === null
				? null
				: {
						amount: {
							amount: budget,
							currency: form.currency.trim().toUpperCase() || region.currency,
						},
						mode: form.budgetMode,
						source: 'user_provided',
					},
		preferences,
		constraints: [],
	};
}

export function sessionFormStateFromResponse(session: SessionStateResponse): SessionFormState {
	const form = defaultSessionFormState();
	const brief = session.current_brief;
	const regionCode = brief.region?.region.country_code ?? session.original_input.region?.region.country_code;
	const currency =
		brief.budget?.amount.currency ??
		brief.region?.region.currency ??
		session.original_input.budget?.amount.currency ??
		session.original_input.region?.region.currency;
	const budget = brief.budget?.amount.amount ?? session.original_input.budget?.amount.amount;
	const budgetMode = brief.budget?.mode ?? session.original_input.budget?.mode;
	const priorities =
		brief.preferences?.map((preference) => preference.text).join(', ') ||
		session.original_input.preferences?.map((preference) => preference.text).join(', ');

	return {
		query: brief.original_query || session.original_input.query || form.query,
		regionCode: regionCode ?? form.regionCode,
		currency: currency ?? form.currency,
		budget: budget === undefined || budget === null ? form.budget : String(budget),
		budgetMode: budgetMode ?? form.budgetMode,
		priorities: priorities || form.priorities,
	};
}

export function regionByCode(code: string): RegionOption {
	return REGION_OPTIONS.find((region) => region.code === code) ?? REGION_OPTIONS[0];
}

export function fieldSourceLabel(source: FieldSource | null | undefined): string {
	if (source === 'user_provided') return 'user provided';
	if (source === 'defaulted') return 'defaulted';
	if (source === 'inferred') return 'inferred';
	return 'unknown';
}

export function parseBudget(value: string): number | null {
	const normalized = value.trim().replace(/[$,\s]/g, '');
	if (!normalized) {
		return null;
	}
	const amount = Number(normalized);
	return Number.isFinite(amount) && amount >= 0 ? amount : null;
}

export function shortSessionId(sessionId: string): string {
	return sessionId.length <= 8 ? sessionId : sessionId.slice(0, 8);
}
