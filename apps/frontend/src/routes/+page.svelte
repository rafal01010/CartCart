<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';
	import { createApiClient, subscribeToRunEvents } from '$lib/api/index.js';
	import { userFacingErrorMessage } from '$lib/api/user-facing-error.js';
	import type { CreateUserAddedProductRequest, DecisionHistoryResponse, GuidedAnswer, GuidedIntakeState, RunId, SessionId, SessionStateResponse, ShoppingRunRecord } from '$lib/api/types.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import RefinementPrompt from '$lib/refinements/RefinementPrompt.svelte';
	import DecisionHistory from '$lib/refinements/DecisionHistory.svelte';
	import { buildRefinementRequestFromPrompt, refinementDraftFromSession, type RefinementPromptDraft, type RefinementPromptKind } from '$lib/refinements/contextual-refinement-prompt.js';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import GuidedQuestion from '$lib/guided/GuidedQuestion.svelte';
	import PromptSurface from '$lib/guided/PromptSurface.svelte';
	import RegionSetup from '$lib/guided/RegionSetup.svelte';
	import {
		defaultRegionCode,
		readLocalRegionPreference,
		writeProvidedRegionPreference,
		writeRefusedRegionPreference,
		type LocalRegionPreference,
	} from '$lib/guided/local-region.js';
	import {
		EMPTY_GUIDED_DRAFT,
		answerSurfaceView,
		buildGuidedAnswerSubmission,
		canContinueGuidedQuestion,
		createDraftFromCachedAnswer,
		regionSetupSubmissionFromOption,
		regionSetupSubmissionFromPreference,
		type GuidedDraft,
	} from '$lib/guided/guided-state.js';
	import { STARTER_QUESTIONS } from '$lib/guided/starter-questions.js';
	import ProcessingState from '$lib/run-progress/ProcessingState.svelte';
	import {
		applyShopperProgressEvent,
		createInitialShopperProgress,
		isTerminalRunEvent,
		shopperProgressHeadline,
		type ShopperProgressItem,
	} from '$lib/run-progress/run-progress.js';
	import RecommendationResult from '$lib/results/RecommendationResult.svelte';
	import { buildResultView, selectModeView, type ResultView } from '$lib/results/result-view.js';
	import { REGION_OPTIONS, regionByCode } from '$lib/session/session-form.js';
	import { listingCheckOutcome as resolveListingCheckOutcome, normalizeListingLink, type ListingCheckOutcome } from '$lib/user-products/listing-check.js';
	import { manualCandidateViews, type ManualCandidateView } from '$lib/user-products/manual-fallback.js';

	type HomeState = 'question' | 'region_setup' | 'guiding' | 'blocked' | 'processing' | 'result' | 'refining';
	type RequestedRun = Readonly<{
		kind: 'analysis' | 'refinement';
		sessionId: SessionId;
		runId: RunId;
		generation: number;
	}>;

	const api = createApiClient();

	let question = $state('');
	let pendingQuestion = $state('');
	let homeState = $state<HomeState>('question');
	let regionReturnState = $state<HomeState>('question');
	let regionPreference = $state<LocalRegionPreference | null>(null);
	let selectedRegionCode = $state(defaultRegionCode());
	let guidedState = $state<GuidedIntakeState | null>(null);
	let sessionId = $state<SessionId | null>(null);
	let answerDraft = $state<GuidedDraft>({ ...EMPTY_GUIDED_DRAFT });
	let answerCache = $state<Record<string, GuidedAnswer>>({});
	let guideError = $state<string | null>(null);
	let isGuidedRequestPending = $state(false);
	let shopperProgress = $state<ShopperProgressItem[]>(createInitialShopperProgress());
	let resultView = $state<ResultView | null>(null);
	let currentSession = $state<SessionStateResponse | null>(null);
	let decisionHistory = $state<DecisionHistoryResponse | null>(null);
	let displayedVersionId = $state<string | null>(null);
	let latestVersionId = $state<string | null>(null);
	let refinementDraft = $state<RefinementPromptDraft | null>(null);
	let refinementError = $state<string | null>(null);
	let refinementPending = $state(false);
	let historyPending = $state(false);
	let historyError = $state<string | null>(null);
	let flowGeneration = 0;
	let activeAnalysisRun: RequestedRun | null = null;
	let historyLoadSequence = 0;
	let selectedModeKey = $state<string | null>(null);
	let activeListingCandidateId = $state<string | null>(null);
	let listingCheckOutcome = $state<ListingCheckOutcome | null>(null);
	let listingCheckError = $state<string | null>(null);
	let manualCandidates = $state<ManualCandidateView[]>([]);
	let manualError = $state<string | null>(null);
	let activeManualCandidateId = $state<string | null>(null);
	let starterIndex = $state(0);
	let clientReady = $state(false);
	let starterTimer: ReturnType<typeof setInterval> | null = null;
	let runEventSubscription: { close: () => void } | null = null;

	const activeStarter = $derived(STARTER_QUESTIONS[starterIndex]);
	const submittedQuestion = $derived(pendingQuestion || question.trim());
	const currentGuidedQuestion = $derived(guidedState?.current_question ?? null);
	const currentAnswerSurface = $derived(
		currentGuidedQuestion ? answerSurfaceView(currentGuidedQuestion) : 'textbox',
	);
	const canContinueGuide = $derived(
		currentGuidedQuestion ? canContinueGuidedQuestion(currentGuidedQuestion, answerDraft) : false,
	);
	const isAtFirstGuidedQuestion = $derived(!guidedState?.navigation.can_go_back);
	const progressHeadline = $derived(shopperProgressHeadline(shopperProgress));
	const selectedModeView = $derived(
		resultView ? selectModeView(resultView, selectedModeKey) : null,
	);
	const regionLabel = $derived(
		regionPreference?.status === 'provided'
			? regionPreference.region.label
			: regionPreference?.status === 'refused'
				? 'Region not set'
				: 'Set buying region',
	);
	const viewingPrevious = $derived(Boolean(displayedVersionId && latestVersionId !== displayedVersionId));
	const decisionBusy = $derived(isGuidedRequestPending || refinementPending || historyPending);

	onMount(() => {
		clientReady = true;
		regionPreference = readLocalRegionPreference(window.localStorage);
		if (regionPreference?.status === 'provided') {
			selectedRegionCode = regionPreference.region.code;
		}
		starterTimer = setInterval(() => {
			starterIndex = (starterIndex + 1) % STARTER_QUESTIONS.length;
		}, 3200);
	});

	onDestroy(() => {
		if (starterTimer) clearInterval(starterTimer);
		closeRunEventSubscription();
	});

	function chooseStarter(starter: string) {
		question = starter;
	}

	function handleSubmit(currentQuestion = question) {
		const trimmed = currentQuestion.trim();
		if (!trimmed || isGuidedRequestPending) return;
		question = currentQuestion;
		pendingQuestion = trimmed;
		void startGuidedFlow(regionPreference);
	}

	function openRegionSetup() {
		if (regionPreference?.status === 'provided') {
			selectedRegionCode = regionPreference.region.code;
		}
		regionReturnState = homeState === 'region_setup' ? 'question' : homeState;
		guideError = null;
		homeState = 'region_setup';
	}

	function leaveRegionSetup() {
		homeState = regionReturnState;
	}

	async function saveRegionAndResume() {
		if (isGuidedRequestPending) return;
		const preference = writeProvidedRegionPreference(window.localStorage, selectedRegionCode);
		regionPreference = preference;
		if (sessionId && guidedState?.region_setup.status === 'needs_answer') {
			await submitRegionPreference(regionSetupSubmissionFromOption(regionByCode(selectedRegionCode)));
			return;
		}
		if (!sessionId && pendingQuestion) {
			await startGuidedFlow(preference);
			return;
		}
		homeState = regionReturnState;
	}

	async function refuseRegionAndResume() {
		if (isGuidedRequestPending) return;
		const preference = writeRefusedRegionPreference(window.localStorage);
		regionPreference = preference;
		if (sessionId && guidedState?.region_setup.status === 'needs_answer') {
			await submitRegionPreference(regionSetupSubmissionFromPreference(preference));
			return;
		}
		if (!sessionId && pendingQuestion) {
			await startGuidedFlow(preference);
			return;
		}
		homeState = regionReturnState;
	}

	async function submitRegionPreference(
		regionSetup: ReturnType<typeof regionSetupSubmissionFromPreference>,
	) {
		if (!sessionId || !regionSetup) return;
		isGuidedRequestPending = true;
		guideError = null;
		try {
			applyGuideState(await api.submitGuidedRegionSetup(sessionId, regionSetup));
		} catch (error) {
			guideError = userFacingErrorMessage(error);
		} finally {
			isGuidedRequestPending = false;
		}
	}

	function resetFlow({ preserveQuestion = false }: { preserveQuestion?: boolean } = {}) {
		flowGeneration += 1;
		activeAnalysisRun = null;
		currentSession = null;
		decisionHistory = null;
		displayedVersionId = null;
		latestVersionId = null;
		refinementDraft = null;
		refinementError = null;
		refinementPending = false;
		historyPending = false;
		historyError = null;
		question = preserveQuestion ? submittedQuestion : '';
		pendingQuestion = preserveQuestion ? submittedQuestion : '';
		guidedState = null;
		sessionId = null;
		answerCache = {};
		answerDraft = { ...EMPTY_GUIDED_DRAFT };
		guideError = null;
		resultView = null;
		selectedModeKey = null;
		activeListingCandidateId = null;
		listingCheckOutcome = null;
		listingCheckError = null;
		manualCandidates = [];
		manualError = null;
		activeManualCandidateId = null;
		shopperProgress = createInitialShopperProgress();
		closeRunEventSubscription();
		homeState = 'question';
	}

	async function startGuidedFlow(preference: LocalRegionPreference | null = regionPreference) {
		if (!pendingQuestion || isGuidedRequestPending) return;
		isGuidedRequestPending = true;
		guideError = null;
		try {
			const response = await api.createGuidedSession({
				query: pendingQuestion,
				region_setup: regionSetupSubmissionFromPreference(preference),
			});
			sessionId = response.session_id;
			answerCache = {};
			applyGuideState(response.guide);
		} catch (error) {
			guideError = userFacingErrorMessage(error);
		} finally {
			isGuidedRequestPending = false;
		}
	}

	function applyGuideState(nextGuide: GuidedIntakeState) {
		guidedState = nextGuide;
		if (nextGuide.status === 'blocked') {
			answerDraft = { ...EMPTY_GUIDED_DRAFT };
			homeState = 'blocked';
			return;
		}
		if (nextGuide.region_setup.status === 'needs_answer' && !regionPreference) {
			answerDraft = { ...EMPTY_GUIDED_DRAFT };
			regionReturnState = 'question';
			homeState = 'region_setup';
			return;
		}
		if (nextGuide.status === 'ready_for_analysis' || nextGuide.status === 'analysis_started') {
			answerDraft = { ...EMPTY_GUIDED_DRAFT };
			homeState = 'processing';
			queueMicrotask(() => void startAnalysis());
			return;
		}
		homeState = 'guiding';
		loadDraftForCurrentQuestion(nextGuide);
	}

	async function continueGuidedFlow() {
		if (!sessionId || !currentGuidedQuestion || !canContinueGuide || isGuidedRequestPending) return;
		const submission = buildGuidedAnswerSubmission(currentGuidedQuestion, answerDraft);
		answerCache = { ...answerCache, [currentGuidedQuestion.question_id]: submission.answer };
		isGuidedRequestPending = true;
		guideError = null;
		try {
			applyGuideState(await api.submitGuidedAnswer(sessionId, submission));
		} catch (error) {
			guideError = userFacingErrorMessage(error);
		} finally {
			isGuidedRequestPending = false;
		}
	}

	async function skipQuestion() {
		if (!sessionId || !currentGuidedQuestion || isGuidedRequestPending) return;
		isGuidedRequestPending = true;
		guideError = null;
		try {
			applyGuideState(await api.skipGuidedQuestion(sessionId));
		} catch (error) {
			guideError = userFacingErrorMessage(error);
		} finally {
			isGuidedRequestPending = false;
		}
	}

	async function skipAll() {
		if (!sessionId || !guidedState || isGuidedRequestPending) return;
		isGuidedRequestPending = true;
		guideError = null;
		try {
			applyGuideState(await api.skipAllGuidedQuestions(sessionId));
		} catch (error) {
			guideError = userFacingErrorMessage(error);
		} finally {
			isGuidedRequestPending = false;
		}
	}

	async function goBack() {
		if (!guidedState || isAtFirstGuidedQuestion) {
			resetFlow({ preserveQuestion: true });
			return;
		}
		const priorQuestion = guidedState.navigation.reanswerable_questions.at(-1);
		if (!sessionId || !priorQuestion || isGuidedRequestPending) return;
		isGuidedRequestPending = true;
		guideError = null;
		try {
			applyGuideState(
				await api.reanswerGuidedQuestion(sessionId, { question_id: priorQuestion.question_id }),
			);
		} catch (error) {
			guideError = userFacingErrorMessage(error);
		} finally {
			isGuidedRequestPending = false;
		}
	}

	function loadDraftForCurrentQuestion(nextGuide: GuidedIntakeState | null = guidedState) {
		answerDraft = nextGuide?.current_question
			? createDraftFromCachedAnswer(answerCache[nextGuide.current_question.question_id])
			: { ...EMPTY_GUIDED_DRAFT };
	}

	async function startAnalysis() {
		if (!sessionId || guidedState?.status !== 'ready_for_analysis' || isGuidedRequestPending) return;
		const activeSessionId = sessionId;
		const generation = flowGeneration;
		isGuidedRequestPending = true;
		guideError = null;
		resultView = null;
		selectedModeKey = null;
		activeListingCandidateId = null;
		activeManualCandidateId = null;
		activeAnalysisRun = null;
		shopperProgress = createInitialShopperProgress();
		closeRunEventSubscription();
		try {
			homeState = 'processing';
			const run = await api.createRun(activeSessionId);
			if (generation !== flowGeneration || sessionId !== activeSessionId) return;
			subscribeToAnalysisProgress({ kind: 'analysis', sessionId: activeSessionId, runId: run.run_id, generation }, run);
		} catch (error) {
			if (generation === flowGeneration && sessionId === activeSessionId) showAnalysisFailure('initial', userFacingErrorMessage(error));
		} finally {
			if (generation === flowGeneration && sessionId === activeSessionId) isGuidedRequestPending = false;
		}
	}

	async function checkListing(url: string) {
		if (!sessionId || decisionBusy || viewingPrevious) return;
		const activeSessionId = sessionId;
		const generation = flowGeneration;
		isGuidedRequestPending = true;
		listingCheckError = null;
		activeListingCandidateId = null;
		activeManualCandidateId = null;
		activeAnalysisRun = null;
		manualError = null;
		closeRunEventSubscription();
		try {
			const updated = await api.addUserProduct(activeSessionId, { url });
			if (generation !== flowGeneration || sessionId !== activeSessionId) return;
			const candidate = updated.user_added_products.find(
				(item) => normalizeListingLink(item.url ?? '') === url,
			);
			if (!candidate) throw new Error('The listing was not saved.');
			activeListingCandidateId = candidate.candidate_id;
			listingCheckOutcome = null;
			shopperProgress = createInitialShopperProgress();
			homeState = 'processing';
			const run = await api.createRun(activeSessionId);
			if (generation !== flowGeneration || sessionId !== activeSessionId) return;
			subscribeToAnalysisProgress({ kind: 'analysis', sessionId: activeSessionId, runId: run.run_id, generation }, run);
		} catch (error) {
			if (generation === flowGeneration && sessionId === activeSessionId) showAnalysisFailure('listing', userFacingErrorMessage(error));
		} finally {
			if (generation === flowGeneration && sessionId === activeSessionId) isGuidedRequestPending = false;
		}
	}

	async function saveManualProduct(request: CreateUserAddedProductRequest) {
		if (!sessionId || !request.fallback_candidate_id || decisionBusy || viewingPrevious) return;
		const activeSessionId = sessionId;
		const generation = flowGeneration;
		isGuidedRequestPending = true;
		manualError = null;
		activeManualCandidateId = null;
		activeAnalysisRun = null;
		closeRunEventSubscription();
		try {
			await api.addUserProduct(activeSessionId, request);
			if (generation !== flowGeneration || sessionId !== activeSessionId) return;
			activeManualCandidateId = request.fallback_candidate_id;
			activeListingCandidateId = null;
			listingCheckOutcome = null;
			listingCheckError = null;
			shopperProgress = createInitialShopperProgress();
			homeState = 'processing';
			const run = await api.createRun(activeSessionId);
			if (generation !== flowGeneration || sessionId !== activeSessionId) return;
			subscribeToAnalysisProgress({ kind: 'analysis', sessionId: activeSessionId, runId: run.run_id, generation }, run);
		} catch (error) {
			if (generation === flowGeneration && sessionId === activeSessionId) showAnalysisFailure('manual', userFacingErrorMessage(error));
		} finally {
			if (generation === flowGeneration && sessionId === activeSessionId) isGuidedRequestPending = false;
		}
	}

	function selectChoice(choiceId: string) {
		answerDraft = { ...answerDraft, choiceId, isCustomAnswer: false, text: '' };
	}

	function selectCustomAnswer() {
		answerDraft = { ...answerDraft, choiceId: null, isCustomAnswer: true };
	}

	function isCurrentRun(request: RequestedRun): boolean {
		return request.generation === flowGeneration && request.sessionId === sessionId
			&& (request.kind === 'refinement' || request === activeAnalysisRun);
	}

	function showAnalysisFailure(
		kind: 'initial' | 'listing' | 'manual' = activeListingCandidateId ? 'listing' : activeManualCandidateId ? 'manual' : 'initial',
		safeMessage?: string,
	) {
		if (kind === 'listing' && resultView) {
			homeState = 'result';
			listingCheckError = safeMessage
				? `Your previous decision is still shown. ${safeMessage}`
				: 'CartCart could not check that listing. Your previous decision is still shown. Try another link.';
		} else if (kind === 'manual' && resultView) {
			homeState = 'result';
			manualError = safeMessage
				? `Your previous decision is still shown. ${safeMessage}`
				: 'CartCart could not finish checking your details. Your previous decision is still shown. Try again.';
		} else {
			homeState = 'processing';
			guideError = safeMessage ?? 'CartCart could not finish checking options. Try again.';
		}
		activeListingCandidateId = null;
		activeManualCandidateId = null;
		activeAnalysisRun = null;
	}

	function subscribeToAnalysisProgress(request: RequestedRun, run: ShoppingRunRecord) {
		closeRunEventSubscription();
		activeAnalysisRun = request;
		if (run.session_id !== request.sessionId || run.status === 'failed' || run.status === 'cancelled') {
			showAnalysisFailure();
			return;
		}
		let completionStarted = false;
		const recover = async () => {
			if (!isCurrentRun(request) || completionStarted) return;
			completionStarted = true;
			closeRunEventSubscription();
			try {
				if (run.status !== 'succeeded') {
					const savedRun = await api.getRun(request.sessionId, request.runId);
					if (!isCurrentRun(request)) return;
					if (savedRun.session_id !== request.sessionId || savedRun.run_id !== request.runId || savedRun.status !== 'succeeded') {
						showAnalysisFailure();
						return;
					}
				}
				await revealResults(request);
			} catch (error) {
				if (isCurrentRun(request)) showAnalysisFailure(undefined, userFacingErrorMessage(error));
			}
		};
		try {
			runEventSubscription = subscribeToRunEvents(
				{ sessionId: request.sessionId, runId: request.runId },
				{
					onEvent: (event) => {
						if (!isCurrentRun(request) || completionStarted || event.run_id !== request.runId) return;
						shopperProgress = applyShopperProgressEvent(shopperProgress, event);
						if (!isTerminalRunEvent(event)) return;
						completionStarted = true;
						closeRunEventSubscription();
						if (event.status === 'failed' || event.status === 'cancelled') {
							showAnalysisFailure();
							return;
						}
						void revealResults(request);
					},
					onError: () => { void recover(); },
				},
			);
		} catch {
			void recover();
		}
	}

	async function revealResults(request: RequestedRun): Promise<boolean> {
		if (!isCurrentRun(request)) return false;
		try {
			const [results, loadedSession] = await Promise.all([
				api.getResults(request.sessionId),
				api.getSession(request.sessionId),
			]);
			if (!isCurrentRun(request)) return false;
			if (results.result_version.run_id !== request.runId) throw new Error('The new result is not available yet.');
			const nextResultView = buildResultView(results);
			currentSession = loadedSession;
			displayedVersionId = results.result_version.result_version_id;
			latestVersionId = displayedVersionId;
			manualCandidates = manualCandidateViews(loadedSession.user_added_products, results);
			const listingCandidateId = activeListingCandidateId;
			const manualCandidateId = activeManualCandidateId;
			listingCheckError = null;
			manualError = null;
			if (listingCandidateId) {
				const candidate = loadedSession.user_added_products.find(
					(item) => item.candidate_id === listingCandidateId,
				);
				listingCheckOutcome = candidate ? resolveListingCheckOutcome(candidate, results) : null;
				listingCheckError = listingCheckOutcome ? null : 'CartCart could not confirm that listing. Try another link.';
			}
			resultView = nextResultView;
			selectedModeKey = nextResultView.finalMode?.key ?? nextResultView.decisionModes[0]?.key ?? null;
			guideError = null;
			homeState = 'result';
			void loadDecisionHistory();
			if (listingCandidateId || manualCandidateId) {
				await tick();
				if (!isCurrentRun(request)) return false;
				document.getElementById(listingCandidateId ? 'listing-correction' : 'manual-product-fallback')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
			}
			activeListingCandidateId = null;
			activeManualCandidateId = null;
			if (request.kind === 'analysis') activeAnalysisRun = null;
			return true;
		} catch (error) {
			if (!isCurrentRun(request)) return false;
			if (request.kind === 'analysis') showAnalysisFailure(undefined, userFacingErrorMessage(error));
			return false;
		}
	}

	async function loadDecisionHistory() {
		if (!sessionId) return;
		const generation = flowGeneration;
		const sequence = ++historyLoadSequence;
		try {
			const history = await api.getDecisionHistory(sessionId);
			if (generation === flowGeneration && sequence === historyLoadSequence) { decisionHistory = history; historyError = null; }
		} catch {
			if (generation === flowGeneration && sequence === historyLoadSequence) historyError = 'CartCart could not load earlier decisions. Try again.';
		}
	}

	function openRefinement() {
		if (decisionBusy || viewingPrevious) return;
		refinementDraft = null;
		refinementError = null;
		homeState = 'refining';
	}

	async function submitRefinement() {
		if (!sessionId || !refinementDraft || decisionBusy) return;
		let request;
		try { request = buildRefinementRequestFromPrompt(refinementDraft); }
		catch (error) { refinementError = error instanceof Error ? error.message : 'Check your answer.'; return; }
		const generation = flowGeneration;
		const activeSessionId = sessionId;
		refinementPending = true;
		refinementError = null;
		homeState = 'result';
		let requestedRun: RequestedRun | null = null;
		let executedRun: ShoppingRunRecord | null = null;
		try {
			const planned = await api.createRefinement(activeSessionId, request);
			if (generation !== flowGeneration || sessionId !== activeSessionId) return;
			if (planned.run.session_id !== activeSessionId) throw new Error('The update belongs to another search.');
			if (planned.run.status === 'failed' || planned.run.status === 'cancelled') throw new Error('The update did not finish.');
			requestedRun = { kind: 'refinement', sessionId: activeSessionId, runId: planned.run.run_id, generation };
			executedRun = await api.executeRefinement(activeSessionId, planned.refinement.refinement_id);
			if (!isCurrentRun(requestedRun)) return;
			if (executedRun.session_id !== activeSessionId || executedRun.run_id !== requestedRun.runId || executedRun.status !== 'succeeded') throw new Error('The update did not finish.');
			if (!await revealResults(requestedRun)) throw new Error('The saved update could not be opened.');
			await loadDecisionHistory();
		} catch {
			if (generation !== flowGeneration || sessionId !== activeSessionId) return;
			let recovered = false;
			if (requestedRun && (!executedRun || (executedRun.status === 'succeeded' && executedRun.session_id === requestedRun.sessionId && executedRun.run_id === requestedRun.runId))) {
				try {
					const run = await api.getRun(requestedRun.sessionId, requestedRun.runId);
					if (isCurrentRun(requestedRun) && run.session_id === requestedRun.sessionId && run.run_id === requestedRun.runId && run.status === 'succeeded') {
						recovered = await revealResults(requestedRun);
					}
				} catch { /* Keep the displayed saved decision available. */ }
			}
			if (!recovered && generation === flowGeneration && sessionId === activeSessionId) refinementError = 'CartCart could not finish the update. Your previous decision is still available.';
		} finally {
			if (generation === flowGeneration && sessionId === activeSessionId) {
				if (!refinementError && request.region) {
					selectedRegionCode = request.region.region.country_code;
					regionPreference = writeProvidedRegionPreference(window.localStorage, selectedRegionCode);
				}
				refinementPending = false;
			}
		}
	}

	async function showDecisionVersion(id: string) {
		if (!sessionId || decisionBusy) return;
		const generation = flowGeneration;
		historyPending = true;
		historyError = null;
		try {
			const results = await api.getResultVersion(sessionId, id);
			if (generation !== flowGeneration) return;
			resultView = buildResultView(results);
			selectedModeKey = resultView.finalMode?.key ?? null;
			displayedVersionId = id;
			manualCandidates = manualCandidateViews(results.considered_products.map((item) => item.candidate), results);
			listingCheckOutcome = null;
			listingCheckError = null;
			manualError = null;
		} catch {
			if (generation === flowGeneration) historyError = 'CartCart could not open that decision. Try again.';
		} finally {
			if (generation === flowGeneration) historyPending = false;
		}
	}

	function closeRunEventSubscription() {
		runEventSubscription?.close();
		runEventSubscription = null;
	}
