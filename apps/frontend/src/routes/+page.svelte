<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import CheckCircle2 from '@lucide/svelte/icons/check-circle-2';
	import CircleDashed from '@lucide/svelte/icons/circle-dashed';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import LinkIcon from '@lucide/svelte/icons/link';
	import Play from '@lucide/svelte/icons/play';
	import Plus from '@lucide/svelte/icons/plus';
	import Search from '@lucide/svelte/icons/search';
	import ShieldCheck from '@lucide/svelte/icons/shield-check';
	import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
	import { createApiClient, ApiError, subscribeToRunEvents } from '$lib/api/index.js';
	import type {
		ComparisonRow,
		CreateRefinementRequest,
		CreateUserAddedProductRequest,
		RefinementRunResponse,
		RunEvent,
		RunStatus,
		SessionResultsResponse,
		SessionStateResponse,
		ShoppingRunRecord,
		UserAddedProduct,
	} from '$lib/api/types.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import {
		buildResultView,
		scoreLabel,
		shortEntityId,
		type ModeView,
		type TrustView,
	} from '$lib/results/result-view.js';
	import {
		buildRefinementRequest,
		defaultRefinementFormState,
		refinementFormStateFromSession,
	} from '$lib/refinements/refinement-form.js';
	import {
		applyRunEvent,
		createInitialRunProgress,
		isTerminalRunEvent,
		runStatusLabel,
		type StageProgressStatus,
	} from '$lib/run-progress/run-progress.js';
	import {
		REGION_OPTIONS,
		buildCreateSessionRequest,
		defaultSessionFormState,
		fieldSourceLabel,
		regionByCode,
		sessionFormStateFromResponse,
		shortSessionId,
	} from '$lib/session/session-form.js';
	import {
		buildUserAddedProductRequest,
		defaultUserProductFormState,
		resetUserProductFormAfterAdd,
		userAddedProductDetail,
		userAddedProductTitle,
		type UserProductAddMode,
	} from '$lib/user-products/user-product-form.js';
	import {
		buildWorkspaceNotices,
		type WorkspaceNoticeTone,
	} from '$lib/workspace-states/workspace-states.js';

	const api = createApiClient();

	let form = $state(defaultSessionFormState());
	let session = $state<SessionStateResponse | null>(null);
	let queryError = $state<string | null>(null);
	let sessionError = $state<string | null>(null);
	let isSubmitting = $state(false);
	let isLoadingSession = $state(false);
	let runProgress = $state(createInitialRunProgress());
	let currentRun = $state<ShoppingRunRecord | null>(null);
	let currentRunStatus = $state<RunStatus | 'idle'>('idle');
	let runError = $state<string | null>(null);
	let isStartingRun = $state(false);
	let resultBundle = $state<SessionResultsResponse | null>(null);
	let resultError = $state<string | null>(null);
	let isLoadingResult = $state(false);
	let activeModeKey = $state<string | null>(null);
	let userProductForm = $state(defaultUserProductFormState());
	let userProductError = $state<string | null>(null);
	let isAddingUserProduct = $state<UserProductAddMode | null>(null);
	let refinementForm = $state(defaultRefinementFormState());
	let refinementError = $state<string | null>(null);
	let isSubmittingRefinement = $state(false);
	let refinementRuns = $state<RefinementRunResponse[]>([]);
	let runEventsSubscription: ReturnType<typeof subscribeToRunEvents> | null = null;
	let resultView = $derived(resultBundle ? buildResultView(resultBundle) : null);
	let workspaceNotices = $derived(
		buildWorkspaceNotices({
			hasSession: Boolean(session),
			runStatus: currentRunStatus,
			isLoadingSession,
			isLoadingResult,
			result: resultBundle,
			apiErrors: [sessionError, runError, resultError, userProductError, refinementError],
		}),
	);
	let selectedMode = $derived(
		resultView?.modeViews.find((mode) => mode.key === activeModeKey) ??
			resultView?.finalMode ??
			resultView?.modeViews[0] ??
			null,
	);

	onMount(() => {
		const sessionId = new URL(window.location.href).searchParams.get('session');
		if (sessionId) {
			void loadPersistedSession(sessionId);
		}
	});

	onDestroy(() => {
		runEventsSubscription?.close();
	});

	function stageIcon(status: StageProgressStatus) {
		if (status === 'succeeded') return CheckCircle2;
		if (status === 'running') return CircleDashed;
		if (status === 'failed' || status === 'skipped') return AlertTriangle;
		return CircleDashed;
	}

	function stageTone(status: StageProgressStatus): string {
		if (status === 'succeeded') return 'border-accent bg-accent/40 text-accent-foreground';
		if (status === 'running') return 'border-ring bg-secondary text-secondary-foreground';
		if (status === 'skipped') return 'border-warning bg-warning/45 text-warning-foreground';
		if (status === 'failed') return 'border-destructive/30 bg-destructive/10 text-destructive';
		return 'border-border bg-background text-muted-foreground';
	}

	function handleRegionChange() {
		form.currency = regionByCode(form.regionCode).currency;
	}

	function handleRefinementRegionChange() {
		refinementForm.currency = regionByCode(refinementForm.regionCode).currency;
	}

	function stopProductEnterSubmit(event: KeyboardEvent) {
		if (event.key === 'Enter') {
			event.preventDefault();
		}
	}

	async function handleCreateSession(event: SubmitEvent) {
		event.preventDefault();
		queryError = null;
		sessionError = null;

		if (!form.query.trim()) {
			queryError = 'Enter a shopping goal before creating a session.';
			return;
		}

		isSubmitting = true;
		try {
			const createdSession = await api.createSession(buildCreateSessionRequest(form));
			setPersistedSession(createdSession, true);
		} catch (error) {
			sessionError =
				error instanceof ApiError ? error.message : 'Could not create the session. Check the backend.';
		} finally {
			isSubmitting = false;
		}
	}

	async function loadPersistedSession(sessionId: string) {
		isLoadingSession = true;
		sessionError = null;
		try {
			const loadedSession = await api.getSession(sessionId);
			setPersistedSession(loadedSession, false);
			void loadLatestResult(loadedSession.session_id);
		} catch (error) {
			sessionError =
				error instanceof ApiError ? error.message : 'Could not load the saved session from the URL.';
		} finally {
			isLoadingSession = false;
		}
	}

	function setPersistedSession(nextSession: SessionStateResponse, updateUrl: boolean) {
		session = nextSession;
		form = sessionFormStateFromResponse(nextSession);
		refinementForm = refinementFormStateFromSession(nextSession);
		resetRunState();
		resetResultState();
		refinementRuns = [];
		if (updateUrl) {
			const url = new URL(window.location.href);
			url.searchParams.set('session', nextSession.session_id);
			window.history.replaceState({}, '', url);
		}
	}

	async function handleStartRun() {
		if (!session || isStartingRun) return;

		runError = null;
		resetResultState();
		isStartingRun = true;
		currentRunStatus = 'running';
		runProgress = createInitialRunProgress();
		runEventsSubscription?.close();

		try {
			const run = await api.createRun(session.session_id);
			currentRun = run;
			subscribeToCurrentRun(run);
		} catch (error) {
			currentRunStatus = 'failed';
			runError = error instanceof ApiError ? error.message : 'Could not start the run.';
		} finally {
			isStartingRun = false;
		}
	}

	function subscribeToCurrentRun(run: ShoppingRunRecord) {
		runEventsSubscription = subscribeToRunEvents(
			{ sessionId: run.session_id, runId: run.run_id },
			{
				onEvent: handleRunEvent,
				onError: () => {
					if (currentRunStatus === 'running') {
						runError = 'Run event stream disconnected before a terminal event.';
					}
				},
			},
		);
	}

	function handleRunEvent(event: RunEvent) {
		runProgress = applyRunEvent(runProgress, event);
		if (event.status === 'failed' || event.status === 'cancelled') {
			currentRunStatus = event.status;
			runError = event.error?.error.message ?? event.message;
		} else if (event.stage === 'complete') {
			currentRunStatus = 'succeeded';
			runError = null;
			void loadLatestResult();
		} else {
			currentRunStatus = 'running';
		}

		if (isTerminalRunEvent(event)) {
			runEventsSubscription?.close();
			runEventsSubscription = null;
		}
	}

	function resetRunState() {
		runEventsSubscription?.close();
		runEventsSubscription = null;
		currentRun = null;
		currentRunStatus = 'idle';
		runError = null;
		runProgress = createInitialRunProgress();
	}

	async function loadLatestResult(sessionId = session?.session_id) {
		if (!sessionId) return;

		isLoadingResult = true;
		resultError = null;
		try {
			const latestResult = await api.getResults(sessionId);
			resultBundle = latestResult;
			const nextView = buildResultView(latestResult);
			activeModeKey = nextView.finalMode?.key ?? nextView.modeViews[0]?.key ?? null;
		} catch (error) {
			if (error instanceof ApiError && error.code === 'result_not_ready') {
				resultBundle = null;
				activeModeKey = null;
				return;
			}
			resultError = error instanceof ApiError ? error.message : 'Could not load recommendation results.';
		} finally {
			isLoadingResult = false;
		}
	}

	async function handleSubmitRefinement() {
		refinementError = null;
		if (!session) {
			refinementError = 'Create or load a session before refining.';
			return;
		}

		let request: CreateRefinementRequest;
		try {
			request = buildRefinementRequest(refinementForm);
		} catch (error) {
			refinementError = error instanceof Error ? error.message : 'Could not create refinement.';
			return;
		}

		isSubmittingRefinement = true;
		resetResultState();
		runEventsSubscription?.close();
		runEventsSubscription = null;
		currentRunStatus = 'running';
		runProgress = createInitialRunProgress();

		try {
			const refinement = await api.createRefinement(session.session_id, request);
			refinementRuns = [...refinementRuns, refinement];
			currentRun = refinement.run;
			currentRunStatus = refinement.run.status;
			subscribeToCurrentRun(refinement.run);
			if (refinement.run.status === 'succeeded') {
				void loadLatestResult(session.session_id);
			}
		} catch (error) {
			currentRunStatus = 'failed';
			refinementError =
				error instanceof ApiError ? error.message : 'Could not create the refinement run.';
		} finally {
			isSubmittingRefinement = false;
		}
	}

	function resetResultState() {
		resultBundle = null;
		resultError = null;
		isLoadingResult = false;
		activeModeKey = null;
	}

	async function handleAddUserProduct(mode: UserProductAddMode) {
		userProductError = null;
		if (!session) {
			userProductError = 'Create or load a session before adding products.';
			return;
		}

		let request: CreateUserAddedProductRequest;
		try {
			request = buildUserAddedProductRequest(userProductForm, mode);
		} catch (error) {
			userProductError = error instanceof Error ? error.message : 'Could not add product.';
			return;
		}

		isAddingUserProduct = mode;
		try {
			const updatedSession = await api.addUserProduct(session.session_id, request);
			session = updatedSession;
			form = sessionFormStateFromResponse(updatedSession);
			userProductForm = resetUserProductFormAfterAdd(userProductForm, mode);
			resetRunState();
			resetResultState();
			refinementRuns = [];
		} catch (error) {
			userProductError =
				error instanceof ApiError ? error.message : 'Could not add the user product.';
		} finally {
			isAddingUserProduct = null;
		}
	}

	function sessionHeading(): string {
		return session?.current_brief.original_query || form.query || 'New shopping session';
	}

	function displayRegion(): string {
		const regionCode = session?.current_brief.region?.region.country_code ?? form.regionCode;
		return regionByCode(regionCode).label;
	}

	function displayBudget(): string {
		const budget = session?.current_brief.budget;
		if (budget) {
			return `${budget.amount.currency} ${budget.amount.amount} ${budget.mode === 'hard_cap' ? 'hard cap' : 'preferred'}`;
		}
		const amount = form.budget.trim();
		return amount ? `${form.currency} ${amount} ${form.budgetMode === 'hard_cap' ? 'hard cap' : 'preferred'}` : 'Not set';
	}

	function sessionStatusLabel(): string {
		if (isLoadingSession) return 'Loading session';
		if (session) return `Saved session ${shortSessionId(session.session_id)}`;
		return 'No session yet';
	}

	function runStatusDotClass(): string {
		if (currentRunStatus === 'succeeded') return 'bg-accent';
		if (currentRunStatus === 'failed' || currentRunStatus === 'cancelled') return 'bg-destructive';
		if (currentRunStatus === 'running') return 'bg-ring';
		return 'bg-muted-foreground';
	}

	function modeForRow(row: ComparisonRow): ModeView | null {
		return (
			resultView?.modeViews.find(
				(mode) =>
					mode.productId === row.product_id &&
					(!row.listing_id || mode.listingId === row.listing_id),
			) ?? null
		);
	}

	function trustForListing(listingId: string | null | undefined): TrustView | null {
		if (!listingId) return null;
		return resultView?.trustViews.find((trust) => trust.listingId === listingId) ?? null;
	}

	function rowSourceCount(row: ComparisonRow): number {
		const mode = modeForRow(row);
		if (mode) return mode.sources.length;
		return row.evidence_ids.length;
	}

	function userProductBadge(product: UserAddedProduct): string {
		if (product.url && product.product) return 'URL and manual';
		if (product.url) return 'URL';
		if (product.product) return 'Manual';
		return 'Text';
	}

	function noticeToneClass(tone: WorkspaceNoticeTone): string {
		if (tone === 'danger') return 'border-destructive/30 bg-destructive/10 text-destructive';
		if (tone === 'warning') return 'border-warning/60 bg-warning/35 text-warning-foreground';
		if (tone === 'progress') return 'border-ring/40 bg-secondary text-secondary-foreground';
		return 'border-border bg-muted/40 text-muted-foreground';
	}
