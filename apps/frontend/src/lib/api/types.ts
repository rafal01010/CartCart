export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export type Timestamp = string;
export type EntityId = string;
export type SessionId = EntityId;
export type RunId = EntityId;
export type CandidateId = EntityId;

export type FieldSource = 'user_provided' | 'inferred' | 'defaulted';
export type BudgetMode = 'hard_cap' | 'preferred';
export type PreferenceMode = 'hard' | 'soft';
export type RunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type GuidedIntakeStatus = 'collecting' | 'blocked' | 'ready_for_analysis' | 'analysis_started';
export type GuidedAnswerSurface = 'textbox' | 'inline_choice';
export type GuidedQuestionPurpose =
	| 'first_question'
	| 'use_case'
	| 'budget'
	| 'priorities'
	| 'constraints'
	| 'considered_products'
	| 'comparison'
	| 'combined_optional'
	| 'clarification';
export type GuidedCaptureTarget =
	| 'shopping_question'
	| 'use_case'
	| 'budget'
	| 'priorities'
	| 'constraints'
	| 'considered_product_names'
	| 'considered_product_descriptions'
	| 'comparison_candidates'
	| 'product_category';
export type InlineChoiceControlType = 'yes_no' | 'two_option' | 'two_option_plus_type_answer';
export type RegionSetupStatus = 'not_needed' | 'needs_answer' | 'provided' | 'refused';
export type RunStage =
	| 'intake'
	| 'query_planning'
	| 'discovery'
	| 'extraction'
	| 'deduplication'
	| 'listing_trust'
	| 'category_analysis'
	| 'comparison_decision'
	| 'verification'
	| 'complete';
export type ConfidenceLevel = 'low' | 'medium' | 'high' | 'unknown';
export type ListingTrustLevel = 'strong' | 'reasonable' | 'mixed' | 'weak' | 'suspicious' | 'unknown';
export type RecommendationMode =
	| 'best_overall'
	| 'best_value'
	| 'within_budget'
	| 'stretch_pick'
	| 'runner_up';
export type RejectionSeverity = 'low' | 'medium' | 'high' | 'blocking';
export type RejectionReason =
	| 'suspicious_listing'
	| 'poor_fit'
	| 'overpaying'
	| 'missing_critical_feature'
	| 'weak_evidence';

export interface Money {
	amount: string | number;
	currency: string;
}

export interface Region {
	country_code: string;
	currency?: string | null;
	locale?: string | null;
}

export interface RegionPreference {
	region: Region;
	source: FieldSource;
	notes?: string | null;
}

export interface BudgetConstraint {
	amount: Money;
	mode: BudgetMode;
	source?: FieldSource;
	notes?: string | null;
}

export interface PreferenceConstraint {
	text: string;
	mode: PreferenceMode;
	source?: FieldSource;
}

export interface CreateSessionRequest {
	query: string;
	region?: RegionPreference | null;
	budget?: BudgetConstraint | null;
	constraints?: PreferenceConstraint[];
	preferences?: PreferenceConstraint[];
}

export interface UpdateShoppingBriefRequest {
	category?: string | null;
	category_source?: FieldSource | null;
	region?: RegionPreference | null;
	budget?: BudgetConstraint | null;
	constraints?: PreferenceConstraint[] | null;
	preferences?: PreferenceConstraint[] | null;
}

export interface ShoppingBrief {
	schema_version: number;
	original_query: string;
	category?: string | null;
	category_source?: FieldSource | null;
	region?: RegionPreference | null;
	budget?: BudgetConstraint | null;
	constraints: PreferenceConstraint[];
	preferences: PreferenceConstraint[];
}

export interface CanonicalProduct {
	schema_version: number;
	product_id: EntityId;
	name: string;
	brand?: string | null;
	model?: string | null;
	category?: string | null;
	source_ids: EntityId[];
	listing_ids: EntityId[];
}

export interface UserAddedProduct {
	schema_version: number;
	candidate_id: CandidateId;
	input_text?: string | null;
	url?: string | null;
	product?: CanonicalProduct | null;
	listing?: JsonObject | null;
	notes?: string | null;
	created_at: Timestamp;
}

export interface SessionStateResponse {
	schema_version: number;
	session_id: SessionId;
	original_input: CreateSessionRequest;
	current_brief: ShoppingBrief;
	created_at: Timestamp;
	updated_at: Timestamp;
	user_added_products: UserAddedProduct[];
}

export interface InlineChoiceOption {
	choice_id: string;
	label: string;
	description?: string | null;
}

export interface InlineChoiceControl {
	control_id: string;
	control_type: InlineChoiceControlType;
	options: [InlineChoiceOption, InlineChoiceOption];
	custom_answer_label?: string | null;
}

