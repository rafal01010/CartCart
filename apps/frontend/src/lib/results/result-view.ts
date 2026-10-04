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
	productName: string;
	listingTitle: string | null;
	sellerName: string | null;
	priceLabel: string | null;
	purchaseUrl: string | null;
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

export interface ComparisonProductView {
	key: string;
	productId: EntityId;
	name: string;
	listingId: EntityId | null;
	seller: string | null;
	price: string | null;
	listingRisk: string | null;
	manual: boolean;
	criteria: { name: string; value: string }[];
	summary: string | null;
	evidence: EvidenceView[];
	sources: SourceView[];
}

export interface ConsideredProductView {
	candidateId: EntityId;
	askedFor: string;
	status: 'confirmed' | 'possible' | 'unresolved' | 'manual' | 'excluded';
	matchedName: string | null;
	possibleNames: string[];
	exclusionReason: string | null;
	manualSeller: string | null;
	manualPrice: string | null;
	manualUnknowns: string[];
	listingRisk: string | null;
	inComparison: boolean;
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
	hasWeakEvidence: boolean;
	hasConflictingEvidence: boolean;
	hasPartialSources: boolean;
	comparisonProducts: ComparisonProductView[];
	consideredProducts: ConsideredProductView[];
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
	const productById = new Map(result.products.map((product) => [product.product_id, product]));
	const listingById = new Map(result.listings.map((listing) => [listing.listing_id, listing]));
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
	const comparisonProducts = buildComparisonProducts(result, productById, listingById, evidenceById, sourceById, sourceViewById, trustViewByListingId);
	const comparisonIds = new Set(comparisonProducts.map((item) => item.productId));

	const projectMode = (mode: RecommendationModeResult) =>
		toModeView(
			mode,
			productById.get(mode.product_id),
			mode.listing_id ? listingById.get(mode.listing_id) : undefined,
			evidenceById,
			sourceById,
			sourceViewById,
			trustViewByListingId,
		);
	const modeViews = result.recommendation_bundle.mode_results.map(projectMode);
	const finalRecommendation = buildFinalRecommendation(result);
	const finalMode = finalRecommendation ? projectMode(finalRecommendation) : null;
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
		decisionModes: findDecisionModes(modeViews, finalMode),
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
		runnerUps: dedupeModes(buildRunnerUpRecommendations(result).map(projectMode)),
		trustViews,
		warnings: buildWarningViews(result, trustViews, evidenceById, sourceById, sourceViewById),
		rejectedItems: result.recommendation_bundle.rejected_items
			.filter(hasMeaningfulRejection)
			.map((item) =>
				toRejectedView(item, productById, listingById, evidenceById, sourceById, sourceViewById),
			),
		sourceViews,
		evidenceViews,
		hasWeakEvidence: evidenceViews.some((item) => /low|unknown/i.test(item.confidence)),
		hasConflictingEvidence: result.source_evidence.some((item) =>
			/conflict|contradict/i.test(`${item.evidence_type} ${item.claim}`),
		),
		hasPartialSources: result.source_snapshots.some(
			(source) => !['succeeded', 'success', 'complete', 'completed'].includes(source.extraction_status),
		),
		comparisonProducts,
		consideredProducts: result.considered_products.map(({ candidate, status, exclusion_reason }) => {
			const matchedId = candidate.product?.product_id;
			const matchedProduct = matchedId ? productById.get(matchedId) : null;
			const listingId = candidate.listing?.listing_id;
			const trust = listingId ? trustViewByListingId.get(listingId) : null;
			const details = candidate.manual_details;
			return {
				candidateId: candidate.candidate_id,
				askedFor: shopperSafeText(candidate.input_text ?? candidate.url ?? candidate.product?.name ?? 'Product you asked us to check'),
				status,
				matchedName: matchedProduct ? shopperSafeText(matchedProduct.name) : status === 'manual' ? shopperSafeText(candidate.product?.name ?? '') : null,
				possibleNames: (candidate.possible_product_ids ?? []).map((id) => productById.get(id)?.name).filter((name): name is string => Boolean(name)).map(shopperSafeText),
				exclusionReason: exclusion_reason ? shopperSafeText(exclusion_reason) : null,
				manualSeller: details?.seller ? shopperSafeText(details.seller) : null,
				manualPrice: details?.price ? moneyLabel(details.price.amount, details.price.currency) : null,
				manualUnknowns: status === 'manual' ? [
					...(!details?.seller ? ['seller'] : []),
					...(!details?.price ? ['price'] : []),
					...(!details?.availability ? ['availability'] : []),
					...(!details?.warranty ? ['warranty'] : []),
				] : [],
				listingRisk: listingRiskText(trust ?? null, candidate.listing?.seller.trust_signal),
				inComparison: matchedId ? comparisonIds.has(matchedId) : false,
			};
		}),
	};
}

