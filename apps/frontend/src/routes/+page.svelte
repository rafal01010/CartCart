<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { createApiClient, subscribeToRunEvents } from '$lib/api/index.js';
	import { userFacingErrorMessage } from '$lib/api/user-facing-error.js';
	import type { GuidedAnswer, GuidedIntakeState, RunId, SessionId, SessionResultsResponse, SessionStateResponse, ShoppingRunRecord } from '$lib/api/types.js';
	import { Button } from '$lib/components/ui/button/index.js';
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
	import { buildResultView, type ResultView } from '$lib/results/result-view.js';
	import { REGION_OPTIONS, regionByCode } from '$lib/session/session-form.js';

	type HomeState = 'question' | 'region_setup' | 'guiding' | 'blocked' | 'processing' | 'result';
	type RequestedRun = Readonly<{
		sessionId: SessionId;
		runId: RunId;
		generation: number;
	}>;

	type GuidedRequestOwner =
		| Readonly<{ kind: 'creating'; generation: number }>
		| Readonly<{ kind: 'session'; generation: number; sessionId: SessionId }>;

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
	let displayedVersionId = $state<string | null>(null);
	let flowGeneration = 0;
	let activeAnalysisRun: RequestedRun | null = null;
	let retryableAnalysisRun = $state<RequestedRun | null>(null);
	let recommendationRetryRunId = $state<RunId | null>(null);
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
	const regionLabel = $derived(
		currentSession?.current_brief.region
			? regionByCode(currentSession.current_brief.region.region.country_code).label
			: regionPreference?.status === 'provided'
			? regionPreference.region.label
			: regionPreference?.status === 'refused'
				? 'Region not set'
				: 'Set buying region',
	);

	onMount(() => {
		clientReady = true;
		regionPreference = readLocalRegionPreference(window.localStorage);
		if (regionPreference?.status === 'provided') {
			selectedRegionCode = regionPreference.region.code;
		}
		starterTimer = setInterval(() => {
			starterIndex = (starterIndex + 1) % STARTER_QUESTIONS.length;
		}, 3200);
		void resumeSavedDecision();
	});

	onDestroy(() => {
		flowGeneration += 1;
		if (starterTimer) clearInterval(starterTimer);
		closeRunEventSubscription();
	});

	function updateSavedDecisionLocation(request: Pick<RequestedRun, 'sessionId' | 'runId'> | null) {
		if (!clientReady) return;
		const url = new URL(window.location.href);
		if (request) {
			url.searchParams.set('session', request.sessionId);
			url.searchParams.set('run', request.runId);
		} else {
			url.searchParams.delete('session');
			url.searchParams.delete('run');
		}
		replaceState(url, {});
	}

	async function resumeSavedDecision() {
		const params = new URLSearchParams(window.location.search);
		const savedSessionId = params.get('session');
		const savedRunId = params.get('run');
		if (!savedSessionId && !savedRunId) return;
		if (!savedSessionId || !savedRunId) {
			guideError = 'This saved decision link is incomplete.';
			return;
		}
		const request: RequestedRun = {
			sessionId: savedSessionId, runId: savedRunId, generation: flowGeneration,
		};
		sessionId = savedSessionId;
		activeAnalysisRun = request;
		isGuidedRequestPending = true;
		homeState = 'processing';
		try {
			const [loadedSession, run] = await Promise.all([
				api.getSession(request.sessionId), api.getRun(request.sessionId, request.runId),
			]);
			if (!isCurrentRun(request)) return;
			if (loadedSession.session_id !== request.sessionId || run.session_id !== request.sessionId || run.run_id !== request.runId) {
				throw new Error('This saved decision does not match the requested comparison.');
			}
			currentSession = loadedSession;
			question = loadedSession.current_brief.original_query;
			pendingQuestion = question;
			subscribeToAnalysisProgress(request, run);
		} catch (error) {
			if (isCurrentRun(request)) showAnalysisFailure(userFacingErrorMessage(error));
		} finally {
			if (request.generation === flowGeneration && request.sessionId === sessionId) isGuidedRequestPending = false;
		}
	}

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

	function isCurrentGuidedRequest(owner: GuidedRequestOwner): boolean {
		return owner.generation === flowGeneration
			&& (owner.kind === 'creating' || owner.sessionId === sessionId);
	}

	async function runGuidedRequest<T>({ owner, send, accept }: {
		owner: GuidedRequestOwner;
		send: () => Promise<T>;
		accept: (response: T) => void;
	}) {
		isGuidedRequestPending = true;
		guideError = null;
		try {
			const response = await send();
			if (isCurrentGuidedRequest(owner)) accept(response);
		} catch (error) {
			if (isCurrentGuidedRequest(owner)) guideError = userFacingErrorMessage(error);
		} finally {
			if (isCurrentGuidedRequest(owner)) isGuidedRequestPending = false;
		}
	}

	async function submitRegionPreference(
		regionSetup: ReturnType<typeof regionSetupSubmissionFromPreference>,
	) {
		if (!sessionId || !regionSetup || isGuidedRequestPending) return;
		const owner = { kind: 'session', generation: flowGeneration, sessionId } satisfies GuidedRequestOwner;
		await runGuidedRequest({
			owner,
			send: () => api.submitGuidedRegionSetup(owner.sessionId, regionSetup),
			accept: (guide) => applyGuideState(guide, owner),
		});
	}

	function resetFlow({ preserveQuestion = false }: { preserveQuestion?: boolean } = {}) {
		flowGeneration += 1;
		isGuidedRequestPending = false;
		updateSavedDecisionLocation(null);
		activeAnalysisRun = null;
		retryableAnalysisRun = null;
		recommendationRetryRunId = null;
		currentSession = null;
		displayedVersionId = null;
		question = preserveQuestion ? submittedQuestion : '';
		pendingQuestion = preserveQuestion ? submittedQuestion : '';
		guidedState = null;
		sessionId = null;
		answerCache = {};
		answerDraft = { ...EMPTY_GUIDED_DRAFT };
		guideError = null;
		resultView = null;
		shopperProgress = createInitialShopperProgress();
		closeRunEventSubscription();
		homeState = 'question';
	}

	async function startGuidedFlow(preference: LocalRegionPreference | null = regionPreference) {
		if (!pendingQuestion || isGuidedRequestPending) return;
		const owner = { kind: 'creating', generation: flowGeneration } satisfies GuidedRequestOwner;
		const request = { query: pendingQuestion, region_setup: regionSetupSubmissionFromPreference(preference) };
		await runGuidedRequest({
			owner,
			send: () => api.createGuidedSession(request),
			accept: (response) => {
				sessionId = response.session_id;
				answerCache = {};
				applyGuideState(response.guide, {
					kind: 'session', generation: owner.generation, sessionId: response.session_id,
				});
			},
		});
	}

	function applyGuideState(nextGuide: GuidedIntakeState, owner: Extract<GuidedRequestOwner, { kind: 'session' }>) {
		if (!isCurrentGuidedRequest(owner)) return;
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
			queueMicrotask(() => {
				if (isCurrentGuidedRequest(owner)) void startAnalysis();
			});
			return;
		}
		homeState = 'guiding';
		loadDraftForCurrentQuestion(nextGuide);
	}

	async function continueGuidedFlow() {
		if (!sessionId || !currentGuidedQuestion || !canContinueGuide || isGuidedRequestPending) return;
		const submission = buildGuidedAnswerSubmission(currentGuidedQuestion, answerDraft);
		answerCache = { ...answerCache, [currentGuidedQuestion.question_id]: submission.answer };
		const owner = { kind: 'session', generation: flowGeneration, sessionId } satisfies GuidedRequestOwner;
		await runGuidedRequest({
			owner,
			send: () => api.submitGuidedAnswer(owner.sessionId, submission),
			accept: (guide) => applyGuideState(guide, owner),
		});
	}

	async function skipQuestion() {
		if (!sessionId || !currentGuidedQuestion || isGuidedRequestPending) return;
		const owner = { kind: 'session', generation: flowGeneration, sessionId } satisfies GuidedRequestOwner;
		await runGuidedRequest({
			owner,
			send: () => api.skipGuidedQuestion(owner.sessionId),
			accept: (guide) => applyGuideState(guide, owner),
		});
	}

	async function skipAll() {
		if (!sessionId || !guidedState || isGuidedRequestPending) return;
		const owner = { kind: 'session', generation: flowGeneration, sessionId } satisfies GuidedRequestOwner;
		await runGuidedRequest({
			owner,
			send: () => api.skipAllGuidedQuestions(owner.sessionId),
			accept: (guide) => applyGuideState(guide, owner),
		});
	}

	async function goBack() {
		if (!guidedState || isAtFirstGuidedQuestion) {
			resetFlow({ preserveQuestion: true });
			return;
		}
		const priorQuestion = guidedState.navigation.reanswerable_questions.at(-1);
		if (!sessionId || !priorQuestion || isGuidedRequestPending) return;
		const owner = { kind: 'session', generation: flowGeneration, sessionId } satisfies GuidedRequestOwner;
		await runGuidedRequest({
			owner,
			send: () => api.reanswerGuidedQuestion(owner.sessionId, { question_id: priorQuestion.question_id }),
			accept: (guide) => applyGuideState(guide, owner),
		});
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
		retryableAnalysisRun = null;
		recommendationRetryRunId = null;
		isGuidedRequestPending = true;
		guideError = null;
		resultView = null;
		activeAnalysisRun = null;
		shopperProgress = createInitialShopperProgress();
		closeRunEventSubscription();
		try {
			homeState = 'processing';
			const run = await api.createRun(activeSessionId);
			if (generation !== flowGeneration || sessionId !== activeSessionId) return;
			subscribeToAnalysisProgress({ sessionId: activeSessionId, runId: run.run_id, generation }, run);
		} catch (error) {
			if (generation === flowGeneration && sessionId === activeSessionId) showAnalysisFailure(userFacingErrorMessage(error));
		} finally {
			if (generation === flowGeneration && sessionId === activeSessionId) isGuidedRequestPending = false;
		}
	}

	async function retryAnalysis() {
		if (!sessionId || isGuidedRequestPending) return;
		const request = retryableAnalysisRun ?? (recommendationRetryRunId ? {
			sessionId, runId: recommendationRetryRunId, generation: flowGeneration,
		} satisfies RequestedRun : null);
		if (!request) {
			await startAnalysis();
			return;
		}
		if (request.sessionId !== sessionId || request.generation !== flowGeneration) return;
		isGuidedRequestPending = true;
		guideError = null;
		shopperProgress = createInitialShopperProgress();
		closeRunEventSubscription();
		activeAnalysisRun = request;
		homeState = 'processing';
		try {
			const run = await api.retryRun(request.sessionId, request.runId);
			if (!isCurrentRun(request)) return;
			if (run.session_id !== request.sessionId || run.run_id !== request.runId) {
				throw new Error('The retry belongs to another comparison.');
			}
			subscribeToAnalysisProgress(request, run);
		} catch (error) {
			if (isCurrentRun(request)) showAnalysisFailure(userFacingErrorMessage(error));
		} finally {
			if (request.generation === flowGeneration && request.sessionId === sessionId) isGuidedRequestPending = false;
		}
	}

	function recommendationRetryId(results: SessionResultsResponse): RunId | null {
		const bundle = results.recommendation_bundle;
		return bundle.verification_action === 'blocked'
			? results.result_version.run_id : null;
	}

	function selectChoice(choiceId: string) {
		answerDraft = { ...answerDraft, choiceId, isCustomAnswer: false, text: '' };
	}

	function selectCustomAnswer() {
		answerDraft = { ...answerDraft, choiceId: null, isCustomAnswer: true };
	}

	function isCurrentRun(request: RequestedRun): boolean {
		return request.generation === flowGeneration && request.sessionId === sessionId
			&& request === activeAnalysisRun;
	}

	function showAnalysisFailure(safeMessage?: string) {
		if (activeAnalysisRun) retryableAnalysisRun = activeAnalysisRun;
		homeState = 'processing';
		guideError = safeMessage ?? 'CartCart could not finish checking options. Try again.';
		activeAnalysisRun = null;
	}

	function subscribeToAnalysisProgress(request: RequestedRun, run: ShoppingRunRecord) {
		closeRunEventSubscription();
		activeAnalysisRun = request;
		if (run.session_id !== request.sessionId || run.status === 'failed' || run.status === 'cancelled') {
			showAnalysisFailure();
			return;
		}
		if (run.status === 'succeeded') {
			void revealResults(request);
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
				if (isCurrentRun(request)) showAnalysisFailure(userFacingErrorMessage(error));
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
			resultView = nextResultView;
			recommendationRetryRunId = recommendationRetryId(results);
			retryableAnalysisRun = null;
			guideError = null;
			homeState = 'result';
			updateSavedDecisionLocation(request);
			activeAnalysisRun = null;
			return true;
		} catch (error) {
			if (!isCurrentRun(request)) return false;
			showAnalysisFailure(userFacingErrorMessage(error));
			return false;
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
			<ProcessingState question={submittedQuestion} headline={progressHeadline} progress={shopperProgress} error={guideError} pending={isGuidedRequestPending} onRetry={retryAnalysis} />
		{:else if homeState === 'result' && resultView}
			<div class="w-full">
				{#key displayedVersionId}
					<RecommendationResult result={resultView} onStartOver={() => resetFlow()} />
				{/key}
				{#if recommendationRetryRunId}
					<div class="mx-auto mt-5 flex max-w-[1180px] flex-wrap items-center gap-3 border border-border bg-card px-5 py-4">
						<p class="text-sm leading-6 text-muted-foreground">This saved run stopped before advice was ready. Try again using the information already gathered.</p>
						<Button variant="outline" disabled={isGuidedRequestPending} onclick={retryAnalysis}>Retry recommendation</Button>
					</div>
				{/if}
			</div>
		{/if}
	</section>
</main>
