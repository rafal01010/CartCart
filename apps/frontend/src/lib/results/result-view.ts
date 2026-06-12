import type {
	EntityId,
	RecommendationMode,
	RecommendationModeResult,
	RejectedItem,
	SessionResultsResponse,
	SourceEvidence,
	SourceSnapshot,
} from '$lib/api/types.js';

export interface EvidenceView {
	id: EntityId;
	claim: string;
	type: string;
	confidence: string;
	sourceTitle: string;
	sourceUrl: string | null;
}

export interface SourceView {
	id: EntityId;
	title: string;
	url: string;
	type: string;
	provider: string;
	quality: string;
	evidence: EvidenceView[];
}

export interface ModeView {
	key: string;
	mode: RecommendationMode;
	label: string;
	productId: EntityId;
	listingId: EntityId | null;
	rationale: string;
	confidence: string;
	evidence: EvidenceView[];
	sources: SourceView[];
}

export interface TrustView {
	listingId: EntityId;
	level: string;
	confidence: string;
	summary: string;
	positiveSignals: string[];
	redFlags: string[];
	evidence: EvidenceView[];
	sources: SourceView[];
}

export interface RejectedView {
	key: string;
	label: string;
	severity: string;
	reason: string;
	evidence: EvidenceView[];
	sources: SourceView[];
}

export interface ResultView {
	versionLabel: string;
	finalMode: ModeView | null;
	noStrongBuyReason: string | null;
	whyItWins: string | null;
	modeViews: ModeView[];
	runnerUps: ModeView[];
	trustViews: TrustView[];
	warnings: string[];
	rejectedItems: RejectedView[];
	sourceViews: SourceView[];
	evidenceViews: EvidenceView[];
}

const MODE_LABELS: Record<RecommendationMode, string> = {
	best_overall: 'Best overall',
	best_value: 'Best value',
	within_budget: 'Within budget',
	stretch_pick: 'Stretch pick',
	runner_up: 'Runner-up',
};

export function buildResultView(result: SessionResultsResponse): ResultView {
	const sourceById = new Map(result.source_snapshots.map((source) => [source.source_id, source]));
	const evidenceById = new Map(result.source_evidence.map((evidence) => [evidence.evidence_id, evidence]));
	const evidenceViews = result.source_evidence.map((evidence) =>
		toEvidenceView(evidence, sourceById.get(evidence.source_id)),
	);
	const sourceViews = result.source_snapshots.map((source) =>
		toSourceView(
			source,
			result.source_evidence
				.filter((evidence) => evidence.source_id === source.source_id)
				.map((evidence) => toEvidenceView(evidence, source)),
		),
	);
	const sourceViewById = new Map(sourceViews.map((source) => [source.id, source]));

	const modeViews = result.recommendation_bundle.mode_results.map((mode) =>
		toModeView(mode, evidenceById, sourceViewById),
	);
	const finalMode = findFinalMode(result, modeViews);

	return {
		versionLabel: `v${result.result_version.version}`,
		finalMode,
		noStrongBuyReason: result.recommendation_bundle.no_strong_buy
			? shopperSafeText(
					result.recommendation_bundle.no_strong_buy_reason ?? 'No strong buy is available.',
				)
			: null,
		whyItWins: shopperSafeOptionalText(
			result.recommendation_bundle.final_rationale ?? finalMode?.rationale ?? null,
		),
		modeViews,
		runnerUps: findRunnerUps(result, modeViews, finalMode),
		trustViews: result.trust_assessments.map((trust) => ({
			listingId: trust.listing_id,
			level: trust.level,
			confidence: confidenceLabel(trust.confidence.level, trust.confidence.score),
			summary: shopperSafeText(trust.summary),
			positiveSignals: trust.positive_signals.map(shopperSafeText),
			redFlags: trust.red_flags.map(shopperSafeText),
			evidence: mapEvidence(trust.evidence_ids, evidenceById, sourceById),
			sources: mapSources(trust.source_ids, sourceViewById),
		})),
		warnings: [
			...result.recommendation_bundle.warnings,
			...result.category_analyses.flatMap((analysis) => analysis.warnings),
			...result.trust_assessments.flatMap((trust) => trust.red_flags),
		].map(shopperSafeText).filter(hasText),
		rejectedItems: result.recommendation_bundle.rejected_items
			.filter(hasMeaningfulRejection)
			.map((item) => toRejectedView(item, evidenceById, sourceById, sourceViewById)),
		sourceViews,
		evidenceViews,
	};
}

export function modeLabel(mode: RecommendationMode): string {
	return MODE_LABELS[mode];
}

export function shortEntityId(id: EntityId | null | undefined): string {
	if (!id) return 'Not linked';
	return id.length > 8 ? id.slice(0, 8) : id;
}

export function scoreLabel(score: number | null | undefined): string {
	if (typeof score !== 'number') return 'Not scored';
	return `${Math.round(score * 100)}%`;
}

function findFinalMode(result: SessionResultsResponse, modes: ModeView[]): ModeView | null {
	const bundle = result.recommendation_bundle;
	return (
		modes.find(
			(mode) =>
				mode.productId === bundle.final_product_id &&
				(!bundle.final_listing_id || mode.listingId === bundle.final_listing_id),
		) ??
		modes.find((mode) => mode.mode === 'best_overall') ??
		modes[0] ??
		null
	);
}

