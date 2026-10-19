import type { RunEvent, RunStage, RunStatus, ShoppingRunRecord } from '$lib/api/types.js';

export type StageProgressStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped';
export type ShopperProgressKind =
	| 'checking_options'
	| 'verifying_risky_listings'
	| 'comparing_evidence'
	| 'preparing_recommendation'
	| 'ready';

export interface StageProgressItem {
	stage: RunStage;
	label: string;
	status: StageProgressStatus;
	message: string;
}

export interface ShopperProgressItem {
	kind: ShopperProgressKind;
	label: string;
	status: StageProgressStatus;
	message: string;
}

export const RUN_STAGE_ORDER: RunStage[] = [
	'intake',
	'general_owner',
	'query_planning',
	'discovery',
	'extraction',
	'deduplication',
	'source_intelligence',
	'listing_trust',
	'category_analysis',
	'comparison_decision',
	'verification',
	'complete',
];

const STAGE_LABELS: Record<RunStage, string> = {
	intake: 'Intake',
	general_owner: 'Shopping review',
	query_planning: 'Query planning',
	discovery: 'Discovery/search',
	extraction: 'Source extraction',
	deduplication: 'Deduplication',
	source_intelligence: 'Source intelligence',
	listing_trust: 'Seller/listing trust',
	category_analysis: 'Category analysis',
	comparison_decision: 'Comparison and decision',
	verification: 'Verification',
	complete: 'Result ready',
};

const PENDING_MESSAGES: Record<RunStage, string> = {
	intake: 'Session must be created first',
	general_owner: 'Waiting to review your shopping question',
	query_planning: 'Waiting for a run',
	discovery: 'Waiting for a run',
	extraction: 'Waiting for source snapshots',
	deduplication: 'Listing identity not reviewed yet',
	source_intelligence: 'Additional source checks not started',
	listing_trust: 'Seller signals not checked',
	category_analysis: 'Product-fit review not started',
	comparison_decision: 'Recommendation pending',
	verification: 'Source support pending',
	complete: 'No final pick yet',
};

export const SHOPPER_PROGRESS_ORDER: ShopperProgressKind[] = [
	'checking_options',
	'verifying_risky_listings',
	'comparing_evidence',
	'preparing_recommendation',
	'ready',
];

const SHOPPER_PROGRESS_LABELS: Record<ShopperProgressKind, string> = {
	checking_options: 'Checking options',
	verifying_risky_listings: 'Checking risky listings',
	comparing_evidence: 'Comparing evidence',
	preparing_recommendation: 'Preparing recommendation',
	ready: 'Recommendation ready',
};

const SHOPPER_PROGRESS_MESSAGES: Record<ShopperProgressKind, string> = {
	checking_options: 'Looking for realistic choices that match your question.',
	verifying_risky_listings: 'Checking seller and listing signals before treating deals as safe.',
	comparing_evidence: 'Weighing fit, value, tradeoffs, and support from sources.',
	preparing_recommendation: 'Turning the evidence into a clear buying recommendation.',
	ready: 'Your recommendation is ready to review.',
};

const SHOPPER_STAGE_MAP: Record<RunStage, ShopperProgressKind> = {
	intake: 'checking_options',
	general_owner: 'checking_options',
	query_planning: 'checking_options',
	discovery: 'checking_options',
	extraction: 'checking_options',
	deduplication: 'checking_options',
	source_intelligence: 'comparing_evidence',
	listing_trust: 'verifying_risky_listings',
	category_analysis: 'comparing_evidence',
	comparison_decision: 'comparing_evidence',
	verification: 'preparing_recommendation',
	complete: 'ready',
};

export function createInitialRunProgress(): StageProgressItem[] {
	return RUN_STAGE_ORDER.map((stage) => ({
		stage,
		label: STAGE_LABELS[stage],
		status: 'pending',
		message: PENDING_MESSAGES[stage],
	}));
}

