import type {
	CurrentGuidedQuestion,
	GuidedAnswer,
	GuidedAnswerSubmission,
	InlineChoiceOption,
	Region,
	RegionSetupSubmission,
} from '$lib/api/types.js';
import type { LocalRegionPreference } from './local-region.js';

export type GuidedAnswerSurfaceView = 'textbox' | 'inline_choice' | 'two_option_plus_text';

export interface GuidedDraft {
	text: string;
	choiceId: string | null;
	isCustomAnswer: boolean;
}

export const EMPTY_GUIDED_DRAFT: GuidedDraft = {
	text: '',
	choiceId: null,
	isCustomAnswer: false,
};

export function questionEyebrow(question: CurrentGuidedQuestion): string {
	if (question.purpose === 'combined_optional') return 'Useful details';
	if (question.purpose === 'priorities') return 'What matters';
	if (question.purpose === 'comparison') return 'Comparison';
	if (question.purpose === 'clarification') return 'Quick question';
	return 'A little context';
}

export function questionHelper(question: CurrentGuidedQuestion): string | null {
	if (question.combined_optional_prompt?.text) {
		return `${question.combined_optional_prompt.text} You do not need links.`;
	}
	if (question.answer_surface === 'textbox') {
		return 'One sentence is enough.';
	}
	return null;
}

export function answerSurfaceView(question: CurrentGuidedQuestion): GuidedAnswerSurfaceView {
	if (question.answer_surface === 'textbox') return 'textbox';
	if (question.inline_choice?.control_type === 'two_option_plus_type_answer') {
		return 'two_option_plus_text';
	}
	return 'inline_choice';
}

export function canContinueGuidedQuestion(question: CurrentGuidedQuestion, draft: GuidedDraft): boolean {
	const surface = answerSurfaceView(question);
	if (surface === 'textbox') {
		return draft.text.trim().length > 0;
	}
	if (surface === 'two_option_plus_text' && draft.isCustomAnswer) {
		return draft.text.trim().length > 0;
	}
	return draft.choiceId !== null;
}

export function buildGuidedAnswerSubmission(
	question: CurrentGuidedQuestion,
	draft: GuidedDraft,
): GuidedAnswerSubmission {
	return {
		question_id: question.question_id,
		answer: buildGuidedAnswer(question, draft),
	};
}

export function createDraftFromCachedAnswer(answer: GuidedAnswer | undefined): GuidedDraft {
	if (!answer) {
		return { ...EMPTY_GUIDED_DRAFT };
	}
	if (answer.answer_type === 'natural_language') {
		return { ...EMPTY_GUIDED_DRAFT, text: answer.text };
	}
	if (answer.answer_type === 'yes_no') {
		return { ...EMPTY_GUIDED_DRAFT, choiceId: answer.value ? 'yes' : 'no' };
	}
	if (answer.answer_type === 'choice') {
		return { ...EMPTY_GUIDED_DRAFT, choiceId: answer.choice_id };
	}
	return {
		text: answer.text,
		choiceId: answer.choice_id ?? null,
		isCustomAnswer: true,
	};
}

export function regionSetupSubmissionFromPreference(
	preference: LocalRegionPreference | null,
): RegionSetupSubmission | null {
	if (preference === null) return null;
	if (preference.status === 'refused') return { status: 'refused' };
	return {
		status: 'provided',
		region: {
			country_code: preference.region.code,
			currency: preference.region.currency,
			locale: preference.region.locale,
		},
	};
}

export function regionSetupSubmissionFromOption(region: {
	code: string;
	currency: string;
	locale: string;
}): RegionSetupSubmission {
	return {
		status: 'provided',
		region: regionFromOption(region),
	};
}

function buildGuidedAnswer(question: CurrentGuidedQuestion, draft: GuidedDraft): GuidedAnswer {
	const surface = answerSurfaceView(question);
	if (surface === 'textbox') {
		return { answer_type: 'natural_language', text: draft.text.trim() };
	}
	if (surface === 'two_option_plus_text' && draft.isCustomAnswer) {
		return {
			answer_type: 'choice_with_text',
			choice_id: draft.choiceId,
			text: draft.text.trim(),
		};
	}

	const choice = question.inline_choice?.options.find(
		(option: InlineChoiceOption) => option.choice_id === draft.choiceId,
	);
	if (question.inline_choice?.control_type === 'yes_no' && choice) {
		return {
			answer_type: 'yes_no',
			value: choice.choice_id === 'yes',
		};
	}
	return {
		answer_type: 'choice',
		choice_id: choice?.choice_id ?? draft.choiceId ?? '',
	};
}

function regionFromOption(region: { code: string; currency: string; locale: string }): Region {
	return {
		country_code: region.code,
		currency: region.currency,
		locale: region.locale,
	};
}