function findRunnerUps(
	result: SessionResultsResponse,
	modes: ModeView[],
	finalMode: ModeView | null,
): ModeView[] {
	const runnerIds = new Set(result.recommendation_bundle.runner_up_product_ids);
	const finalKey = finalMode ? resultKey(finalMode.productId, finalMode.listingId) : null;
	const runnerModes = modes.filter((mode) => {
		const isRunner = runnerIds.has(mode.productId) || mode.mode === 'runner_up';
		return isRunner && resultKey(mode.productId, mode.listingId) !== finalKey;
	});

	return dedupeModes(runnerModes);
}

function dedupeModes(modes: ModeView[]): ModeView[] {
	const seen = new Set<string>();
	return modes.filter((mode) => {
		const key = resultKey(mode.productId, mode.listingId);
		if (seen.has(key)) return false;
		seen.add(key);
		return true;
	});
}

function toModeView(
	mode: RecommendationModeResult,
	evidenceById: Map<EntityId, SourceEvidence>,
	sourceViewById: Map<EntityId, SourceView>,
): ModeView {
	const sources = mapSources(mode.source_ids, sourceViewById);
	return {
		key: `${mode.mode}:${resultKey(mode.product_id, mode.listing_id ?? null)}`,
		mode: mode.mode,
		label: shopperSafeText(mode.title || modeLabel(mode.mode)),
		productId: mode.product_id,
		listingId: mode.listing_id ?? null,
		rationale: shopperSafeText(mode.rationale),
		confidence: confidenceLabel(mode.confidence.level, mode.confidence.score),
		evidence: mode.evidence_ids
			.map((id) => evidenceById.get(id))
			.filter((evidence): evidence is SourceEvidence => Boolean(evidence))
			.map((evidence) => toEvidenceView(evidence, sources.find((source) => source.id === evidence.source_id))),
		sources,
	};
}

function toRejectedView(
	item: RejectedItem,
	evidenceById: Map<EntityId, SourceEvidence>,
	sourceById: Map<EntityId, SourceSnapshot>,
	sourceViewById: Map<EntityId, SourceView>,
): RejectedView {
	return {
		key: resultKey(item.product_id ?? null, item.listing_id ?? null),
		label: item.listing_id
			? `Listing ${shortEntityId(item.listing_id)}`
			: `Product ${shortEntityId(item.product_id)}`,
		severity: item.severity,
		reason: shopperSafeText(item.reason),
		evidence: mapEvidence(item.evidence_ids, evidenceById, sourceById),
		sources: mapSources(item.source_ids, sourceViewById),
	};
}

function toSourceView(source: SourceSnapshot, evidence: EvidenceView[]): SourceView {
	return {
		id: source.source_id,
		title: shopperSafeText(source.title || source.url),
		url: source.url,
		type: source.source_type,
		provider: providerName(source.provider),
		quality: source.quality.level,
		evidence,
	};
}

function toEvidenceView(evidence: SourceEvidence, source: SourceSnapshot | SourceView | undefined): EvidenceView {
	return {
		id: evidence.evidence_id,
		claim: shopperSafeText(evidence.claim),
		type: evidence.evidence_type,
		confidence: confidenceLabel(evidence.confidence.level, evidence.confidence.score),
		sourceTitle: source?.title ?? 'Source not attached',
		sourceUrl: source && 'url' in source ? source.url : null,
	};
}

function mapEvidence(
	ids: EntityId[],
	evidenceById: Map<EntityId, SourceEvidence>,
	sourceById: Map<EntityId, SourceSnapshot>,
): EvidenceView[] {
	return ids
		.map((id) => evidenceById.get(id))
		.filter((evidence): evidence is SourceEvidence => Boolean(evidence))
		.map((evidence) => toEvidenceView(evidence, sourceById.get(evidence.source_id)));
}

function mapSources(ids: EntityId[], sourceViewById: Map<EntityId, SourceView>): SourceView[] {
	return ids
		.map((id) => sourceViewById.get(id))
		.filter((source): source is SourceView => Boolean(source));
}

function hasMeaningfulRejection(item: RejectedItem): boolean {
	return hasText(item.reason);
}

function hasText(value: string | null | undefined): value is string {
	return Boolean(value?.trim());
}

function confidenceLabel(level: string, score: number | null | undefined): string {
	const scoreText = typeof score === 'number' ? ` ${Math.round(score * 100)}%` : '';
	return `${level}${scoreText}`;
}

export function shopperSafeText(value: string): string {
	return value
		.replace(/\bfixture[-\s]*/gi, '')
		.replace(/\s{2,}/g, ' ')
		.trim();
}

function shopperSafeOptionalText(value: string | null): string | null {
	return value ? shopperSafeText(value) : null;
}

function providerName(provider: Record<string, unknown>): string {
	const value = provider.provider_name;
	return typeof value === 'string' && value.trim() ? value : 'unknown';
}

function resultKey(productId: EntityId | null, listingId: EntityId | null): string {
	return `${productId ?? 'productless'}:${listingId ?? 'listingless'}`;
}
