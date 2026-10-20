import type { CartCartApiClient, GuidedIntakeState, SessionId } from '$lib/api/index.js';
import { regionSetupSubmissionFromPreference } from './guided-state.js';
import {
	writeProvidedRegionPreference,
	writeRefusedRegionPreference,
	type LocalRegionPreference,
} from './local-region.js';

type RegionEditContext =
	| { kind: 'guided'; sessionId: SessionId; api: Pick<CartCartApiClient, 'submitGuidedRegionSetup'> }
	| { kind: 'future' };

export async function applyRegionEdit({ preference, context, storage, isCurrent }: {
	preference: LocalRegionPreference;
	context: RegionEditContext;
	storage: Storage;
	isCurrent: () => boolean;
}): Promise<{ preference: LocalRegionPreference; guide: GuidedIntakeState | null } | null> {
	const submission = regionSetupSubmissionFromPreference(preference);
	if (!submission) return null;
	const guide = context.kind === 'guided'
		? await context.api.submitGuidedRegionSetup(context.sessionId, submission)
		: null;
	if (!isCurrent()) return null;
	if (preference.status === 'provided') {
		writeProvidedRegionPreference(storage, preference.region.code);
	} else {
		writeRefusedRegionPreference(storage);
	}
	return { preference, guide };
}