export interface CombinedOptionalQuestionPrompt {
	text: string;
	capture_targets: GuidedCaptureTarget[];
}

export interface CurrentGuidedQuestion {
	schema_version: number;
	question_id: string;
	text: string;
	purpose: GuidedQuestionPurpose;
	answer_surface: GuidedAnswerSurface;
	capture_targets: GuidedCaptureTarget[];
	inline_choice?: InlineChoiceControl | null;
	combined_optional_prompt?: CombinedOptionalQuestionPrompt | null;
}

export type NaturalLanguageGuidedAnswer = {
	answer_type: 'natural_language';
	text: string;
};

export type YesNoGuidedAnswer = {
	answer_type: 'yes_no';
	value: boolean;
};

export type ChoiceGuidedAnswer = {
	answer_type: 'choice';
	choice_id: string;
};

export type ChoiceWithTextGuidedAnswer = {
	answer_type: 'choice_with_text';
	text: string;
	choice_id?: string | null;
};

export type GuidedAnswer =
	| NaturalLanguageGuidedAnswer
	| YesNoGuidedAnswer
	| ChoiceGuidedAnswer
	| ChoiceWithTextGuidedAnswer;

export interface GuidedAnswerSubmission {
	schema_version?: number;
	question_id: string;
	answer: GuidedAnswer;
}

export interface CreateGuidedSessionRequest {
	query: string;
	region_setup?: RegionSetupSubmission | null;
}

export interface GuidedSessionResponse {
	schema_version: number;
	session_id: SessionId;
	guide: GuidedIntakeState;
}

export interface GuidedReanswerRequest {
	question_id: string;
}

export interface ReanswerableQuestion {
	question_id: string;
	label: string;
}

export interface PriorQuestionNavigationState {
	can_go_back: boolean;
	current_reanswer_question_id?: string | null;
	reanswerable_questions: ReanswerableQuestion[];
}

export interface SkippableQuestionState {
	can_skip: boolean;
	label: 'Skip question';
}

export interface AnalysisStartAvailability {
	enough_information: boolean;
	can_skip_all_and_start_analysis: boolean;
	label: 'Skip all and start analysis';
	message?: string | null;
}

export interface LocalRegionSetupState {
	status: RegionSetupStatus;
	prompt_text?: string | null;
	region?: Region | null;
	can_refuse: boolean;
	resumes_pending_question: boolean;
}

export interface RegionSetupSubmission {
	status: 'provided' | 'refused';
	region?: Region | null;
}

export interface ProgressDisplayStatus {
	kind:
		| 'idle'
		| 'checking_options'
		| 'comparing_evidence'
		| 'verifying_risky_listings'
		| 'preparing_recommendation'
		| 'ready'
		| 'blocked';
	message: string;
}

export interface ShoppingGuardrailResult {
	schema_version: number;
	decision: 'allowed' | 'blocked';
	reason?: 'off_topic' | 'unsafe_product' | 'illegal_product' | 'inappropriate_product' | null;
	message?: string | null;
}

export interface GuidedIntakeState {
	schema_version: number;
	status: GuidedIntakeStatus;
	current_question?: CurrentGuidedQuestion | null;
	navigation: PriorQuestionNavigationState;
	skippable_question: SkippableQuestionState;
	analysis_start: AnalysisStartAvailability;
	region_setup: LocalRegionSetupState;
	progress?: ProgressDisplayStatus | null;
	guardrail?: ShoppingGuardrailResult | null;
	ready_brief?: ShoppingBrief | null;
}

export interface CreateUserAddedProductRequest {
	input_text?: string | null;
	url?: string | null;
	name?: string | null;
	brand?: string | null;
	model?: string | null;
	category?: string | null;
	notes?: string | null;
}

export interface ErrorBody {
	code: string;
	message: string;
	request_id: string;
	details?: JsonValue;
}

export interface ErrorEnvelope {
	error: ErrorBody;
}

export interface Confidence {
	score?: number | null;
	level: ConfidenceLevel;
	rationale?: string | null;
}

export interface ShoppingRunRecord {
	schema_version: number;
	run_id: RunId;
	session_id: SessionId;
	status: RunStatus;
	current_stage?: RunStage | null;
	created_at: Timestamp;
	started_at?: Timestamp | null;
	completed_at?: Timestamp | null;
	error?: ErrorEnvelope | null;
}

export interface RunEvent {
	schema_version: number;
	event_id: CandidateId;
	run_id: RunId;
	sequence: number;
	stage: RunStage;
	status: RunStatus;
	message: string;
	occurred_at: Timestamp;
	error?: ErrorEnvelope | null;
}