function buildComparisonProducts(
	result: SessionResultsResponse,
	productById: Map<EntityId, SessionResultsResponse['products'][number]>,
	listingById: Map<EntityId, SessionResultsResponse['listings'][number]>,
	evidenceById: Map<EntityId, SourceEvidence>,
	sourceById: Map<EntityId, SourceSnapshot>,
	sourceViewById: Map<EntityId, SourceView>,
	trustByListingId: Map<EntityId, TrustView>,
): ComparisonProductView[] {
	const matrix = result.comparison_matrix;
	const shortlist = [
		...result.shortlist,
		...matrix.rows.map((row) => ({ candidate_id: row.product_id, product_id: row.product_id, listing_id: row.listing_id ?? null, position: null })),
	];
	const seen = new Set<string>();
	return shortlist.flatMap((item) => {
		const product = productById.get(item.product_id);
		if (!product) return [];
		const row = matrix.rows.find((candidate) => candidate.product_id === item.product_id && candidate.listing_id === item.listing_id)
			?? matrix.rows.find((candidate) => candidate.product_id === item.product_id);
		const listingId = row?.listing_id ?? item.listing_id;
		const key = `${item.product_id}:${listingId ?? 'no-listing'}`;
		if (seen.has(key)) return [];
		seen.add(key);
		const listing = listingId ? listingById.get(listingId) : null;
		const trust = listingId ? trustByListingId.get(listingId) : null;
		const manual = !listing && result.considered_products.some(({ candidate }) => candidate.manual_fallback_reason && candidate.product?.product_id === item.product_id);
		const evidence = row ? mapEvidence(row.evidence_ids, evidenceById, sourceById) : [];
		return [{
			key,
			productId: item.product_id,
			name: shopperSafeText(product.name),
			listingId: listingId ?? null,
			seller: manual ? null : listing ? shopperSafeText(listing.seller.seller_name) : null,
			price: manual ? null : listing?.price ? moneyLabel(listing.price.amount, listing.price.currency) : null,
			listingRisk: listingRiskText(trust ?? null, listing?.seller.trust_signal),
			manual: Boolean(manual),
			criteria: matrix.criteria.map((criterion) => ({
				name: shopperSafeText(criterion.name),
				value: row && evidence.length > 0 && typeof row.scores[criterion.name] === 'number'
					? scoreLabel(row.scores[criterion.name]) : 'Unknown',
			})),
			summary: row?.summary ? shopperSafeText(row.summary) : null,
			evidence,
			sources: mapSources(evidence.map((item) => item.sourceId), sourceViewById),
		}];
	});
}

function listingRiskText(trust: TrustView | null, sellerSignal: string | undefined): string | null {
	if (trust?.isRisky) return trust.summary;
	if (sellerSignal === 'suspicious') return 'This seller or listing has a suspicious trust signal.';
	if (sellerSignal === 'weak') return 'This seller or listing has weak trust signals.';
	return null;
}

export function modeLabel(mode: RecommendationMode): string {
	return MODE_LABELS[mode];
}