</script>

<svelte:head>
	<title>CartCart — Shop with clarity</title>
	<meta name="description" content="Compare the options that fit, understand the tradeoffs, and avoid risky listings." />
</svelte:head>

<main class="min-h-svh bg-background text-foreground" data-client-ready={clientReady}>
	<AppHeader regionLabel={regionLabel} onRegionClick={openRegionSetup} onHome={() => resetFlow()} />

	<section class={`mx-auto flex w-full max-w-[1440px] px-4 sm:px-8 lg:px-10 ${homeState === 'result' ? 'py-10 sm:py-14' : 'min-h-[calc(100svh-4rem)] items-center py-10 sm:py-16'}`}>
		{#if homeState === 'question'}
			<PromptSurface bind:question starter={activeStarter} pending={isGuidedRequestPending} error={guideError} onSubmit={handleSubmit} onChooseStarter={chooseStarter} />
		{:else if homeState === 'region_setup'}
			<RegionSetup bind:selectedCode={selectedRegionCode} regions={REGION_OPTIONS} pending={isGuidedRequestPending} error={guideError} allowBack={Boolean(regionPreference) || !sessionId} onSave={saveRegionAndResume} onRefuse={refuseRegionAndResume} onBack={leaveRegionSetup} />
		{:else if homeState === 'guiding' && currentGuidedQuestion && guidedState}
			<GuidedQuestion question={currentGuidedQuestion} guide={guidedState} bind:draft={answerDraft} surface={currentAnswerSurface} canContinue={canContinueGuide} pending={isGuidedRequestPending} error={guideError} onContinue={continueGuidedFlow} onBack={goBack} onSkip={skipQuestion} onSkipAll={skipAll} onSelectChoice={selectChoice} onSelectCustom={selectCustomAnswer} />
		{:else if homeState === 'blocked'}
			<div class="surface-enter mx-auto w-full max-w-[820px] text-center">
				<p class="text-xs font-medium tracking-[0.14em] text-muted-foreground uppercase">Shopping decisions only</p>
				<h1 class="mt-5 text-balance text-[clamp(2.7rem,5.5vw,5rem)] leading-[1.02] font-light tracking-[-0.04em] text-foreground">CartCart can help with what to buy.</h1>
				<p class="mx-auto mt-5 max-w-[620px] text-pretty text-base leading-7 text-muted-foreground">{guidedState?.guardrail?.message ?? 'Try asking what to buy, what to avoid, or which option is safer.'}</p>
				<div class="mt-8 flex justify-center"><button type="button" class="rounded-md border border-border bg-card px-4 py-2 text-sm text-foreground hover:border-iron focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none" onclick={() => resetFlow({ preserveQuestion: true })}>Back</button></div>
			</div>
		{:else if homeState === 'processing'}
			<ProcessingState question={submittedQuestion} headline={progressHeadline} progress={shopperProgress} error={guideError} pending={isGuidedRequestPending} onRetry={startAnalysis} />
		{:else if homeState === 'refining'}
			<RefinementPrompt bind:draft={refinementDraft} error={refinementError} onChoose={(kind: RefinementPromptKind) => { refinementDraft = refinementDraftFromSession(kind, currentSession); refinementError = null; }} onSubmit={submitRefinement} onBack={() => { if (refinementDraft) { refinementDraft = null; refinementError = null; } else homeState = 'result'; }} />
		{:else if homeState === 'result' && resultView}
			<div class="w-full">
				<div class="mx-auto mb-6 max-w-[1180px]">
					{#if refinementPending}<p role="status" class="mb-4 text-sm text-muted-foreground">Updating your decision. You can review the previous result below.</p>{/if}
					{#if refinementError}<p role="alert" class="mb-4 text-sm text-destructive">{refinementError}</p>{/if}
					{#if viewingPrevious}<p class="mb-3 text-sm text-muted-foreground">Viewing an earlier decision.</p><Button variant="outline" disabled={decisionBusy} onclick={() => latestVersionId && showDecisionVersion(latestVersionId)}>Return to latest decision</Button>
					{:else}<Button variant="outline" disabled={decisionBusy} onclick={openRefinement}>{refinementError ? 'Try refining again' : 'Refine this decision'}</Button>{/if}
					<DecisionHistory history={decisionHistory} selectedId={displayedVersionId} pending={decisionBusy} error={historyError} onSelect={showDecisionVersion} onReload={loadDecisionHistory} />
				</div>
				{#key displayedVersionId}
					<RecommendationResult result={resultView} selectedMode={selectedModeView} question={submittedQuestion} onSelectMode={(modeKey) => (selectedModeKey = modeKey)} onStartOver={() => resetFlow()} {listingCheckOutcome} {listingCheckError} listingCheckPending={decisionBusy} onCheckListing={checkListing} {manualCandidates} {manualError} onSaveManual={saveManualProduct} allowCorrections={!viewingPrevious} />
				{/key}
			</div>
		{/if}
	</section>
</main>