export interface CreateRefinementRequest {
	instruction: string;
	region?: RegionPreference | null;
	budget?: BudgetConstraint | null;
	constraints?: PreferenceConstraint[];
	preferences?: PreferenceConstraint[];
}

export interface RefinementRequest extends CreateRefinementRequest {
	schema_version: number;
	refinement_id: CandidateId;
	session_id: SessionId;
	run_id?: RunId | null;
	created_at: Timestamp;
}

export interface RefinementRunResponse {
	refinement: RefinementRequest;
	run: ShoppingRunRecord;
}

export interface ResultVersionResponse {
	result_version_id: CandidateId;
	run_id: RunId;
	version: number;
	recommendation_bundle_id: CandidateId;
	comparison_matrix_id: CandidateId;
}

export interface SourceQuality {
	level: string;
	score?: number | null;
	rationale?: string | null;
}

export interface TimestampReference {
	start_seconds: number;
	end_seconds?: number | null;
	label?: string | null;
}

export interface VideoSource {
	video_id: string;
	url: string;
	title?: string | null;
	channel_name?: string | null;
	published_at?: Timestamp | null;
	duration_seconds?: number | null;
	transcript_availability: string;
	sponsorship_disclosed?: boolean | null;
	affiliate_links_disclosed?: boolean | null;
	affiliate_bias_risk?: Confidence | null;
	bias_notes?: string | null;
}

export interface SourceSnapshot {
	schema_version: number;
	source_id: EntityId;
	url: string;
	source_type: string;
	provider: JsonObject;
	title?: string | null;
	extraction_status: string;
	http_status_code?: number | null;
	quality: SourceQuality;
	captured_at: Timestamp;
	video?: VideoSource | null;
}

export interface SourceEvidence {
	evidence_id: EntityId;
	source_id: EntityId;
	target: JsonObject;
	evidence_type: string;
	claim: string;
	confidence: Confidence;
	source_quality: SourceQuality;
	timestamp_references?: TimestampReference[];
	video?: VideoSource | null;
}

export interface ListingTrustAssessment {
	schema_version: number;
	listing_id: EntityId;
	level: ListingTrustLevel;
	confidence: Confidence;
	summary: string;
	red_flags: string[];
	positive_signals: string[];
	evidence_ids: EntityId[];
	source_ids: EntityId[];
	assessed_at: Timestamp;
}

export interface CategoryAnalysis {
	schema_version: number;
	product_id: EntityId;
	listing_ids: EntityId[];
	category: string;
	fit_summary: string;
	strengths: string[];
	weaknesses: string[];
	warnings: string[];
	confidence: Confidence;
	evidence_ids: EntityId[];
	source_ids: EntityId[];
}

export interface ComparisonCriterion {
	name: string;
	weight?: number | null;
	higher_is_better: boolean;
}

export interface ComparisonRow {
	product_id: EntityId;
	listing_id?: EntityId | null;
	scores: Record<string, number>;
	evidence_ids: EntityId[];
	summary?: string | null;
}

export interface ComparisonMatrix {
	schema_version: number;
	criteria: ComparisonCriterion[];
	rows: ComparisonRow[];
}

export interface RecommendationModeResult {
	mode: RecommendationMode;
	product_id: EntityId;
	listing_id?: EntityId | null;
	title: string;
	rationale: string;
	confidence: Confidence;
	evidence_ids: EntityId[];
	source_ids: EntityId[];
}

export interface RejectedItem {
	product_id?: EntityId | null;
	listing_id?: EntityId | null;
	reason_code: RejectionReason;
	reason: string;
	severity: RejectionSeverity;
	evidence_ids: EntityId[];
	source_ids: EntityId[];
}

export interface RecommendationBundle {
	schema_version: number;
	bundle_id: CandidateId;
	final_product_id?: EntityId | null;
	final_listing_id?: EntityId | null;
	no_strong_buy: boolean;
	no_strong_buy_reason?: string | null;
	final_rationale?: string | null;
	runner_up_product_ids: EntityId[];
	mode_results: RecommendationModeResult[];
	comparison_matrix: ComparisonMatrix;
	rejected_items: RejectedItem[];
	warnings: string[];
	evidence_ids: EntityId[];
	source_ids: EntityId[];
}

export interface SessionResultsResponse {
	result_version: ResultVersionResponse;
	trust_assessments: ListingTrustAssessment[];
	category_analyses: CategoryAnalysis[];
	agent_records: JsonObject[];
	comparison_matrix: ComparisonMatrix;
	recommendation_bundle: RecommendationBundle;
	source_snapshots: SourceSnapshot[];
	source_evidence: SourceEvidence[];
}
