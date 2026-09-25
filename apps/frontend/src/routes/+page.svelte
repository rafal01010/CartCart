<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { ApiError, createApiClient, subscribeToRunEvents } from '$lib/api/index.js';
	import type { GuidedAnswer, GuidedIntakeState, RunId, SessionId } from '$lib/api/types.js';
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

	type HomeState = 'question' | 'region_setup' | 'guiding' | 'blocked' | 'processing' | 'result';

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
	let selectedModeKey = $state<string | null>(null);
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
		question = preserveQuestion ? submittedQuestion : '';
		pendingQuestion = preserveQuestion ? submittedQuestion : '';
		guidedState = null;
		sessionId = null;
		answerCache = {};
		answerDraft = { ...EMPTY_GUIDED_DRAFT };
		guideError = null;
		resultView = null;
		selectedModeKey = null;
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
		isGuidedRequestPending = true;
		guideError = null;
		resultView = null;
		selectedModeKey = null;
		shopperProgress = createInitialShopperProgress();
		closeRunEventSubscription();
		try {
			const run = await api.createRun(sessionId);
			homeState = 'processing';
			subscribeToAnalysisProgress(sessionId, run.run_id);
		} catch (error) {
			guideError = userFacingErrorMessage(error);
		} finally {
			isGuidedRequestPending = false;
		}
	}

	function userFacingErrorMessage(error: unknown): string {
		if (error instanceof ApiError && error.code === 'network_error') {
			return 'CartCart could not connect. Check your connection and try again.';
		}
		return 'CartCart could not continue. Try again.';
	}

	function selectChoice(choiceId: string) {
		answerDraft = { ...answerDraft, choiceId, isCustomAnswer: false, text: '' };
	}

	function selectCustomAnswer() {
		answerDraft = { ...answerDraft, choiceId: null, isCustomAnswer: true };
	}

	function subscribeToAnalysisProgress(activeSessionId: SessionId, runId: RunId) {
		closeRunEventSubscription();
		try {
			runEventSubscription = subscribeToRunEvents(
				{ sessionId: activeSessionId, runId },
				{
					onEvent: (event) => {
						shopperProgress = applyShopperProgressEvent(shopperProgress, event);
						if (!isTerminalRunEvent(event)) return;
						closeRunEventSubscription();
						if (event.status === 'failed' || event.status === 'cancelled') {
							guideError = 'CartCart could not finish checking options. Try again.';
							return;
						}
						void revealResults();
					},
					onError: () => {
						closeRunEventSubscription();
						void revealResults();
					},
				},
			);
		} catch {
			void revealResults();
		}
	}

	async function revealResults() {
		if (!sessionId) return;
		try {
			const nextResultView = buildResultView(await api.getResults(sessionId));
			resultView = nextResultView;
			selectedModeKey = nextResultView.finalMode?.key ?? nextResultView.decisionModes[0]?.key ?? null;
			guideError = null;
			homeState = 'result';
		} catch (error) {
			guideError = userFacingErrorMessage(error);
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
		{:else if homeState === 'result' && resultView}
			<RecommendationResult result={resultView} selectedMode={selectedModeView} question={submittedQuestion} onSelectMode={(modeKey) => (selectedModeKey = modeKey)} onStartOver={() => resetFlow()} />
		{/if}
	</section>
</main>
