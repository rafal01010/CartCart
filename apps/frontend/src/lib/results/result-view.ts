import type {
	EntityId,
	RecommendationMode,
	RecommendationModeResult,
	RejectedItem,
	RejectionReason,
	SessionResultsResponse,
	SourceEvidence,
	SourceSnapshot,
} from '$lib/api/types.js';

export interface EvidenceView {
	id: EntityId;
	sourceId: EntityId;
	claim: string;
	type: string;
	typeLabel: string;
	targetLabel: string;
	confidence: string;
	sourceQuality: string;
	sourceTitle: string;
	sourceUrl: string | null;
	timestampLabels: string[];
	metadata: string[];
}

export interface SourceView {
	id: EntityId;
	title: string;
	url: string | null;
	displayUrl: string;
	type: string;
	typeLabel: string;
	provider: string;
	quality: string;
	qualityLabel: string;
	extractionStatus: string;
	capturedLabel: string;
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
	listingTrust: TrustView | null;
	evidence: EvidenceView[];
	sources: SourceView[];
}

export interface TrustView {
	listingId: EntityId;
	level: string;
	levelLabel: string;
	confidence: string;
	summary: string;
	positiveSignals: string[];
	redFlags: string[];
	isBlocking: boolean;
	isRisky: boolean;
	evidence: EvidenceView[];
	sources: SourceView[];
}

export interface RejectedView {
	key: string;
	label: string;
	reasonCode: RejectionReason;
	reasonLabel: string;
	severity: string;
	reason: string;
	evidence: EvidenceView[];
	sources: SourceView[];
}

export interface WarningView {
	key: string;
	text: string;
	evidence: EvidenceView[];
	sources: SourceView[];
}

export interface ResultView {
	versionLabel: string;
	finalMode: ModeView | null;
	decisionModes: ModeView[];
	resultEvidence: EvidenceView[];
	resultSources: SourceView[];
	noStrongBuyReason: string | null;
	whyItWins: string | null;
	modeViews: ModeView[];
	runnerUps: ModeView[];
	trustViews: TrustView[];
	warnings: WarningView[];
	rejectedItems: RejectedView[];
	sourceViews: SourceView[];
	evidenceViews: EvidenceView[];
}

const MODE_LABELS: Record<RecommendationMode, string> = {
	best_overall: 'Best overall',
	best_value: 'Best value',
	within_budget: 'Best within budget',
	stretch_pick: 'Stretch upgrade',
	runner_up: 'Runner-up',
};

const REJECTION_REASON_LABELS: Record<RejectionReason, string> = {
	suspicious_listing: 'Risky listing',
	poor_fit: 'Poor fit',
	overpaying: 'Overpaying',
	missing_critical_feature: 'Missing requirement',
	weak_evidence: 'Weak evidence',
};