export function applyRunEvent(
	progress: StageProgressItem[],
	event: RunEvent,
): StageProgressItem[] {
	const eventIndex = RUN_STAGE_ORDER.indexOf(event.stage);
	return progress.map((item, index) => {
		if (event.status === 'failed') {
			if (index < eventIndex) {
				return { ...item, status: 'succeeded' };
			}
			if (item.stage === event.stage) {
				return { ...item, status: 'failed', message: event.message };
			}
			return item;
		}

		if (event.status === 'succeeded' || event.stage === 'complete') {
			if (index <= eventIndex) {
				return {
					...item,
					status: 'succeeded',
					message: item.stage === event.stage ? event.message : item.message,
				};
			}
			return item;
		}

		if (event.status === 'running') {
			if (index < eventIndex) {
				return { ...item, status: 'succeeded' };
			}
			if (item.stage === event.stage) {
				return { ...item, status: 'running', message: event.message };
			}
		}

		return item;
	});
}

export function shopperProgressFromEvents(events: readonly RunEvent[]): ShopperProgressItem[] {
	const stages: Partial<Record<RunStage, StageProgressStatus>> = {};
	let activeStage: RunStage | null = null;
	let terminalStatus: 'succeeded' | 'failed' | null = null;

	for (const event of events) {
		if (event.status === 'failed' || event.status === 'cancelled') {
			if (activeStage && activeStage !== event.stage) stages[activeStage] = 'skipped';
			stages[event.stage] = 'failed';
			terminalStatus = 'failed';
			break;
		}
		if (event.status === 'pending') continue;
		if (event.stage === 'complete' && event.status !== 'succeeded') continue;

		if (activeStage && activeStage !== event.stage) stages[activeStage] = 'succeeded';
		stages[event.stage] = event.status;
		activeStage = event.status === 'running' ? event.stage : null;
		if (event.stage === 'complete' && event.status === 'succeeded') {
			terminalStatus = 'succeeded';
			break;
		}
	}

	return SHOPPER_PROGRESS_ORDER.map((kind) => {
		const contributingStages = RUN_STAGE_ORDER.filter((stage) => SHOPPER_STAGE_MAP[stage] === kind);
		const observedStatuses = contributingStages.flatMap((stage) => {
			const status = stages[stage];
			return status ? [status] : [];
		});
		let status: StageProgressStatus = 'pending';
		if (observedStatuses.includes('failed')) status = 'failed';
		else if (observedStatuses.includes('running')) status = 'running';
		else if (
			(terminalStatus === 'succeeded' && observedStatuses.length > 0) ||
			contributingStages.every((stage) => stages[stage] === 'succeeded')
		) status = 'succeeded';
		else if (terminalStatus) status = 'skipped';

		return {
			kind,
			label: SHOPPER_PROGRESS_LABELS[kind],
			status,
			message: status === 'failed'
				? 'CartCart could not finish this check. Try again.'
				: status === 'skipped'
					? 'This check was not completed.'
					: SHOPPER_PROGRESS_MESSAGES[kind],
		};
	});
}

export function runStatusFromRecord(run: ShoppingRunRecord | null): RunStatus | 'idle' {
	return run?.status ?? 'idle';
}

export function isTerminalRunStatus(status: RunStatus | 'idle'): boolean {
	return status === 'succeeded' || status === 'failed' || status === 'cancelled';
}

export function isTerminalRunEvent(event: RunEvent): boolean {
	return event.status === 'failed' || event.status === 'cancelled' ||
		(event.stage === 'complete' && event.status === 'succeeded');
}

export function runStatusLabel(status: RunStatus | 'idle'): string {
	if (status === 'idle') return 'No run yet';
	if (status === 'pending') return 'Run queued';
	if (status === 'running') return 'Run in progress';
	if (status === 'succeeded') return 'Run complete';
	if (status === 'failed') return 'Run failed';
	if (status === 'cancelled') return 'Run cancelled';
	return status;
}

export function shopperProgressHeadline(progress: ShopperProgressItem[]): string {
	if (progress.some((item) => item.status === 'failed')) {
		return 'CartCart could not finish checking options.';
	}
	if (progress.find((item) => item.kind === 'ready')?.status === 'succeeded') {
		return 'Your recommendation is ready.';
	}
	const active = progress.find((item) => item.status === 'running');
	return active ? active.label : 'CartCart is checking options.';
}
