<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import MapPin from '@lucide/svelte/icons/map-pin';
	import SearchCheck from '@lucide/svelte/icons/search-check';
	import { ApiError, createApiClient, subscribeToRunEvents } from '$lib/api/index.js';
	import type { GuidedAnswer, GuidedIntakeState, RunId, SessionId } from '$lib/api/types.js';
	import { Button } from '$lib/components/ui/button/index.js';
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
	import {
		applyShopperProgressEvent,
		createInitialShopperProgress,
		isTerminalRunEvent,
		shopperProgressHeadline,
		type ShopperProgressItem,
	} from '$lib/run-progress/run-progress.js';
	import { buildResultView, type ResultView } from '$lib/results/result-view.js';
	import { REGION_OPTIONS, regionByCode } from '$lib/session/session-form.js';

	type HomeState =
		| 'question'
		| 'region_setup'
		| 'guiding'
		| 'blocked'
		| 'processing'
		| 'result';

	const api = createApiClient();

	let question = $state('');
	let pendingQuestion = $state('');
	let homeState = $state<HomeState>('question');
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
	let showSupportingDetails = $state(false);
	let showSourceDetails = $state(false);
	let starterIndex = $state(0);
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
	const supportingModeViews = $derived(
		resultView
			? resultView.modeViews.filter((mode) => mode.key !== resultView?.finalMode?.key)
			: [],
	);

	onMount(() => {
		regionPreference = readLocalRegionPreference(window.localStorage);
		if (regionPreference?.status === 'provided') {
			selectedRegionCode = regionPreference.region.code;
		}
		starterTimer = setInterval(() => {
			starterIndex = (starterIndex + 1) % STARTER_QUESTIONS.length;
		}, 2800);
	});

	onDestroy(() => {
		if (starterTimer) {
			clearInterval(starterTimer);
		}
		closeRunEventSubscription();
	});

	function chooseStarter(starter: string) {
		question = starter;
	}

	function handleSubmit() {
		const trimmed = question.trim();
		if (!trimmed || isGuidedRequestPending) return;

		pendingQuestion = trimmed;
		void startGuidedFlow(regionPreference);
	}

	async function saveRegionAndResume() {
		if (isGuidedRequestPending) return;
		const preference = writeProvidedRegionPreference(window.localStorage, selectedRegionCode);
		regionPreference = preference;
		if (!sessionId) {
			await startGuidedFlow(preference);
			return;
		}
		await submitRegionPreference(regionSetupSubmissionFromOption(regionByCode(selectedRegionCode)));
	}

	async function refuseRegionAndResume() {
		if (isGuidedRequestPending) return;
		const preference = writeRefusedRegionPreference(window.localStorage);
		regionPreference = preference;
		if (!sessionId) {
			await startGuidedFlow(preference);
			return;
		}
		await submitRegionPreference(regionSetupSubmissionFromPreference(preference));
	}

	async function submitRegionPreference(regionSetup: ReturnType<typeof regionSetupSubmissionFromPreference>) {
		if (!sessionId || !regionSetup) return;
		isGuidedRequestPending = true;
		guideError = null;
		try {
			const nextGuide = await api.submitGuidedRegionSetup(sessionId, regionSetup);
			applyGuideState(nextGuide);
		} catch (error) {
			guideError = userFacingErrorMessage(error);
		} finally {
			isGuidedRequestPending = false;
		}
	}

	function editQuestion() {
		question = submittedQuestion;
		guidedState = null;
		sessionId = null;
		answerCache = {};
		answerDraft = { ...EMPTY_GUIDED_DRAFT };
		guideError = null;
		resultView = null;
		showSupportingDetails = false;
		showSourceDetails = false;
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
			homeState = 'region_setup';
			return;
		}
		if (nextGuide.status === 'ready_for_analysis' || nextGuide.status === 'analysis_started') {
			answerDraft = { ...EMPTY_GUIDED_DRAFT };
			homeState = 'processing';
			queueMicrotask(() => {
				void startAnalysis();
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
		isGuidedRequestPending = true;
		guideError = null;
		try {
			const nextGuide = await api.submitGuidedAnswer(sessionId, submission);
			applyGuideState(nextGuide);
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
			const nextGuide = await api.skipGuidedQuestion(sessionId);
			applyGuideState(nextGuide);
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
			const nextGuide = await api.skipAllGuidedQuestions(sessionId);
			applyGuideState(nextGuide);
		} catch (error) {
			guideError = userFacingErrorMessage(error);
		} finally {
			isGuidedRequestPending = false;
		}
	}

	async function goBack() {
		if (!guidedState || isAtFirstGuidedQuestion) {
			editQuestion();
			return;
		}
		const priorQuestion = guidedState.navigation.reanswerable_questions.at(-1);
		if (!sessionId || !priorQuestion || isGuidedRequestPending) return;
		isGuidedRequestPending = true;
		guideError = null;
		try {
			const nextGuide = await api.reanswerGuidedQuestion(sessionId, {
				question_id: priorQuestion.question_id,
			});
			applyGuideState(nextGuide);
		} catch (error) {
			guideError = userFacingErrorMessage(error);
		} finally {
			isGuidedRequestPending = false;
		}
	}

	function loadDraftForCurrentQuestion(nextGuide: GuidedIntakeState | null = guidedState) {
		if (!nextGuide?.current_question) {
			answerDraft = { ...EMPTY_GUIDED_DRAFT };
			return;
		}
		answerDraft = createDraftFromCachedAnswer(answerCache[nextGuide.current_question.question_id]);
	}

	async function startAnalysis() {
		if (!sessionId || guidedState?.status !== 'ready_for_analysis' || isGuidedRequestPending) return;
		isGuidedRequestPending = true;
		guideError = null;
		resultView = null;
		showSupportingDetails = false;
		showSourceDetails = false;
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
		answerDraft = {
			...answerDraft,
			choiceId,
			isCustomAnswer: false,
			text: '',
		};
	}

	function selectCustomAnswer() {
		answerDraft = {
			...answerDraft,
			choiceId: null,
			isCustomAnswer: true,
		};
	}

	function subscribeToAnalysisProgress(activeSessionId: SessionId, runId: RunId) {
		closeRunEventSubscription();
		try {
			runEventSubscription = subscribeToRunEvents(
				{ sessionId: activeSessionId, runId },
				{
					onEvent: (event) => {
						shopperProgress = applyShopperProgressEvent(shopperProgress, event);
						if (isTerminalRunEvent(event)) {
							closeRunEventSubscription();
							if (event.status === 'failed' || event.status === 'cancelled') {
								guideError = 'CartCart could not finish checking options. Try again.';
								return;
							}
							void revealResults();
						}
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
			const results = await api.getResults(sessionId);
			resultView = buildResultView(results);
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
	<title>CartCart</title>
	<meta
		name="description"
		content="CartCart helps compare shopping options and avoid risky purchases."
	/>
</svelte:head>

<main class="min-h-svh bg-background text-foreground">
	<header class="border-border/80 bg-card/80 h-14 border-b">
		<div class="mx-auto flex h-full w-full max-w-6xl items-center justify-between px-4 sm:px-6">
			<a href="/" class="flex items-center gap-2 text-sm font-medium text-foreground">
				<span
					class="border-border bg-accent/10 shadow-subtle flex size-6 items-center justify-center rounded-md"
					aria-hidden="true"
				>
					<SearchCheck class="text-accent size-3.5" />
				</span>
				<span>CartCart</span>
			</a>
			<p class="hidden text-sm text-muted-foreground sm:block">Guided shopping decisions</p>
		</div>
	</header>

	<section
		class="mx-auto flex min-h-[calc(100svh-3.5rem)] w-full max-w-6xl items-center px-4 py-10 sm:px-6"
	>
		<div class="mx-auto w-full max-w-5xl">
			{#if homeState === 'question'}
				<div class="text-center">
					<h1
						class="text-prompt mx-auto max-w-5xl text-balance text-4xl font-light tracking-normal text-foreground sm:text-5xl md:text-6xl"
					>
						Send your question
						<br />
						{#key activeStarter}
							<button
								type="button"
								class="starter-question mt-3 inline text-balance rounded-md text-foreground/75 transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:outline-none"
								onclick={() => chooseStarter(activeStarter)}
							>
								{activeStarter}
							</button>
						{/key}
					</h1>
				</div>

				<form
					class="focus-within:ring-ring/70 bg-input shadow-input mx-auto mt-8 grid max-w-3xl grid-cols-[1fr_auto] items-end gap-3 rounded-md p-3 focus-within:ring-1"
					aria-label="Question entry"
					onsubmit={(event) => {
						event.preventDefault();
						handleSubmit();
					}}
				>
					<label for="shopping-question" class="sr-only">Shopping question</label>
					<textarea
						id="shopping-question"
						bind:value={question}
						rows="3"
						class="max-h-48 min-h-24 resize-none bg-transparent px-2 py-1 text-base leading-7 text-foreground outline-none placeholder:text-muted-foreground sm:text-lg"
						placeholder="Ask what you should buy."
					></textarea>
					<Button
						type="submit"
						size="icon"
						aria-label="Send question"
						disabled={!question.trim() || isGuidedRequestPending}
						class="mb-0.5"
					>
						<ArrowUp />
					</Button>
				</form>
				{#if guideError}
					<p class="mt-4 text-center text-sm text-destructive">{guideError}</p>
				{/if}
			{:else if homeState === 'region_setup'}
				<div class="text-center">
					<p class="mb-3 text-sm font-medium text-muted-foreground">Buying region</p>
					<h1
						class="mx-auto max-w-2xl text-balance text-4xl font-light tracking-normal text-foreground sm:text-5xl"
					>
						Where should CartCart look first?
					</h1>
					<p class="mx-auto mt-4 max-w-xl text-pretty text-base leading-7 text-muted-foreground">
						Your region helps show products you can actually buy, with prices, shipping, returns, and seller risk that make sense for you.
					</p>
				</div>

				<div class="bg-card shadow-subtle mx-auto mt-8 max-w-xl rounded-xl p-4 sm:p-5">
					<label for="region-select" class="flex items-center gap-2 text-sm font-medium text-foreground">
						<MapPin class="text-accent size-4" />
						Country or region
					</label>
					<select
						id="region-select"
						bind:value={selectedRegionCode}
						class="bg-input shadow-input mt-3 h-11 w-full rounded-md px-3 text-sm text-foreground outline-none focus:ring-1 focus:ring-ring"
					>
						{#each REGION_OPTIONS as region}
							<option value={region.code}>{region.label}</option>
						{/each}
					</select>
					<div class="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
						<Button type="button" onclick={saveRegionAndResume} disabled={isGuidedRequestPending}>
							<Check />
							Use this region
						</Button>
						<Button
							type="button"
							variant="outline"
							onclick={refuseRegionAndResume}
							disabled={isGuidedRequestPending}
						>
							I prefer not to say
						</Button>
					</div>
					{#if guideError}
						<p class="mt-4 text-sm text-destructive">{guideError}</p>
					{/if}
				</div>
			{:else if homeState === 'guiding' && currentGuidedQuestion}
				<div class="text-center">
					<h1
						class="mx-auto max-w-5xl text-balance text-4xl font-light tracking-normal text-foreground sm:text-5xl"
					>
						{currentGuidedQuestion.text}
					</h1>
				</div>

				<form
					class="mx-auto mt-8 max-w-3xl"
					aria-label="Guided answer"
					onsubmit={(event) => {
						event.preventDefault();
						continueGuidedFlow();
					}}
				>
					{#if currentAnswerSurface === 'textbox'}
						<div
							class="focus-within:ring-ring/70 bg-input shadow-input grid grid-cols-[1fr_auto] items-end gap-3 rounded-md p-3 focus-within:ring-1"
						>
							<label for="guided-answer" class="sr-only">Your answer</label>
							<textarea
								id="guided-answer"
								bind:value={answerDraft.text}
								rows="3"
								class="max-h-48 min-h-24 resize-none bg-transparent px-2 py-1 text-base leading-7 text-foreground outline-none placeholder:text-muted-foreground sm:text-lg"
								placeholder="Type your answer."
							></textarea>
							<Button
								type="submit"
								size="icon"
								aria-label="Continue"
								disabled={!canContinueGuide || isGuidedRequestPending}
								class="mb-0.5"
							>
								<ArrowUp />
							</Button>
						</div>
					{:else}
						<div class="mx-auto grid max-w-2xl gap-3 sm:grid-cols-2">
							{#each currentGuidedQuestion.inline_choice?.options ?? [] as option}
								<button
									type="button"
									class={`rounded-xl p-4 text-left shadow-subtle transition-colors focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:outline-none ${
										answerDraft.choiceId === option.choice_id && !answerDraft.isCustomAnswer
											? 'bg-secondary text-foreground'
											: 'bg-card text-muted-foreground hover:text-foreground'
									}`}
									onclick={() => selectChoice(option.choice_id)}
									disabled={isGuidedRequestPending}
								>
									<span class="block text-sm font-medium text-foreground">{option.label}</span>
									{#if option.description}
										<span class="mt-1 block text-sm leading-6">{option.description}</span>
									{/if}
								</button>
							{/each}
						</div>

						{#if currentAnswerSurface === 'two_option_plus_text'}
							<div class="mt-3 flex justify-center">
								<Button
									type="button"
									variant="outline"
									onclick={selectCustomAnswer}
									disabled={isGuidedRequestPending}
								>
									{currentGuidedQuestion.inline_choice?.custom_answer_label ?? 'Type my answer'}
								</Button>
							</div>
							{#if answerDraft.isCustomAnswer}
								<div
									class="focus-within:ring-ring/70 bg-input shadow-input mx-auto mt-4 max-w-2xl rounded-md p-3 focus-within:ring-1"
								>
									<label for="guided-custom-answer" class="sr-only">Your answer</label>
									<textarea
										id="guided-custom-answer"
										bind:value={answerDraft.text}
										rows="3"
										class="max-h-48 min-h-24 w-full resize-none bg-transparent px-2 py-1 text-base leading-7 text-foreground outline-none placeholder:text-muted-foreground sm:text-lg"
										placeholder="Type your answer."
									></textarea>
								</div>
							{/if}
						{/if}

						<div class="mt-5 flex justify-center">
							<Button type="submit" disabled={!canContinueGuide || isGuidedRequestPending}
								>Continue</Button
							>
						</div>
					{/if}

					{#if guideError}
						<p class="mt-4 text-center text-sm text-destructive">{guideError}</p>
					{/if}

					<div class="mt-5 flex flex-wrap items-center justify-between gap-3">
						<Button type="button" variant="outline" onclick={goBack} disabled={isGuidedRequestPending}>
							<ArrowLeft />
							Back
						</Button>
						<div class="flex flex-wrap items-center justify-end gap-3">
							{#if guidedState?.skippable_question.can_skip}
								<Button
									type="button"
									variant="outline"
									onclick={skipQuestion}
									disabled={isGuidedRequestPending}
									>Skip</Button
								>
							{/if}
							{#if guidedState?.analysis_start.can_skip_all_and_start_analysis}
								<Button
									type="button"
									variant="outline"
									onclick={skipAll}
									disabled={isGuidedRequestPending}
								>
									Skip all
								</Button>
							{/if}
						</div>
					</div>
				</form>
			{:else if homeState === 'blocked'}
				<div class="text-center">
					<p class="mb-3 text-sm font-medium text-muted-foreground">Shopping questions only</p>
					<h1
						class="mx-auto max-w-2xl text-balance text-4xl font-light tracking-normal text-foreground sm:text-5xl"
					>
						CartCart can help with shopping decisions.
					</h1>
					<p class="mx-auto mt-4 max-w-xl text-pretty text-base leading-7 text-muted-foreground">
						{guidedState?.guardrail?.message ??
							'Try asking what to buy, what to avoid, or which option is safer.'}
					</p>
				</div>

				<div class="mt-8 flex justify-center">
					<Button type="button" variant="outline" onclick={editQuestion}>
						<ArrowLeft />
						Back
					</Button>
				</div>
			{:else if homeState === 'processing'}
				<div class="text-center">
					<p class="mb-3 text-sm font-medium text-muted-foreground">Checking options</p>
					<h1
						class="mx-auto max-w-2xl text-balance text-4xl font-light tracking-normal text-foreground sm:text-5xl"
					>
						{progressHeadline}
					</h1>
					<p class="mx-auto mt-4 max-w-xl text-pretty text-base leading-7 text-muted-foreground">
						CartCart is comparing fit, evidence, and seller risk for: {submittedQuestion}
					</p>
				</div>

				<div class="bg-card shadow-subtle mx-auto mt-8 grid max-w-2xl gap-1 rounded-xl p-3 sm:p-4">
					{#each shopperProgress as item}
						<div
							class={`grid grid-cols-[auto_1fr] gap-3 rounded-md px-3 py-3 ${
								item.status === 'running'
									? 'bg-secondary text-foreground'
									: 'text-muted-foreground'
							}`}
						>
							<span
								class={`mt-1 size-2 rounded-full ${
									item.status === 'succeeded'
										? 'bg-emerald-500'
										: item.status === 'running'
											? 'bg-accent'
											: item.status === 'failed'
												? 'bg-destructive'
												: 'bg-muted-foreground/35'
								}`}
								aria-hidden="true"
							></span>
							<span>
								<span class="block text-sm font-medium text-foreground">{item.label}</span>
								<span class="mt-1 block text-sm leading-6">{item.message}</span>
							</span>
						</div>
					{/each}
				</div>

				{#if guideError}
					<p class="mt-4 text-center text-sm text-destructive">{guideError}</p>
				{/if}

				<div class="mt-8 flex flex-wrap items-center justify-center gap-3">
					<Button type="button" variant="outline" onclick={goBack} disabled={isGuidedRequestPending}>
						<ArrowLeft />
						Back
					</Button>
				</div>
			{:else if homeState === 'result' && resultView}
				<div class="text-center">
					<p class="mb-3 text-sm font-medium text-muted-foreground">Recommendation</p>
					<h1
						class="mx-auto max-w-2xl text-balance text-4xl font-light tracking-normal text-foreground sm:text-5xl"
					>
						{resultView.noStrongBuyReason ? 'No strong buy yet.' : 'Here is the best pick.'}
					</h1>
					<p class="mx-auto mt-4 max-w-xl text-pretty text-base leading-7 text-muted-foreground">
						{resultView.noStrongBuyReason ?? resultView.whyItWins ?? resultView.finalMode?.rationale}
					</p>
				</div>

				<div class="bg-card shadow-subtle mx-auto mt-8 max-w-3xl rounded-xl p-4 sm:p-5">
					{#if resultView.finalMode}
						<div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
							<div>
								<p class="text-sm font-medium text-muted-foreground">Best pick</p>
								<h2 class="mt-2 text-2xl font-light tracking-normal text-foreground">
									{resultView.finalMode.label}
								</h2>
								<p class="mt-3 text-sm leading-6 text-muted-foreground">
									{resultView.finalMode.rationale}
								</p>
							</div>
							<div class="rounded-md bg-secondary px-3 py-2 text-sm text-muted-foreground">
								Confidence: {resultView.finalMode.confidence}
							</div>
						</div>
						{#if resultView.finalMode.listingTrust}
							<div class="mt-4 grid gap-3 sm:grid-cols-2">
								<div class="rounded-md border border-border bg-secondary/60 p-3">
									<p class="text-sm font-medium text-foreground">Product fit</p>
									<p class="mt-1 text-sm leading-6 text-muted-foreground">
										{resultView.finalMode.rationale}
									</p>
								</div>
								<div
									class={`rounded-md border p-3 ${
										resultView.finalMode.listingTrust.isBlocking
											? 'border-destructive/45 bg-destructive/10'
											: 'border-border bg-secondary/60'
									}`}
								>
									<p class="text-sm font-medium text-foreground">
										Listing safety: {resultView.finalMode.listingTrust.levelLabel}
									</p>
									<p class="mt-1 text-sm leading-6 text-muted-foreground">
										{resultView.finalMode.listingTrust.summary}
									</p>
									{#if resultView.finalMode.listingTrust.redFlags.length}
										<p class="mt-1 text-sm leading-6 text-destructive">
											{resultView.finalMode.listingTrust.redFlags.join(' ')}
										</p>
									{/if}
								</div>
							</div>
						{/if}
					{/if}

					{#if resultView.warnings.length}
						<div class="mt-5 rounded-md border border-destructive/45 bg-destructive/10 p-3">
							<p class="text-sm font-medium text-foreground">Watch-outs</p>
							<ul class="mt-2 grid gap-2 text-sm leading-6 text-muted-foreground">
								{#each resultView.warnings.slice(0, 3) as warning}
									<li>{warning}</li>
								{/each}
							</ul>
						</div>
					{/if}

					<div class="mt-5 flex flex-wrap items-center gap-2">
						<Button
							type="button"
							variant="secondary"
							onclick={() => (showSupportingDetails = !showSupportingDetails)}
						>
							{#if showSupportingDetails}
								<ChevronDown />
							{:else}
								<ChevronRight />
							{/if}
							Supporting details
						</Button>
						<Button
							type="button"
							variant="outline"
							onclick={() => (showSourceDetails = !showSourceDetails)}
						>
							{#if showSourceDetails}
								<ChevronDown />
							{:else}
								<ChevronRight />
							{/if}
							Source details
						</Button>
					</div>

					{#if showSupportingDetails}
						<div class="mt-5 grid gap-4">
							{#if resultView.runnerUps.length}
								<section>
									<h3 class="text-sm font-medium text-foreground">Runner-ups</h3>
									<div class="mt-2 grid gap-2">
										{#each resultView.runnerUps as runner}
											<div class="rounded-md border border-border bg-secondary/60 p-3">
												<p class="text-sm font-medium text-foreground">{runner.label}</p>
												<p class="mt-1 text-sm leading-6 text-muted-foreground">
													{runner.rationale}
												</p>
												{#if runner.listingTrust?.isRisky}
													<p class="mt-2 text-sm leading-6 text-destructive">
														Listing safety: {runner.listingTrust.levelLabel}. {runner.listingTrust.summary}
													</p>
												{:else if runner.listingTrust}
													<p class="mt-2 text-sm leading-6 text-muted-foreground">
														Listing safety: {runner.listingTrust.levelLabel}
													</p>
												{/if}
											</div>
										{/each}
									</div>
								</section>
							{/if}

							{#if supportingModeViews.length}
								<section>
									<h3 class="text-sm font-medium text-foreground">Other ways to choose</h3>
									<div class="mt-2 grid gap-2">
										{#each supportingModeViews as mode}
											<div class="rounded-md border border-border bg-secondary/60 p-3">
												<p class="text-sm font-medium text-foreground">{mode.label}</p>
												<p class="mt-1 text-sm leading-6 text-muted-foreground">
													{mode.rationale}
												</p>
												{#if mode.listingTrust?.isRisky}
													<p class="mt-2 text-sm leading-6 text-destructive">
														Listing safety: {mode.listingTrust.levelLabel}. {mode.listingTrust.summary}
													</p>
												{:else if mode.listingTrust}
													<p class="mt-2 text-sm leading-6 text-muted-foreground">
														Listing safety: {mode.listingTrust.levelLabel}
													</p>
												{/if}
											</div>
										{/each}
									</div>
								</section>
							{/if}

							{#if resultView.trustViews.length}
								<section>
									<h3 class="text-sm font-medium text-foreground">Seller and listing checks</h3>
									<div class="mt-2 grid gap-2">
										{#each resultView.trustViews as trust}
											<div class="rounded-md border border-border bg-secondary/60 p-3">
												<p class="text-xs font-medium text-muted-foreground">
													{trust.levelLabel} · confidence: {trust.confidence}
												</p>
												<p class="text-sm font-medium text-foreground">{trust.summary}</p>
												{#if trust.redFlags.length}
													<p class="mt-1 text-sm leading-6 text-destructive">
														{trust.redFlags.join(' ')}
													</p>
												{/if}
												{#if trust.positiveSignals.length}
													<p class="mt-1 text-sm leading-6 text-muted-foreground">
														{trust.positiveSignals.join(' ')}
													</p>
												{/if}
											</div>
										{/each}
									</div>
								</section>
							{/if}

							{#if resultView.rejectedItems.length}
								<section>
									<h3 class="text-sm font-medium text-foreground">Avoid</h3>
									<div class="mt-2 grid gap-2">
										{#each resultView.rejectedItems as item}
											<div class="rounded-md border border-destructive/45 bg-destructive/10 p-3">
												<p class="text-sm leading-6 text-muted-foreground">{item.reason}</p>
											</div>
										{/each}
									</div>
								</section>
							{/if}
						</div>
					{/if}

					{#if showSourceDetails}
						<section class="mt-5">
							<h3 class="text-sm font-medium text-foreground">Sources checked</h3>
							<div class="mt-2 grid gap-2">
								{#each resultView.sourceViews as source}
									<a
										href={source.url}
										target="_blank"
										rel="noreferrer"
										class="rounded-md border border-border bg-secondary/60 p-3 text-sm transition-colors hover:text-foreground"
									>
										<span class="block font-medium text-foreground">{source.title}</span>
										<span class="mt-1 block text-muted-foreground"
											>{source.type.replaceAll('_', ' ')} · quality: {source.quality}</span
										>
									</a>
								{/each}
							</div>
						</section>
					{/if}
				</div>

				<div class="mx-auto mt-8 flex max-w-3xl items-center justify-start">
					<Button type="button" variant="outline" onclick={goBack} disabled={isGuidedRequestPending}>
						<ArrowLeft />
						Back
					</Button>
				</div>
			{/if}
		</div>
	</section>
</main>
