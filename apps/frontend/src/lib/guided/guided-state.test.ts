import { describe, expect, it } from 'vitest';
import {
	EMPTY_GUIDED_DRAFT,
	answerSurfaceView,
	buildGuidedAnswerSubmission,
	canContinueGuidedQuestion,
	createDraftFromCachedAnswer,
	regionSetupSubmissionFromPreference,
} from './guided-state.js';
import type { CurrentGuidedQuestion } from '$lib/api/types.js';

const textboxQuestion: CurrentGuidedQuestion = {
	schema_version: 1,
	question_id: 'budget',
	text: 'What budget should we stay near?',
	purpose: 'budget',
	answer_surface: 'textbox',
	capture_targets: ['budget'],
};

const yesNoQuestion: CurrentGuidedQuestion = {
	schema_version: 1,
	question_id: 'monitor-connection',
	text: 'Would one-cable setup be useful for this monitor?',
	purpose: 'priorities',
	answer_surface: 'inline_choice',
	capture_targets: ['priorities'],
	inline_choice: {
		control_id: 'monitor-connection-choice',
		control_type: 'yes_no',
		options: [
			{ choice_id: 'yes', label: 'Yes' },
			{ choice_id: 'no', label: 'No' },
		],
	},
};

const customChoiceQuestion: CurrentGuidedQuestion = {
	schema_version: 1,
	question_id: 'comparison-priority',
	text: 'For that comparison, what should matter most?',
	purpose: 'priorities',
	answer_surface: 'inline_choice',
	capture_targets: ['priorities'],
	inline_choice: {
		control_id: 'comparison-priority-choice',
		control_type: 'two_option_plus_type_answer',
		options: [
			{ choice_id: 'everyday-use', label: 'Everyday use' },
			{ choice_id: 'best-value', label: 'Best value' },
		],
		custom_answer_label: 'Type my answer',
	},
};

describe('guided API state view helpers', () => {
	it('requires non-empty text for textbox questions and builds natural language answers', () => {
		expect(answerSurfaceView(textboxQuestion)).toBe('textbox');
		expect(canContinueGuidedQuestion(textboxQuestion, EMPTY_GUIDED_DRAFT)).toBe(false);

		const draft = { ...EMPTY_GUIDED_DRAFT, text: 'Under $300 and considering the Bekant.' };

		expect(canContinueGuidedQuestion(textboxQuestion, draft)).toBe(true);
		expect(buildGuidedAnswerSubmission(textboxQuestion, draft)).toEqual({
			question_id: 'budget',
			answer: {
				answer_type: 'natural_language',
				text: 'Under $300 and considering the Bekant.',
			},
		});
	});

	it('builds yes/no answers for yes-no inline choices', () => {
		const draft = { ...EMPTY_GUIDED_DRAFT, choiceId: 'yes' };

		expect(answerSurfaceView(yesNoQuestion)).toBe('inline_choice');
		expect(canContinueGuidedQuestion(yesNoQuestion, EMPTY_GUIDED_DRAFT)).toBe(false);
		expect(buildGuidedAnswerSubmission(yesNoQuestion, draft)).toEqual({
			question_id: 'monitor-connection',
			answer: {
				answer_type: 'yes_no',
				value: true,
			},
		});
	});

	it('supports two-option-plus-type-answer choices', () => {
		expect(answerSurfaceView(customChoiceQuestion)).toBe('two_option_plus_text');
		expect(
			canContinueGuidedQuestion(customChoiceQuestion, {
				text: '',
				choiceId: null,
				isCustomAnswer: true,
			}),
		).toBe(false);

		expect(
			buildGuidedAnswerSubmission(customChoiceQuestion, {
				text: 'Battery life matters most.',
				choiceId: null,
				isCustomAnswer: true,
			}),
		).toEqual({
			question_id: 'comparison-priority',
			answer: {
				answer_type: 'choice_with_text',
				choice_id: null,
				text: 'Battery life matters most.',
			},
		});
	});

	it('creates drafts from cached backend answer payloads', () => {
		expect(createDraftFromCachedAnswer({ answer_type: 'yes_no', value: false })).toEqual({
			text: '',
			choiceId: 'no',
			isCustomAnswer: false,
		});
		expect(
			createDraftFromCachedAnswer({
				answer_type: 'choice_with_text',
				text: 'Durability',
				choice_id: 'other',
			}),
		).toEqual({
			text: 'Durability',
			choiceId: 'other',
			isCustomAnswer: true,
		});
	});

	it('converts local region preference into backend region setup payloads', () => {
		expect(regionSetupSubmissionFromPreference({ status: 'refused' })).toEqual({
			status: 'refused',
		});
		expect(
			regionSetupSubmissionFromPreference({
				status: 'provided',
				region: { code: 'CA', label: 'Canada', currency: 'CAD', locale: 'en-CA' },
			}),
		).toEqual({
			status: 'provided',
			region: { country_code: 'CA', currency: 'CAD', locale: 'en-CA' },
		});
	});
});