</script>

<svelte:head>
	<title>CartCart</title>
	<meta name="description" content="CartCart shopping comparison workspace." />
</svelte:head>

<main class="min-h-screen bg-background text-foreground">
	<div class="mx-auto grid max-w-[1500px] gap-0 lg:grid-cols-[360px_minmax(0,1fr)_330px]">
		<aside class="border-b bg-card/80 lg:min-h-screen lg:border-r lg:border-b-0">
			<div class="border-b px-5 py-4">
				<p class="text-xs font-semibold uppercase text-muted-foreground">CartCart</p>
				<h1 class="mt-1 text-xl font-semibold">Shopping research workspace</h1>
			</div>

			<form class="space-y-5 px-5 py-5" onsubmit={handleCreateSession}>
				<section class="space-y-2">
					<label for="shopping-goal" class="text-sm font-medium">Shopping goal</label>
					<textarea
						id="shopping-goal"
						bind:value={form.query}
						aria-invalid={queryError ? 'true' : undefined}
						aria-describedby={queryError ? 'shopping-goal-error' : undefined}
						class="min-h-36 w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
						placeholder="Reliable 27 inch monitor for coding, movies, and light gaming"
					></textarea>
					{#if queryError}
						<p id="shopping-goal-error" class="text-sm text-destructive">{queryError}</p>
					{/if}
				</section>

				<section class="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
					<label class="space-y-2">
						<span class="text-sm font-medium">Region</span>
						<select
							bind:value={form.regionCode}
							onchange={handleRegionChange}
							class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus:border-ring focus:ring-3 focus:ring-ring/20"
						>
							{#each REGION_OPTIONS as region}
								<option value={region.code}>{region.label}</option>
							{/each}
						</select>
					</label>
					<label class="space-y-2">
						<span class="text-sm font-medium">Currency</span>
						<select
							bind:value={form.currency}
							class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus:border-ring focus:ring-3 focus:ring-ring/20"
						>
							<option>USD</option>
							<option>CAD</option>
							<option>GBP</option>
							<option>AUD</option>
						</select>
					</label>
				</section>

				<section class="space-y-3">
					<div class="grid grid-cols-[minmax(0,1fr)_140px] gap-3">
						<label class="space-y-2">
							<span class="text-sm font-medium">Budget</span>
							<input
								bind:value={form.budget}
								class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
								inputmode="decimal"
								placeholder="400"
							/>
						</label>
						<fieldset class="space-y-2">
							<legend class="text-sm font-medium">Budget mode</legend>
							<div class="grid grid-cols-2 rounded-md border bg-background p-1">
								<label
									class={`rounded-sm px-2 py-1.5 text-center text-xs font-medium ${form.budgetMode === 'preferred' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}
								>
									<input
										bind:group={form.budgetMode}
										class="sr-only"
										type="radio"
										name="budget-mode"
										value="preferred"
									/>
									Soft
								</label>
								<label
									class={`rounded-sm px-2 py-1.5 text-center text-xs font-medium ${form.budgetMode === 'hard_cap' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}
								>
									<input
										bind:group={form.budgetMode}
										class="sr-only"
										type="radio"
										name="budget-mode"
										value="hard_cap"
									/>
									Hard
								</label>
							</div>
						</fieldset>
					</div>

					<label class="space-y-2">
						<span class="text-sm font-medium">Priorities</span>
						<input
							bind:value={form.priorities}
							class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
							placeholder="text clarity, reliable seller, no curved screen"
						/>
					</label>
				</section>

				<section class="space-y-3 border-t pt-4" aria-labelledby="user-added-products-heading">
					<div class="flex items-center justify-between gap-3">
						<h2 id="user-added-products-heading" class="text-sm font-semibold">User-added products</h2>
						<Button
							variant="outline"
							size="icon-sm"
							aria-label="Add manual product"
							type="button"
							disabled={!session || isAddingUserProduct !== null}
							onclick={() => void handleAddUserProduct('manual')}
						>
							<Plus />
						</Button>
					</div>
					<label class="space-y-2">
						<span class="text-sm font-medium">Product URL</span>
						<div class="flex gap-2">
							<input
								bind:value={userProductForm.url}
								disabled={!session || isAddingUserProduct !== null}
								onkeydown={stopProductEnterSubmit}
								class="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
								placeholder="https://store.example/product"
							/>
							<Button
								variant="secondary"
								size="icon"
								aria-label="Attach URL"
								type="button"
								disabled={!session || isAddingUserProduct !== null}
								onclick={() => void handleAddUserProduct('url')}
							>
								<LinkIcon />
							</Button>
						</div>
					</label>
					<label class="space-y-2">
						<span class="text-sm font-medium">Manual product</span>
						<input
							bind:value={userProductForm.name}
							disabled={!session || isAddingUserProduct !== null}
							onkeydown={stopProductEnterSubmit}
							class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
							placeholder="ASUS ProArt PA278QV"
						/>
					</label>
					<div class="grid grid-cols-2 gap-2">
						<label class="space-y-2">
							<span class="text-sm font-medium">Brand</span>
							<input
								bind:value={userProductForm.brand}
								disabled={!session || isAddingUserProduct !== null}
								onkeydown={stopProductEnterSubmit}
								class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
								placeholder="ASUS"
							/>
						</label>
						<label class="space-y-2">
							<span class="text-sm font-medium">Model</span>
							<input
								bind:value={userProductForm.model}
								disabled={!session || isAddingUserProduct !== null}
								onkeydown={stopProductEnterSubmit}
								class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
								placeholder="PA278CV"
							/>
						</label>
					</div>
					<label class="space-y-2">
						<span class="text-sm font-medium">Category</span>
						<input
							bind:value={userProductForm.category}
							disabled={!session || isAddingUserProduct !== null}
							onkeydown={stopProductEnterSubmit}
							class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
							placeholder="monitor"
						/>
					</label>
					<label class="space-y-2">
						<span class="text-sm font-medium">Product notes</span>
						<input
							bind:value={userProductForm.notes}
							disabled={!session || isAddingUserProduct !== null}
							onkeydown={stopProductEnterSubmit}
							class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
							placeholder="price, seller, why it is being considered"
						/>
					</label>
					{#if userProductError}
						<p class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
							{userProductError}
						</p>
					{/if}
					<div class="grid grid-cols-2 gap-2">
						<Button
							variant="secondary"
							size="sm"
							type="button"
							disabled={!session || isAddingUserProduct !== null}
							onclick={() => void handleAddUserProduct('url')}
						>
							<LinkIcon />
							{isAddingUserProduct === 'url' ? 'Adding URL' : 'Add URL'}
						</Button>
						<Button
							variant="outline"
							size="sm"
							type="button"
							disabled={!session || isAddingUserProduct !== null}
							onclick={() => void handleAddUserProduct('manual')}
						>
							<Plus />
							{isAddingUserProduct === 'manual' ? 'Adding manual' : 'Add manual'}
						</Button>
					</div>
				</section>

				{#if sessionError}
					<p class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
						{sessionError}
					</p>
				{/if}

				<div class="flex gap-2 border-t pt-4">
					<Button class="flex-1" type="submit" disabled={isSubmitting || isLoadingSession}>
						<Search />
						{isSubmitting ? 'Creating session' : 'Create session'}
					</Button>
					<Button variant="outline" size="icon" aria-label="Refine controls">
						<SlidersHorizontal />
					</Button>
				</div>
			</form>
		</aside>

		<section class="min-w-0">
			<div class="border-b bg-background px-5 py-4">
				<div class="flex flex-wrap items-center justify-between gap-3">
					<div>
						<p class="text-sm font-medium text-muted-foreground">{sessionStatusLabel()}</p>
						<h2 class="text-2xl font-semibold">{sessionHeading()}</h2>
					</div>
					<div class="flex flex-wrap items-center gap-2">
						<div class="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
							<span class={`size-2 rounded-full ${runStatusDotClass()}`}></span>
							{runStatusLabel(currentRunStatus)}
						</div>
						<Button
							variant="secondary"
							size="sm"
							disabled={!session || isStartingRun || currentRunStatus === 'running'}
							onclick={handleStartRun}
						>
							<Play />
							{isStartingRun ? 'Starting' : 'Start run'}
						</Button>
					</div>
				</div>
			</div>

			<div class="grid gap-5 p-5">
				{#if workspaceNotices.length}
					<section class="grid gap-2 md:grid-cols-2 xl:grid-cols-3" aria-label="Workspace states">
						{#each workspaceNotices as notice}
							<article class={`rounded-md border px-3 py-2 ${noticeToneClass(notice.tone)}`}>
								<p class="text-sm font-semibold">{notice.title}</p>
								<p class="mt-1 text-xs">{notice.message}</p>
							</article>
						{/each}
					</section>
				{/if}

				<section class="grid gap-3 md:grid-cols-4">
					<div class="rounded-md border bg-card p-4">
						<p class="text-xs font-medium text-muted-foreground">Inferred category</p>
						<div class="mt-2 flex items-center justify-between gap-2">
							<p class="text-sm font-semibold">{session?.current_brief.category ?? 'Not inferred yet'}</p>
							<span class="rounded-sm bg-secondary px-2 py-1 text-xs text-secondary-foreground">
								{fieldSourceLabel(session?.current_brief.category_source)}
							</span>
						</div>
					</div>
					<div class="rounded-md border bg-card p-4">
						<p class="text-xs font-medium text-muted-foreground">Region</p>
						<p class="mt-2 text-sm font-semibold">{displayRegion()}</p>
					</div>
					<div class="rounded-md border bg-card p-4">
						<p class="text-xs font-medium text-muted-foreground">Budget</p>
						<p class="mt-2 text-sm font-semibold">{displayBudget()}</p>
					</div>
					<div class="rounded-md border bg-card p-4">
						<p class="text-xs font-medium text-muted-foreground">Session ID</p>
						<p class="mt-2 text-sm font-semibold">
							{session ? shortSessionId(session.session_id) : 'Not saved'}
						</p>
					</div>
				</section>

				<section class="rounded-md border bg-card">
					<div class="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
						<div>
							<h3 class="text-sm font-semibold">Refinement</h3>
							{#if resultBundle}
								<p class="mt-1 text-xs text-muted-foreground">
									Result {resultView?.versionLabel} · Run {shortSessionId(resultBundle.result_version.run_id)}
								</p>
							{/if}
						</div>
						{#if refinementRuns.length}
							<span class="rounded-sm bg-muted px-2 py-1 text-xs">
								{refinementRuns.length} refinement{refinementRuns.length === 1 ? '' : 's'}
							</span>
						{/if}
					</div>
					<div class="grid gap-3 p-4 lg:grid-cols-[minmax(0,1fr)_150px_150px_150px_minmax(0,1fr)_auto]">
						<label class="space-y-2">
							<span class="text-sm font-medium">Category</span>
							<input
								bind:value={refinementForm.category}
								disabled={!session || isSubmittingRefinement || currentRunStatus === 'running'}
								class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
								placeholder="monitor"
							/>
						</label>
						<label class="space-y-2">
							<span class="text-sm font-medium">Region</span>
							<select
								bind:value={refinementForm.regionCode}
								disabled={!session || isSubmittingRefinement || currentRunStatus === 'running'}
								onchange={handleRefinementRegionChange}
								class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus:border-ring focus:ring-3 focus:ring-ring/20"
							>
								{#each REGION_OPTIONS as region}
									<option value={region.code}>{region.label}</option>
								{/each}
							</select>
						</label>
						<label class="space-y-2">
							<span class="text-sm font-medium">Budget</span>
							<input
								bind:value={refinementForm.budget}
								disabled={!session || isSubmittingRefinement || currentRunStatus === 'running'}
								class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
								inputmode="decimal"
								placeholder="400"
							/>
						</label>
						<fieldset class="space-y-2">
							<legend class="text-sm font-medium">Budget mode</legend>
							<div class="grid grid-cols-2 rounded-md border bg-background p-1">
								<label
									class={`rounded-sm px-2 py-1.5 text-center text-xs font-medium ${refinementForm.budgetMode === 'preferred' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}
								>
									<input
										bind:group={refinementForm.budgetMode}
										class="sr-only"
										type="radio"
										name="refinement-budget-mode"
										value="preferred"
										disabled={!session || isSubmittingRefinement || currentRunStatus === 'running'}
									/>
									Soft
								</label>
								<label
									class={`rounded-sm px-2 py-1.5 text-center text-xs font-medium ${refinementForm.budgetMode === 'hard_cap' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}
								>
									<input
										bind:group={refinementForm.budgetMode}
										class="sr-only"
										type="radio"
										name="refinement-budget-mode"
										value="hard_cap"
										disabled={!session || isSubmittingRefinement || currentRunStatus === 'running'}
									/>
									Hard
								</label>
							</div>
						</fieldset>
						<label class="space-y-2">
							<span class="text-sm font-medium">Preferences</span>
							<input
								bind:value={refinementForm.preferences}
								disabled={!session || isSubmittingRefinement || currentRunStatus === 'running'}
								class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-3 focus:ring-ring/20"
								placeholder="better value, avoid marketplace sellers"
							/>
						</label>
						<div class="flex items-end">
							<Button
								type="button"
								variant="secondary"
								size="sm"
								disabled={!session || isSubmittingRefinement || currentRunStatus === 'running'}
								onclick={() => void handleSubmitRefinement()}
							>
								<SlidersHorizontal />
								{isSubmittingRefinement ? 'Submitting' : 'Submit'}
							</Button>
						</div>
					</div>
					{#if refinementError}
						<p class="mx-4 mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
							{refinementError}
						</p>
					{/if}
					{#if refinementRuns.length}
						<div class="border-t px-4 py-3">
							<div class="flex flex-wrap gap-2">
								{#each refinementRuns as refinement}
									<span class="rounded-md border bg-background px-2 py-1 text-xs text-muted-foreground">
										Run {shortSessionId(refinement.run.run_id)} · {runStatusLabel(refinement.run.status)}
									</span>
								{/each}
							</div>
						</div>
					{/if}
				</section>

				<section class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
					<div class="space-y-5">
						<section class="rounded-md border bg-card">
							<div class="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
								<div>
									<h3 class="text-sm font-semibold">Run progress</h3>
									{#if currentRun}
										<p class="mt-1 text-xs text-muted-foreground">Run {shortSessionId(currentRun.run_id)}</p>
									{/if}
								</div>
								{#if runError}
									<p class="max-w-md rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
										{runError}
									</p>
								{/if}
							</div>
							<ol class="grid gap-0 divide-y">
								{#each runProgress as stage}
									{@const Icon = stageIcon(stage.status)}
									<li class="grid gap-3 px-4 py-3 sm:grid-cols-[190px_minmax(0,1fr)]">
										<div class="flex items-center gap-2">
											<span class={`flex size-7 items-center justify-center rounded-full border ${stageTone(stage.status)}`}>
												<Icon class="size-4" />
											</span>
											<span class="text-sm font-medium">{stage.label}</span>
										</div>
										<p class="text-sm text-muted-foreground">{stage.message}</p>
									</li>
								{/each}
							</ol>
						</section>

						<section class="rounded-md border bg-card">
							<div class="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
								<h3 class="text-sm font-semibold">Generated shortlist</h3>
								<p class="text-xs text-muted-foreground">Product and listing signals</p>
							</div>
							<div class="grid gap-3 p-4 lg:grid-cols-3">
								{#if resultBundle}
									{#each resultBundle.comparison_matrix.rows as row}
										{@const rowMode = modeForRow(row)}
										{@const rowTrust = trustForListing(row.listing_id)}
										<article class="rounded-md border bg-background p-4">
											<div class="flex items-start justify-between gap-3">
												<div>
													<h4 class="text-sm font-semibold">
														{rowMode?.label ?? `Product ${shortEntityId(row.product_id)}`}
													</h4>
													<p class="mt-1 text-xs text-muted-foreground">
														Listing {shortEntityId(row.listing_id)}
													</p>
												</div>
												<span class="rounded-sm bg-muted px-2 py-1 text-xs">
													{rowTrust?.level ?? 'unassessed'}
												</span>
											</div>
											<p class="mt-3 text-sm text-muted-foreground">{row.summary ?? 'Analysis summary pending.'}</p>
											<dl class="mt-4 grid gap-2 text-xs">
												<div class="flex justify-between gap-3">
													<dt class="text-muted-foreground">Fit</dt>
													<dd class="text-right font-medium">{scoreLabel(row.scores.fit)}</dd>
												</div>
												<div class="flex justify-between gap-3">
													<dt class="text-muted-foreground">Seller trust</dt>
													<dd class="text-right font-medium">{scoreLabel(row.scores.seller_trust)}</dd>
												</div>
												<div class="flex justify-between gap-3">
													<dt class="text-muted-foreground">Sources</dt>
													<dd class="text-right font-medium">{rowSourceCount(row)}</dd>
												</div>
											</dl>
										</article>
									{/each}
								{:else}
									<article class="rounded-md border bg-background p-4">
										<h4 class="text-sm font-semibold">No generated candidates loaded</h4>
										<p class="mt-2 text-sm text-muted-foreground">
											Generated candidates will appear after analysis.
										</p>
									</article>
								{/if}
							</div>
						</section>

						<section class="rounded-md border bg-card">
							<div class="border-b px-4 py-3">
								<h3 class="text-sm font-semibold">Candidate comparison</h3>
							</div>
							<div class="overflow-x-auto">
								<table class="w-full min-w-[640px] text-left text-sm">
									<thead class="border-b bg-muted/40 text-xs text-muted-foreground">
										<tr>
											<th class="px-4 py-3 font-medium">Candidate</th>
											{#if resultBundle}
												{#each resultBundle.comparison_matrix.criteria as criterion}
													<th class="px-4 py-3 font-medium">{criterion.name}</th>
												{/each}
											{:else}
												<th class="px-4 py-3 font-medium">Fit</th>
												<th class="px-4 py-3 font-medium">Value</th>
												<th class="px-4 py-3 font-medium">Listing trust</th>
											{/if}
											<th class="px-4 py-3 font-medium">Evidence</th>
										</tr>
									</thead>
									<tbody class="divide-y">
										{#if resultBundle}
											{#each resultBundle.comparison_matrix.rows as row}
												{@const rowMode = modeForRow(row)}
												<tr>
													<td class="px-4 py-3 font-medium">
														{rowMode?.label ?? `Product ${shortEntityId(row.product_id)}`}
														<span class="block text-xs font-normal text-muted-foreground">
															Listing {shortEntityId(row.listing_id)}
														</span>
													</td>
													{#each resultBundle.comparison_matrix.criteria as criterion}
														<td class="px-4 py-3">{scoreLabel(row.scores[criterion.name])}</td>
													{/each}
													<td class="px-4 py-3">{row.evidence_ids.length} claims</td>
												</tr>
											{/each}
										{:else}
											<tr>
												<td class="px-4 py-3 font-medium">Pending fixture result</td>
												<td class="px-4 py-3">Not scored</td>
												<td class="px-4 py-3">Not scored</td>
												<td class="px-4 py-3">Not assessed</td>
												<td class="px-4 py-3">No claims</td>
											</tr>
										{/if}
									</tbody>
								</table>
							</div>
						</section>
					</div>

					<aside class="space-y-5">
						<section class="rounded-md border bg-card">
							<div class="flex items-center justify-between gap-3 border-b px-4 py-3">
								<h3 class="text-sm font-semibold">Recommendation</h3>
								{#if resultView}
									<span class="rounded-sm bg-muted px-2 py-1 text-xs">{resultView.versionLabel}</span>
								{/if}
							</div>
							<div class="space-y-4 p-4">
								{#if resultError}
									<p class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
										{resultError}
									</p>
								{/if}
								{#if isLoadingResult}
									<div class="rounded-md border border-dashed bg-muted/30 p-4">
										<p class="text-xs font-medium text-muted-foreground">Final pick</p>
										<p class="mt-2 text-sm font-semibold">Loading result</p>
									</div>
								{:else if resultView}
									<div class="rounded-md border bg-background p-4">
										<p class="text-xs font-medium text-muted-foreground">
											{resultView.noStrongBuyReason ? 'No strong buy' : 'Final pick'}
										</p>
										<p class="mt-2 text-sm font-semibold">
											{resultView.noStrongBuyReason ??
												resultView.finalMode?.label ??
												'Recommendation unavailable'}
										</p>
										{#if resultView.finalMode}
											<p class="mt-1 text-xs text-muted-foreground">
												Product {shortEntityId(resultView.finalMode.productId)} · Listing
												{shortEntityId(resultView.finalMode.listingId)}
											</p>
										{/if}
										{#if resultView.whyItWins}
											<div class="mt-4 rounded-md border bg-muted/30 p-3">
												<p class="text-xs font-medium text-muted-foreground">Why it wins</p>
												<p class="mt-2 text-sm text-foreground">{resultView.whyItWins}</p>
											</div>
										{/if}
									</div>

									<div class="grid grid-cols-2 gap-2">
										{#each resultView.modeViews as mode}
											<button
												type="button"
												class={`rounded-md border px-3 py-2 text-left text-xs font-medium ${selectedMode?.key === mode.key ? 'bg-primary text-primary-foreground' : 'bg-background text-muted-foreground'}`}
												onclick={() => (activeModeKey = mode.key)}
											>
												{mode.label}
											</button>
										{/each}
									</div>

									{#if selectedMode}
										<div class="rounded-md border bg-background p-3">
											<div class="flex items-start justify-between gap-3">
												<div>
													<p class="text-sm font-semibold">{selectedMode.label}</p>
													<p class="mt-1 text-xs text-muted-foreground">
														{selectedMode.confidence} confidence
													</p>
												</div>
												<span class="rounded-sm bg-secondary px-2 py-1 text-xs text-secondary-foreground">
													{selectedMode.sources.length} sources
												</span>
											</div>
											<p class="mt-3 text-sm text-muted-foreground">{selectedMode.rationale}</p>
										</div>
									{/if}

									{#if resultView.runnerUps.length}
										<div class="space-y-2">
											<p class="text-xs font-medium text-muted-foreground">Runner-ups</p>
											{#each resultView.runnerUps as runnerUp}
												<div class="rounded-md border bg-background p-3">
													<p class="text-sm font-semibold">{runnerUp.label}</p>
													<p class="mt-1 text-sm text-muted-foreground">{runnerUp.rationale}</p>
												</div>
											{/each}
										</div>
									{/if}

									{#if resultView.warnings.length}
										<div class="rounded-md border border-warning/60 bg-warning/35 p-3">
											<div class="flex items-center gap-2">
												<AlertTriangle class="size-4" />
												<p class="text-sm font-semibold">Warnings and red flags</p>
											</div>
											<ul class="mt-3 space-y-2 text-sm text-warning-foreground">
												{#each resultView.warnings as warning}
													<li>{warning}</li>
												{/each}
											</ul>
										</div>
									{/if}

									{#if resultView.rejectedItems.length}
										<div class="space-y-2">
											<p class="text-xs font-medium text-muted-foreground">Why not</p>
											{#each resultView.rejectedItems as item}
												<div class="rounded-md border border-destructive/30 bg-destructive/10 p-3">
													<p class="text-sm font-semibold">{item.label}</p>
													<p class="mt-1 text-xs text-muted-foreground">{item.severity}</p>
													<p class="mt-2 text-sm text-destructive">{item.reason}</p>
												</div>
											{/each}
										</div>
									{/if}
								{:else}
									<div class="rounded-md border border-dashed bg-muted/30 p-4">
										<p class="text-xs font-medium text-muted-foreground">Final pick</p>
										<p class="mt-2 text-sm font-semibold">Pending analysis</p>
									</div>
								{/if}
							</div>
						</section>

						<section class="rounded-md border bg-card">
							<div class="flex items-center gap-2 border-b px-4 py-3">
								<ShieldCheck class="size-4 text-muted-foreground" />
								<h3 class="text-sm font-semibold">Trust notes</h3>
							</div>
							<div class="space-y-3 p-4 text-sm">
								{#if resultView?.trustViews.length}
									{#each resultView.trustViews as trust}
										<div class="rounded-md border bg-background p-3">
											<div class="flex items-start justify-between gap-3">
												<div>
													<p class="font-medium">Listing {shortEntityId(trust.listingId)}</p>
													<p class="mt-1 text-xs text-muted-foreground">
														{trust.level} · {trust.confidence}
													</p>
												</div>
												<span class="rounded-sm bg-muted px-2 py-1 text-xs">
													{trust.sources.length} sources
												</span>
											</div>
											<p class="mt-2 text-muted-foreground">{trust.summary}</p>
											{#if trust.redFlags.length}
												<ul class="mt-3 space-y-1 text-destructive">
													{#each trust.redFlags as flag}
														<li>{flag}</li>
													{/each}
												</ul>
											{:else if trust.positiveSignals.length}
												<ul class="mt-3 space-y-1 text-muted-foreground">
													{#each trust.positiveSignals as signal}
														<li>{signal}</li>
													{/each}
												</ul>
											{/if}
										</div>
									{/each}
								{:else}
									<div class="rounded-md border bg-background p-3">
										<p class="font-medium">Trust assessment pending</p>
										<p class="mt-1 text-muted-foreground">Listing trust notes have not loaded.</p>
									</div>
								{/if}
							</div>
						</section>

						<section class="rounded-md border bg-card">
							<div class="border-b px-4 py-3">
								<h3 class="text-sm font-semibold">User-added candidates</h3>
							</div>
							<div class="space-y-3 p-4">
								{#if session?.user_added_products.length}
									{#each session.user_added_products as product}
										<div class="rounded-md border bg-background p-3 text-sm">
											<div class="flex items-start justify-between gap-3">
												<div>
													<p class="font-medium">{userAddedProductTitle(product)}</p>
													<p class="mt-1 text-muted-foreground">{userAddedProductDetail(product)}</p>
												</div>
												<span class="rounded-sm bg-muted px-2 py-1 text-xs">
													{userProductBadge(product)}
												</span>
											</div>
										</div>
									{/each}
								{:else}
									<div class="rounded-md border bg-background p-3 text-sm">
										<p class="font-medium">No user-added candidates</p>
										<p class="mt-1 text-muted-foreground">Added products will appear in session state.</p>
									</div>
								{/if}
							</div>
						</section>
					</aside>
				</section>
			</div>
		</section>

		<aside class="border-t bg-card/70 lg:min-h-screen lg:border-t-0 lg:border-l">
			<div class="border-b px-5 py-4">
				<h2 class="text-sm font-semibold">Source evidence</h2>
				<p class="mt-1 text-sm text-muted-foreground">
					{resultView ? `${resultView.sourceViews.length} sources` : 'Selected source details'}
				</p>
			</div>
			<div class="space-y-4 p-5">
				{#if resultView}
					{#each resultView.sourceViews as source}
						<section class="rounded-md border bg-background p-4">
							<div class="flex items-start justify-between gap-3">
								<div>
									<p class="text-xs font-medium text-muted-foreground">
										{source.type} · {source.quality}
									</p>
									<h3 class="mt-2 text-sm font-semibold">{source.title}</h3>
									<p class="mt-1 text-xs text-muted-foreground">{source.provider}</p>
								</div>
								<a
									class="inline-flex size-8 shrink-0 items-center justify-center rounded-md border bg-background text-muted-foreground hover:text-foreground"
									href={source.url}
									target="_blank"
									rel="noreferrer"
									aria-label={`Open ${source.title}`}
								>
									<ExternalLink class="size-4" />
								</a>
							</div>
							{#if source.evidence.length}
								<ul class="mt-4 space-y-2 text-sm text-muted-foreground">
									{#each source.evidence as evidence}
										<li class="rounded-md bg-muted/40 p-2">
											<span class="block text-xs font-medium text-foreground">
												{evidence.type} · {evidence.confidence}
											</span>
											{evidence.claim}
										</li>
									{/each}
								</ul>
							{/if}
						</section>
					{/each}
				{:else}
					<section class="rounded-md border bg-background p-4">
						<p class="text-xs font-medium text-muted-foreground">Source</p>
						<h3 class="mt-2 text-sm font-semibold">No source bundle loaded</h3>
						<p class="mt-2 text-sm text-muted-foreground">
							Source references have not loaded.
						</p>
					</section>
				{/if}
			</div>
		</aside>
	</div>
</main>
