import type {
	BudgetMode,
	CreateRefinementRequest,
	PreferenceConstraint,
	SessionStateResponse,
} from '$lib/api/types.js';
import { REGION_OPTIONS, parseBudget, regionByCode } from '$lib/session/session-form.js';

export type RefinementPromptKind = 'budget' | 'region' | 'category' | 'preferences';

export interface RefinementPromptDraft {
	kind: RefinementPromptKind;
	text: string;
	regionCode: string;
	currency: string;
	budgetMode: BudgetMode;
}

export interface RefinementPromptSpec {
	kind: RefinementPromptKind;
	question: string;
	placeholder: string;
	usesRegionChoice: boolean;
}

export function refinementPromptSpec(kind: RefinementPromptKind): RefinementPromptSpec {
	if (kind === 'budget') {
		return {
			kind,
			question: 'What budget should CartCart use now?',
			placeholder: 'Type the new budget.',
			usesRegionChoice: false,
		};
	}
	if (kind === 'region') {
		return {
			kind,
			question: 'Where should CartCart check availability now?',
			placeholder: 'Type anything else to keep in mind.',
			usesRegionChoice: true,
		};
	}
	if (kind === 'category') {
		return {
			kind,
			question: 'What kind of product should CartCart compare instead?',
			placeholder: 'Type the corrected category.',
			usesRegionChoice: false,
		};
	}
	return {
		kind,
		question: 'What should CartCart prioritize now?',
		placeholder: 'Type the change to keep in mind.',
		usesRegionChoice: false,
	};
}

export function refinementDraftFromSession(
	kind: RefinementPromptKind,
	session: SessionStateResponse | null,
): RefinementPromptDraft {
	const regionCode =
		session?.current_brief.region?.region.country_code ??
		session?.original_input.region?.region.country_code ??
		REGION_OPTIONS[0].code;
	const budgetMode =
		session?.current_brief.budget?.mode ?? session?.original_input.budget?.mode ?? 'preferred';
	const currency =
		session?.current_brief.budget?.amount.currency ??
		session?.current_brief.region?.region.currency ??
		session?.original_input.budget?.amount.currency ??
		session?.original_input.region?.region.currency ??
		regionByCode(regionCode).currency;

	return {
		kind,
		text: '',
		regionCode,
		currency,
		budgetMode,
	};
}

export function refinementPromptCanContinue(draft: RefinementPromptDraft): boolean {
	if (draft.kind === 'region') return Boolean(draft.regionCode);
	return draft.text.trim().length > 0;
}

export function buildRefinementRequestFromPrompt(
	draft: RefinementPromptDraft,
): CreateRefinementRequest {
	if (!refinementPromptCanContinue(draft)) {
		throw new Error('Answer the current refinement prompt before continuing.');
	}

	if (draft.kind === 'region') {
		const region = regionByCode(draft.regionCode);
		const note = normalizeText(draft.text);
		return {
			instruction: note
				? `Use ${region.label} results. Also keep in mind: ${note}.`
				: `Use ${region.label} results.`,
			region: {
				region: {
					country_code: region.code,
					currency: region.currency,
					locale: region.locale,
				},
				source: 'user_provided',
			},
			constraints: [],
			preferences: [],
		};
	}

	const text = normalizeText(draft.text);
	if (draft.kind === 'budget') {
		const amount = parseBudget(text);
		if (amount === null) {
			throw new Error('Type a budget amount.');
		}
		return {
			instruction: `Use a ${draft.budgetMode === 'hard_cap' ? 'hard' : 'soft'} budget of ${draft.currency.toUpperCase()} ${amount}.`,
			budget: {
				amount: {
					amount,
					currency: draft.currency.toUpperCase(),
				},
				mode: draft.budgetMode,
				source: 'user_provided',
			},
			constraints: [],
			preferences: [],
		};
	}

	if (draft.kind === 'category') {
		return {
			instruction: `Compare ${text} instead.`,
			constraints: [],
			preferences: [
				{
					text: `Correct product category: ${text}`,
					mode: 'soft',
					source: 'user_provided',
				},
			],
		};
	}

	const preference: PreferenceConstraint = {
		text,
		mode: 'soft',
		source: 'user_provided',
	};
	return {
		instruction: `Prioritize ${text}.`,
		constraints: [],
		preferences: [preference],
	};
}

function normalizeText(value: string): string {
	return value.trim().replace(/\s+/g, ' ');
}