const MEANINGFUL_REJECTION_REASONS = new Set<RejectionReason>(
	Object.keys(REJECTION_REASON_LABELS) as RejectionReason[],
);
const MEANINGFUL_REJECTION_SEVERITIES = new Set(['medium', 'high', 'blocking']);

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
	const trustViews = result.trust_assessments.map((trust) =>
		toTrustView(trust, evidenceById, sourceById, sourceViewById),
	);
	const trustViewByListingId = new Map(trustViews.map((trust) => [trust.listingId, trust]));

	const modeViews = result.recommendation_bundle.mode_results.map((mode) =>
		toModeView(mode, evidenceById, sourceById, sourceViewById, trustViewByListingId),
	);
	const finalMode = findFinalMode(result, modeViews);
	const resultEvidence = mapEvidence(result.recommendation_bundle.evidence_ids, evidenceById, sourceById);
	const resultSources = mapSources(
		[
			...result.recommendation_bundle.source_ids,
			...resultEvidence.map((evidence) => evidence.sourceId),
		],
		sourceViewById,
	);

	return {
		versionLabel: `v${result.result_version.version}`,
		finalMode,
		decisionModes: findDecisionModes(modeViews),
		resultEvidence,
		resultSources,
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
		trustViews,
		warnings: buildWarningViews(result, trustViews, evidenceById, sourceById, sourceViewById),
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

export function selectModeView(view: ResultView, selectedKey: string | null): ModeView | null {
	if (!selectedKey) return view.finalMode ?? view.decisionModes[0] ?? null;
	return (
		view.decisionModes.find((mode) => mode.key === selectedKey) ??
		view.finalMode ??
		view.decisionModes[0] ??
		null
	);
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
	if (bundle.no_strong_buy) return null;
	const matchingBestOverall = modes.find(
		(mode) =>
			mode.mode === 'best_overall' &&
			mode.productId === bundle.final_product_id &&
			(!bundle.final_listing_id || mode.listingId === bundle.final_listing_id),
	);
	return (
		matchingBestOverall ??
		modes.find((mode) => mode.mode === 'best_overall') ??
		modes.find(
			(mode) =>
				mode.productId === bundle.final_product_id &&
				(!bundle.final_listing_id || mode.listingId === bundle.final_listing_id),
		) ??
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

function findDecisionModes(modes: ModeView[]): ModeView[] {
	return modes.filter((mode) => mode.mode !== 'runner_up');
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
	sourceById: Map<EntityId, SourceSnapshot>,
	sourceViewById: Map<EntityId, SourceView>,
	trustViewByListingId: Map<EntityId, TrustView>,
): ModeView {
	const evidence = mapEvidence(mode.evidence_ids, evidenceById, sourceById);
	const sources = mapSources(
		[...mode.source_ids, ...evidence.map((item) => item.sourceId)],
		sourceViewById,
	);
	const listingTrust = mode.listing_id ? trustViewByListingId.get(mode.listing_id) ?? null : null;
	return {
		key: `${mode.mode}:${resultKey(mode.product_id, mode.listing_id ?? null)}`,
		mode: mode.mode,
		label: shopperSafeText(mode.title || modeLabel(mode.mode)),
		productId: mode.product_id,
		listingId: mode.listing_id ?? null,
		rationale: shopperSafeText(mode.rationale),
		confidence: confidenceLabel(mode.confidence.level, mode.confidence.score),
		listingTrust,
		evidence,
		sources,
	};
}

function toTrustView(
	trust: {
		listing_id: EntityId;
		level: string;
		confidence: { level: string; score?: number | null };
		summary: string;
		positive_signals: string[];
		red_flags: string[];
		evidence_ids: EntityId[];
		source_ids: EntityId[];
	},
	evidenceById: Map<EntityId, SourceEvidence>,
	sourceById: Map<EntityId, SourceSnapshot>,
	sourceViewById: Map<EntityId, SourceView>,
): TrustView {
	const evidence = mapEvidence(trust.evidence_ids, evidenceById, sourceById);
	return {
		listingId: trust.listing_id,
		level: trust.level,
		levelLabel: trustLevelLabel(trust.level),
		confidence: confidenceLabel(trust.confidence.level, trust.confidence.score),
		summary: shopperSafeText(trust.summary),
		positiveSignals: trust.positive_signals.map(shopperSafeText),
		redFlags: trust.red_flags.map(shopperSafeText),
		isBlocking: trust.level === 'suspicious',
		isRisky: trust.level === 'suspicious' || trust.level === 'weak',
		evidence,
		sources: mapSources([...trust.source_ids, ...evidence.map((item) => item.sourceId)], sourceViewById),
	};
}

function toRejectedView(
	item: RejectedItem,
	evidenceById: Map<EntityId, SourceEvidence>,
	sourceById: Map<EntityId, SourceSnapshot>,
	sourceViewById: Map<EntityId, SourceView>,
): RejectedView {
	const evidence = mapEvidence(item.evidence_ids, evidenceById, sourceById);
	return {
		key: resultKey(item.product_id ?? null, item.listing_id ?? null),
		label: item.listing_id
			? `Listing ${shortEntityId(item.listing_id)}`
			: `Product ${shortEntityId(item.product_id)}`,
		reasonCode: item.reason_code,
		reasonLabel: rejectionReasonLabel(item.reason_code),
		severity: item.severity,
		reason: shopperSafeText(item.reason),
		evidence,
		sources: mapSources([...item.source_ids, ...evidence.map((record) => record.sourceId)], sourceViewById),
	};
}

function toSourceView(source: SourceSnapshot, evidence: EvidenceView[]): SourceView {
	const neutralUrl = neutralOutboundUrl(source.url);
	return {
		id: source.source_id,
		title: shopperSafeText(source.title || source.url),
		url: neutralUrl,
		displayUrl: displayUrl(neutralUrl ?? source.url),
		type: source.source_type,
		typeLabel: readableLabel(source.source_type),
		provider: providerName(source.provider),
		quality: source.quality.level,
		qualityLabel: sourceQualityLabel(source.quality.level, source.quality.score),
		extractionStatus: extractionStatusLabel(source.extraction_status),
		capturedLabel: dateLabel(source.captured_at),
		evidence,
	};
}

function toEvidenceView(evidence: SourceEvidence, source: SourceSnapshot | SourceView | undefined): EvidenceView {
	const sourceUrl = source && 'url' in source ? source.url : null;
	return {
		id: evidence.evidence_id,
		sourceId: evidence.source_id,
		claim: shopperSafeText(evidence.claim),
		type: evidence.evidence_type,
		typeLabel: readableLabel(evidence.evidence_type),
		targetLabel: evidenceTargetLabel(evidence.target),
		confidence: confidenceLabel(evidence.confidence.level, evidence.confidence.score),
		sourceQuality: sourceQualityLabel(evidence.source_quality.level, evidence.source_quality.score),
		sourceTitle: source?.title ? shopperSafeText(source.title) : 'Source not attached',
		sourceUrl: typeof sourceUrl === 'string' ? neutralOutboundUrl(sourceUrl) : sourceUrl,
		timestampLabels: (evidence.timestamp_references ?? []).map(timestampLabel),
		metadata: evidenceMetadata(evidence),
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
	const seen = new Set<EntityId>();
	return ids
		.filter((id) => {
			if (seen.has(id)) return false;
			seen.add(id);
			return true;
		})
		.map((id) => sourceViewById.get(id))
		.filter((source): source is SourceView => Boolean(source));
}

function buildWarningViews(
	result: SessionResultsResponse,
	trustViews: TrustView[],
	evidenceById: Map<EntityId, SourceEvidence>,
	sourceById: Map<EntityId, SourceSnapshot>,
	sourceViewById: Map<EntityId, SourceView>,
): WarningView[] {
	const warnings = new Map<string, WarningView>();
	const appendWarning = (
		key: string,
		text: string,
		evidenceIds: EntityId[],
		sourceIds: EntityId[],
	) => {
		const safeText = shopperSafeText(text);
		if (!hasText(safeText)) return;
		const evidence = mapEvidence(evidenceIds, evidenceById, sourceById);
		const sources = mapSources([...sourceIds, ...evidence.map((item) => item.sourceId)], sourceViewById);
		const existing = warnings.get(safeText);
		if (existing) {
			existing.evidence = dedupeEvidence([...existing.evidence, ...evidence]);
			existing.sources = dedupeSources([...existing.sources, ...sources]);
			return;
		}
		warnings.set(safeText, {
			key,
			text: safeText,
			evidence,
			sources,
		});
	};

	result.recommendation_bundle.warnings.forEach((warning, index) => {
		appendWarning(
			`bundle:${index}`,
			warning,
			result.recommendation_bundle.evidence_ids,
			result.recommendation_bundle.source_ids,
		);
	});
	result.category_analyses.forEach((analysis) => {
		analysis.warnings.forEach((warning, index) => {
			appendWarning(
				`analysis:${analysis.product_id}:${index}`,
				warning,
				analysis.evidence_ids,
				analysis.source_ids,
			);
		});
	});
	trustViews.forEach((trust) => {
		trust.redFlags.forEach((warning, index) => {
			appendWarning(`trust:${trust.listingId}:${index}`, warning, [], []);
			const existing = warnings.get(warning);
			if (existing) {
				existing.evidence = dedupeEvidence([...existing.evidence, ...trust.evidence]);
				existing.sources = dedupeSources([...existing.sources, ...trust.sources]);
			}
		});
	});

	return [...warnings.values()];
}

function hasMeaningfulRejection(item: RejectedItem): boolean {
	return (
		hasText(item.reason) &&
		MEANINGFUL_REJECTION_REASONS.has(item.reason_code) &&
		MEANINGFUL_REJECTION_SEVERITIES.has(item.severity)
	);
}

function hasText(value: string | null | undefined): value is string {
	return Boolean(value?.trim());
}

function confidenceLabel(level: string, score: number | null | undefined): string {
	const scoreText = typeof score === 'number' ? ` ${Math.round(score * 100)}%` : '';
	return `${level}${scoreText}`;
}

function sourceQualityLabel(level: string, score: number | null | undefined): string {
	const scoreText = typeof score === 'number' ? ` ${Math.round(score * 100)}%` : '';
	return `${readableLabel(level)}${scoreText}`;
}

function extractionStatusLabel(status: string): string {
	return readableLabel(status || 'unknown');
}

function readableLabel(value: string): string {
	return value
		.replaceAll('_', ' ')
		.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function evidenceTargetLabel(target: Record<string, unknown>): string {
	const targetType = target.target_type;
	if (targetType === 'product') return 'Product detail';
	if (targetType === 'listing') return 'Listing detail';
	if (targetType === 'seller') return 'Seller signal';
	if (targetType === 'review') return 'Review signal';
	if (targetType === 'region') return 'Regional detail';
	if (targetType === 'source_metadata') return 'Source context';
	if (targetType === 'candidate') return 'Candidate detail';
	return 'Supporting detail';
}

function evidenceMetadata(evidence: SourceEvidence): string[] {
	const metadata: string[] = [];
	if (evidence.video?.transcript_availability) {
		metadata.push(`Transcript: ${readableLabel(evidence.video.transcript_availability)}`);
	}
	if (evidence.video?.channel_name) {
		metadata.push(`Channel: ${shopperSafeText(evidence.video.channel_name)}`);
	}
	if (evidence.video?.sponsorship_disclosed) {
		metadata.push('Sponsorship disclosed');
	}
	if (evidence.video?.affiliate_links_disclosed) {
		metadata.push('Affiliate links disclosed by source');
	}
	if (evidence.video?.affiliate_bias_risk) {
		metadata.push(`Bias risk: ${confidenceLabel(
			evidence.video.affiliate_bias_risk.level,
			evidence.video.affiliate_bias_risk.score,
		)}`);
	}
	return metadata;
}

function timestampLabel(timestamp: {
	start_seconds: number;
	end_seconds?: number | null;
	label?: string | null;
}): string {
	if (timestamp.label) return shopperSafeText(timestamp.label);
	const start = durationLabel(timestamp.start_seconds);
	const end = typeof timestamp.end_seconds === 'number' ? durationLabel(timestamp.end_seconds) : null;
	return end ? `${start}-${end}` : start;
}

function durationLabel(seconds: number): string {
	const rounded = Math.max(0, Math.floor(seconds));
	const minutes = Math.floor(rounded / 60);
	const remainingSeconds = String(rounded % 60).padStart(2, '0');
	return `${minutes}:${remainingSeconds}`;
}

function dateLabel(value: string): string {
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return 'Date unavailable';
	return new Intl.DateTimeFormat('en', {
		year: 'numeric',
		month: 'short',
		day: 'numeric',
	}).format(date);
}

function trustLevelLabel(level: string): string {
	const labels: Record<string, string> = {
		strong: 'Strong listing',
		reasonable: 'Reasonable listing',
		mixed: 'Mixed listing',
		weak: 'Weak listing',
		suspicious: 'Blocked listing',
		unknown: 'Unknown listing',
	};
	return labels[level] ?? 'Listing check';
}

function rejectionReasonLabel(reason: RejectionReason): string {
	return REJECTION_REASON_LABELS[reason];
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

function dedupeEvidence(evidence: EvidenceView[]): EvidenceView[] {
	const seen = new Set<EntityId>();
	return evidence.filter((item) => {
		if (seen.has(item.id)) return false;
		seen.add(item.id);
		return true;
	});
}

function dedupeSources(sources: SourceView[]): SourceView[] {
	const seen = new Set<EntityId>();
	return sources.filter((source) => {
		if (seen.has(source.id)) return false;
		seen.add(source.id);
		return true;
	});
}

export function neutralOutboundUrl(value: string | null | undefined): string | null {
	if (!value) return null;
	try {
		const url = new URL(value);
		if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
		for (const key of [...url.searchParams.keys()]) {
			if (isTrackingQueryKey(key)) {
				url.searchParams.delete(key);
			}
		}
		url.hash = '';
		return url.toString();
	} catch {
		return null;
	}
}

function displayUrl(value: string): string {
	try {
		const url = new URL(value);
		return url.hostname.replace(/^www\./, '');
	} catch {
		return value;
	}
}

const TRACKING_QUERY_KEYS = new Set([
	'affiliate',
	'affiliate_id',
	'asc_source',
	'ascsubtag',
	'camp',
	'creative',
	'fbclid',
	'gclid',
	'linkcode',
	'msclkid',
	'ref',
	'ref_',
	'referrer',
	'smclid',
	'source',
	'tag',
]);

function isTrackingQueryKey(key: string): boolean {
	const normalized = key.toLowerCase();
	return (
		normalized.startsWith('utm_') ||
		normalized.startsWith('aff_') ||
		normalized.includes('affiliate') ||
		TRACKING_QUERY_KEYS.has(normalized)
	);
}

function resultKey(productId: EntityId | null, listingId: EntityId | null): string {
	return `${productId ?? 'productless'}:${listingId ?? 'listingless'}`;
}
