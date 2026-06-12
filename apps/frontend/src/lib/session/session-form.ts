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

const ISO_3166_ALPHA_2_REGION_CODES = [
	'US',
	'CA',
	'GB',
	'AU',
	'PH',
	'JP',
	'DE',
	'FR',
	'IT',
	'ES',
	'NL',
	'SE',
	'NO',
	'DK',
	'FI',
	'IE',
	'BE',
	'CH',
	'AT',
	'PT',
	'NZ',
	'SG',
	'HK',
	'KR',
	'CN',
	'TW',
	'IN',
	'MY',
	'TH',
	'ID',
	'VN',
	'BR',
	'MX',
	'AR',
	'CL',
	'CO',
	'PE',
	'ZA',
	'AE',
	'SA',
	'AF',
	'AX',
	'AL',
	'DZ',
	'AS',
	'AD',
	'AO',
	'AI',
	'AQ',
	'AG',
	'AM',
	'AW',
	'AZ',
	'BS',
	'BH',
	'BD',
	'BB',
	'BY',
	'BZ',
	'BJ',
	'BM',
	'BT',
	'BO',
	'BQ',
	'BA',
	'BW',
	'BV',
	'IO',
	'BN',
	'BG',
	'BF',
	'BI',
	'CV',
	'KH',
	'CM',
	'KY',
	'CF',
	'TD',
	'CX',
	'CC',
	'KM',
	'CG',
	'CD',
	'CK',
	'CR',
	'CI',
	'HR',
	'CU',
	'CW',
	'CY',
	'CZ',
	'DJ',
	'DM',
	'DO',
	'EC',
	'EG',
	'SV',
	'GQ',
	'ER',
	'EE',
	'SZ',
	'ET',
	'FK',
	'FO',
	'FJ',
	'GF',
	'PF',
	'TF',
	'GA',
	'GM',
	'GE',
	'GH',
	'GI',
	'GR',
	'GL',
	'GD',
	'GP',
	'GU',
	'GT',
	'GG',
	'GN',
	'GW',
	'GY',
	'HT',
	'HM',
	'VA',
	'HN',
	'HU',
	'IS',
	'IR',
	'IQ',
	'IM',
	'IL',
	'JM',
	'JE',
	'JO',
	'KZ',
	'KE',
	'KI',
	'KP',
	'KW',
	'KG',
	'LA',
	'LV',
	'LB',
	'LS',
	'LR',
	'LY',
	'LI',
	'LT',
	'LU',
	'MO',
	'MG',
	'MW',
	'MV',
	'ML',
	'MT',
	'MH',
	'MQ',
	'MR',
	'MU',
	'YT',
	'FM',
	'MD',
	'MC',
	'MN',
	'ME',
	'MS',
	'MA',
	'MZ',
	'MM',
	'NA',
	'NR',
	'NP',
	'NC',
	'NI',
	'NE',
	'NG',
	'NU',
	'NF',
	'MK',
	'MP',
	'OM',
	'PK',
	'PW',
	'PS',
	'PA',
	'PG',
	'PY',
	'PN',
	'PL',
	'PR',
	'QA',
	'RE',
	'RO',
	'RU',
	'RW',
	'BL',
	'SH',
	'KN',
	'LC',
	'MF',
	'PM',
	'VC',
	'WS',
	'SM',
	'ST',
	'SN',
	'RS',
	'SC',
	'SL',
	'SX',
	'SK',
	'SI',
	'SB',
	'SO',
	'GS',
	'SS',
	'LK',
	'SD',
	'SR',
	'SJ',
	'SY',
	'TJ',
	'TZ',
	'TL',
	'TG',
	'TK',
	'TO',
	'TT',
	'TN',
	'TR',
	'TM',
	'TC',
	'TV',
	'UG',
	'UA',
	'UM',
	'UY',
	'UZ',
	'VU',
	'VE',
	'VG',
	'VI',
	'WF',
	'EH',
	'YE',
	'ZM',
	'ZW',
] as const;

const REGION_METADATA: Record<string, { currency: string; locale: string }> = {
	US: { currency: 'USD', locale: 'en-US' },
	CA: { currency: 'CAD', locale: 'en-CA' },
	GB: { currency: 'GBP', locale: 'en-GB' },
	AU: { currency: 'AUD', locale: 'en-AU' },
	PH: { currency: 'PHP', locale: 'en-PH' },
	JP: { currency: 'JPY', locale: 'ja-JP' },
	DE: { currency: 'EUR', locale: 'de-DE' },
	FR: { currency: 'EUR', locale: 'fr-FR' },
	IT: { currency: 'EUR', locale: 'it-IT' },
	ES: { currency: 'EUR', locale: 'es-ES' },
	NL: { currency: 'EUR', locale: 'nl-NL' },
	SE: { currency: 'SEK', locale: 'sv-SE' },
	NO: { currency: 'NOK', locale: 'nb-NO' },
	DK: { currency: 'DKK', locale: 'da-DK' },
	FI: { currency: 'EUR', locale: 'fi-FI' },
	IE: { currency: 'EUR', locale: 'en-IE' },
	BE: { currency: 'EUR', locale: 'nl-BE' },
	CH: { currency: 'CHF', locale: 'de-CH' },
	AT: { currency: 'EUR', locale: 'de-AT' },
	PT: { currency: 'EUR', locale: 'pt-PT' },
	NZ: { currency: 'NZD', locale: 'en-NZ' },
	SG: { currency: 'SGD', locale: 'en-SG' },
	HK: { currency: 'HKD', locale: 'zh-HK' },
	KR: { currency: 'KRW', locale: 'ko-KR' },
	CN: { currency: 'CNY', locale: 'zh-CN' },
	TW: { currency: 'TWD', locale: 'zh-TW' },
	IN: { currency: 'INR', locale: 'en-IN' },
	MY: { currency: 'MYR', locale: 'ms-MY' },
	TH: { currency: 'THB', locale: 'th-TH' },
	ID: { currency: 'IDR', locale: 'id-ID' },
	VN: { currency: 'VND', locale: 'vi-VN' },
	BR: { currency: 'BRL', locale: 'pt-BR' },
	MX: { currency: 'MXN', locale: 'es-MX' },
	AR: { currency: 'ARS', locale: 'es-AR' },
	CL: { currency: 'CLP', locale: 'es-CL' },
	CO: { currency: 'COP', locale: 'es-CO' },
	PE: { currency: 'PEN', locale: 'es-PE' },
	ZA: { currency: 'ZAR', locale: 'en-ZA' },
	AE: { currency: 'AED', locale: 'en-AE' },
	SA: { currency: 'SAR', locale: 'ar-SA' },
};

// Display names come from Unicode CLDR through Intl.DisplayNames; the selectable
// identifiers are ISO 3166-1 alpha-2 region codes.
// Sources: https://cldr.unicode.org/ and https://www.iso.org/iso-3166-country-codes.html
const regionDisplayNames = new Intl.DisplayNames(['en'], { type: 'region' });

export const REGION_OPTIONS: RegionOption[] = ISO_3166_ALPHA_2_REGION_CODES.map((code) => {
	const metadata = REGION_METADATA[code] ?? { currency: 'USD', locale: `en-${code}` };
	return {
		code,
		label: regionDisplayNames.of(code) ?? code,
		...metadata,
	};
});

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