export function selectModeView(view: ResultView, selectedKey: string | null): ModeView | null {
	if (!view.finalMode || view.noStrongBuyReason) return null;
	if (!selectedKey) return view.finalMode;
	return (
		view.decisionModes.find((mode) => mode.key === selectedKey) ??
		view.finalMode
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

function buildFinalRecommendation(result: SessionResultsResponse): RecommendationModeResult | null {
	const bundle = result.recommendation_bundle;
	const productId = bundle.final_product_id;
	if (bundle.no_strong_buy || !productId || !result.products.some((product) => product.product_id === productId)) return null;
	const listingId = bundle.final_listing_id ?? null;
	const matchingBestOverall = bundle.mode_results.find(
		(mode) =>
			mode.mode === 'best_overall' &&
			mode.product_id === productId &&
			(mode.listing_id ?? null) === listingId,
	);
	const analysis = result.category_analyses.find((item) => item.product_id === productId);
	const row = result.comparison_matrix.rows.find(
		(item) => item.product_id === productId && (item.listing_id ?? null) === listingId,
	);
	return {
		mode: 'best_overall',
		product_id: productId,
		listing_id: listingId,
		title: matchingBestOverall?.title ?? modeLabel('best_overall'),
		rationale: bundle.final_rationale ?? matchingBestOverall?.rationale ?? '',
		confidence: matchingBestOverall?.confidence ?? analysis?.confidence ?? { level: 'unknown' },
		evidence_ids: [...new Set([
			...bundle.evidence_ids,
			...(matchingBestOverall?.evidence_ids ?? []),
			...(row?.evidence_ids ?? []),
			...(analysis?.evidence_ids ?? []),
		])],
		source_ids: [...new Set([
			...bundle.source_ids,
			...(matchingBestOverall?.source_ids ?? []),
			...(analysis?.source_ids ?? []),
		])],
	};
}

function buildRunnerUpRecommendations(result: SessionResultsResponse): RecommendationModeResult[] {
	const bundle = result.recommendation_bundle;
	const runnerIds = new Set([
		...bundle.runner_up_product_ids,
		...bundle.mode_results.filter((mode) => mode.mode === 'runner_up').map((mode) => mode.product_id),
	]);
	return [...runnerIds].flatMap((productId) => {
		if (productId === bundle.final_product_id || !result.products.some((product) => product.product_id === productId)) return [];
		const savedModes = bundle.mode_results.filter((mode) => mode.product_id === productId);
		if (savedModes.length) return savedModes;
		const rows = result.comparison_matrix.rows.filter((item) => item.product_id === productId);
		const listingReferences = rows.length ? rows : result.shortlist.filter((item) => item.product_id === productId);
		const listingIds = new Set(listingReferences.map((item) => item.listing_id ?? null));
		const analysis = result.category_analyses.find((item) => item.product_id === productId);
		return [{
			mode: 'runner_up',
			product_id: productId,
			listing_id: listingIds.size === 1 ? [...listingIds][0] ?? null : null,
			title: modeLabel('runner_up'),
			rationale: (rows.length === 1 ? rows[0]?.summary : null) ?? analysis?.fit_summary ?? '',
			confidence: analysis?.confidence ?? { level: 'unknown' },
			evidence_ids: [...new Set([...rows.flatMap((row) => row.evidence_ids), ...(analysis?.evidence_ids ?? [])])],
			source_ids: analysis?.source_ids ?? [],
		} satisfies RecommendationModeResult];
	});
}

function findDecisionModes(modes: ModeView[], finalMode: ModeView | null): ModeView[] {
	if (!finalMode) return [];
	return [finalMode, ...modes.filter((mode) => mode.mode !== 'runner_up' && mode.mode !== 'best_overall')];
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
	product: SessionResultsResponse['products'][number] | undefined,
	listing: SessionResultsResponse['listings'][number] | undefined,
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
		productName: shopperSafeText(product?.name ?? mode.title ?? modeLabel(mode.mode)),
		listingTitle: listing ? shopperSafeText(listing.title) : null,
		sellerName: listing ? shopperSafeText(listing.seller.seller_name) : null,
		priceLabel: listing?.price ? moneyLabel(listing.price.amount, listing.price.currency) : null,
		purchaseUrl: neutralOutboundUrl(listing?.canonical_url ?? listing?.url),
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
	productById: Map<EntityId, SessionResultsResponse['products'][number]>,
	listingById: Map<EntityId, SessionResultsResponse['listings'][number]>,
	evidenceById: Map<EntityId, SourceEvidence>,
	sourceById: Map<EntityId, SourceSnapshot>,
	sourceViewById: Map<EntityId, SourceView>,
): RejectedView {
	const evidence = mapEvidence(item.evidence_ids, evidenceById, sourceById);
	return {
		key: resultKey(item.product_id ?? null, item.listing_id ?? null),
		label:
			(item.product_id ? productById.get(item.product_id)?.name : null) ??
			(item.listing_id ? listingById.get(item.listing_id)?.title : null) ??
			'Candidate',
		reasonCode: item.reason_code,
		reasonLabel: rejectionReasonLabel(item.reason_code),
		severity: item.severity,
		reason: shopperSafeText(item.reason),
		evidence,
		sources: mapSources([...item.source_ids, ...evidence.map((record) => record.sourceId)], sourceViewById),
	};
}

function moneyLabel(amount: string | number, currency: string): string {
	const numericAmount = typeof amount === 'number' ? amount : Number(amount);
	if (!Number.isFinite(numericAmount)) return `${currency} ${amount}`;
	try {
		return new Intl.NumberFormat('en', {
			style: 'currency',
			currency,
			maximumFractionDigits: Number.isInteger(numericAmount) ? 0 : 2,
		}).format(numericAmount);
	} catch {
		return `${currency} ${numericAmount}`;
	}
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
