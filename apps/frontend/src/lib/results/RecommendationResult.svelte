<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import { Button } from '$lib/components/ui/button/index.js';
	import EvidenceDetails from './EvidenceDetails.svelte';
	import ConsideredComparison from './ConsideredComparison.svelte';
	import type { ModeView, ResultView } from './result-view.js';
	import ListingCorrection from '$lib/user-products/ListingCorrection.svelte';
	import type { ListingCheckOutcome } from '$lib/user-products/listing-check.js';
	import ManualProductFallback from '$lib/user-products/ManualProductFallback.svelte';
	import type { ManualCandidateView } from '$lib/user-products/manual-fallback.js';
	import type { CreateUserAddedProductRequest } from '$lib/api/types.js';

	let {
		result,
		selectedMode,
		question,
		onStartOver,
		listingCheckOutcome = null,
		listingCheckError = null,
		listingCheckPending = false,
		onCheckListing,
		manualCandidates = [],
		manualError = null,
		onSaveManual,
		allowCorrections = true,
	}: {
		result: ResultView;
		selectedMode: ModeView | null;
		question: string;
		onSelectMode: (modeKey: string) => void;
		onStartOver: () => void;
		listingCheckOutcome?: ListingCheckOutcome | null;
		listingCheckError?: string | null;
		listingCheckPending?: boolean;
		onCheckListing: (url: string) => void;
		manualCandidates?: ManualCandidateView[];
		manualError?: string | null;
		onSaveManual: (request: CreateUserAddedProductRequest) => void;
		allowCorrections?: boolean;
	} = $props();

	let showSupportingDetails = $state(false);
	let showSourceDetails = $state(false);

	const decisionCopy = $derived(
		result.noStrongBuyReason ?? result.whyItWins ?? (result.recommendedOptions.length > 1
			? 'Compare these options and their tradeoffs.'
			: result.whyItWins ?? selectedMode?.rationale ?? ''),
	);
</script>

<div class="surface-enter mx-auto w-full max-w-[1180px] pb-8">
	<div class="max-w-[900px]">
		<p class="text-xs font-medium tracking-[0.14em] text-muted-foreground uppercase">
			{result.noStrongBuyReason ? 'Buying decision' : 'CartCart recommendation'}
		</p>
		<h1 class="mt-4 text-balance text-[clamp(2.8rem,6vw,5.6rem)] leading-[0.98] font-light tracking-[-0.045em] text-foreground">
			{result.recommendedOptions.length > 1 ? 'Good options to consider.' : result.recommendedOptions.length ? 'An option worth considering.' : 'No suitable option to suggest yet.'}
		</h1>
		<p class="mt-6 max-w-[760px] text-pretty text-base leading-7 text-muted-foreground sm:text-[17px]">
			{decisionCopy}
		</p>
	</div>

	<section class="mt-8" aria-label="Recommended options">
		{#if result.recommendedOptions.length}
			<div class={`grid gap-5 ${result.recommendedOptions.length > 1 ? 'md:grid-cols-2' : ''} ${result.recommendedOptions.length === 3 ? 'lg:grid-cols-3' : ''}`}>
				{#each result.recommendedOptions as option, index (option.productId)}
					<article class="flex flex-col border border-border bg-card/45 p-5 sm:p-7">
						<div class="flex flex-wrap items-center justify-between gap-2">
							<p class="text-xs font-medium tracking-[0.12em] text-muted-foreground uppercase">Option {index + 1}</p>
						</div>
						<h2 class="mt-4 text-balance text-2xl leading-tight font-[510] tracking-[-0.03em] text-foreground sm:text-3xl">{option.productName}</h2>
						<p class="mt-4 text-sm leading-7 text-muted-foreground">{option.rationale}</p>
						{#if option.tradeoffs.length}
							<div class="mt-4 text-sm leading-6 text-muted-foreground">
								<h3 class="font-[510] text-foreground">Tradeoffs</h3>
								{#each option.tradeoffs as tradeoff}<p class="mt-1">{tradeoff}</p>{/each}
							</div>
						{/if}
						{#if option.budgetNote}<p class="mt-4 text-sm leading-6 text-muted-foreground">{option.budgetNote}</p>{/if}
						<div class="mt-6 flex flex-wrap items-center gap-3">
							{#if option.purchaseUrl}
								<Button href={option.purchaseUrl} target="_blank" rel="noreferrer noopener" variant="outline">View listing <ExternalLink /></Button>
							{:else if option.productUrl}
								<Button href={option.productUrl} target="_blank" rel="noreferrer noopener" variant="outline">Learn more <ExternalLink /></Button>
							{/if}
						</div>
						{#if option.listingId}
							<div class="mt-6 border-t border-border pt-5">
								<p class="text-sm text-foreground">{option.priceLabel ?? 'Price unavailable'}{option.sellerName ? ` · ${option.sellerName}` : ''}</p>
							</div>
						{/if}
					</article>
				{/each}
			</div>
		{:else}
			<div class="border-y border-border bg-card/45 p-5 sm:p-8 lg:p-10">
				{#if !result.noStrongBuyReason}<p class="text-sm leading-6 text-muted-foreground">This saved decision has no suggested options.</p>{/if}
			</div>
		{/if}
	</section>

	{#if result.runnerUps.length}
		<section class="mt-8 border-t border-border pt-6" aria-labelledby="runners-up-title">
			<h2 id="runners-up-title" class="text-lg font-[510] text-foreground">Runners-up</h2>
			<div class="mt-4 grid gap-5 md:grid-cols-2">
				{#each result.runnerUps as option (option.productId)}
					<article class="rounded-md border border-border/60 p-5">
						<h3 class="text-lg font-[510] text-foreground">{option.productName}</h3>
						{#if option.rationale}<p class="mt-3 text-sm leading-6 text-muted-foreground">{option.rationale}</p>{/if}
						{#if option.tradeoffs.length}
							<div class="mt-3 text-sm leading-6 text-muted-foreground">
								<h4 class="font-[510] text-foreground">Tradeoffs</h4>
								{#each option.tradeoffs as tradeoff}<p class="mt-1">{tradeoff}</p>{/each}
							</div>
						{/if}
						{#if option.budgetNote}<p class="mt-3 text-sm leading-6 text-muted-foreground">{option.budgetNote}</p>{/if}
						{#if option.priceLabel}<p class="mt-3 text-sm text-foreground">{option.priceLabel}</p>{/if}
						{#if option.purchaseUrl}
							<a class="mt-4 inline-flex items-center gap-2 rounded-sm text-sm text-foreground underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none" href={option.purchaseUrl} target="_blank" rel="noreferrer noopener">View listing <ExternalLink class="size-3.5" /></a>
						{:else if option.productUrl}
							<a class="mt-4 inline-flex items-center gap-2 rounded-sm text-sm text-foreground underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none" href={option.productUrl} target="_blank" rel="noreferrer noopener">Learn more <ExternalLink class="size-3.5" /></a>
						{/if}
					</article>
				{/each}
			</div>
		</section>
	{/if}

	<ConsideredComparison considered={result.consideredProducts} comparison={result.comparisonProducts} />

	<div class="mt-8 grid gap-3 sm:grid-cols-2">
		<button
			type="button"
			class="flex items-center justify-between gap-4 rounded-md border border-border bg-card px-5 py-4 text-left text-sm font-[510] text-foreground transition-colors hover:border-iron hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
			onclick={() => (showSupportingDetails = !showSupportingDetails)}
			aria-expanded={showSupportingDetails}
		>
			<span>Supporting details</span>
			{#if showSupportingDetails}<ChevronDown />{:else}<ChevronRight />{/if}
		</button>
		<button
			type="button"
			class="flex items-center justify-between gap-4 rounded-md border border-border bg-card px-5 py-4 text-left text-sm font-[510] text-foreground transition-colors hover:border-iron hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
			onclick={() => (showSourceDetails = !showSourceDetails)}
			aria-expanded={showSourceDetails}
		>
			<span>Available sources</span>
			{#if showSourceDetails}<ChevronDown />{:else}<ChevronRight />{/if}
		</button>
	</div>

	{#if showSupportingDetails}
		{#if !result.trustViews.length && !result.rejectedItems.length}
			<p class="mt-8 border-y border-border py-6 text-sm leading-6 text-muted-foreground">
				No additional listing checks were preserved for this result.
			</p>
		{/if}
		<div class="mt-8 grid gap-10 lg:grid-cols-2">
			{#if result.trustViews.length}
				<section aria-labelledby="seller-checks-title">
					<h2 id="seller-checks-title" class="text-xl font-[510] tracking-[-0.02em] text-foreground">Seller and listing checks</h2>
					<div class="mt-4 divide-y divide-border border-y border-border">
						{#each result.trustViews as trust}
							<article class="py-5">
								<p class="text-xs font-medium tracking-[0.1em] text-muted-foreground uppercase">{trust.levelLabel}</p>
								<p class="mt-2 text-sm leading-6 text-foreground">{trust.summary}</p>
								{#if trust.redFlags.length}<p class="mt-2 text-sm leading-6 text-destructive">{trust.redFlags.join(' ')}</p>{/if}
								<div class="mt-3"><EvidenceDetails evidence={trust.evidence} sources={trust.sources} label="Inspect listing evidence" /></div>
							</article>
						{/each}
					</div>
				</section>
			{/if}
		</div>

		{#if result.rejectedItems.length}
			<section class="mt-10" aria-labelledby="avoid-title">
				<h2 id="avoid-title" class="text-xl font-[510] tracking-[-0.02em] text-foreground">Avoid</h2>
				<div class="mt-4 divide-y divide-destructive/20 border-y border-destructive/25">
					{#each result.rejectedItems as item}
						<article class="grid gap-2 py-5 sm:grid-cols-[minmax(180px,0.35fr)_1fr] sm:gap-8">
							<div><p class="break-words text-sm font-[510] text-foreground">{item.label}</p><p class="mt-1 text-xs text-destructive">{item.reasonLabel}</p></div>
							<div><p class="text-sm leading-6 text-muted-foreground">{item.reason}</p><div class="mt-3"><EvidenceDetails evidence={item.evidence} sources={item.sources} label="Why to avoid it" /></div></div>
						</article>
					{/each}
				</div>
			</section>
		{/if}
	{/if}

	{#if showSourceDetails}
		<section class="mt-10" aria-labelledby="sources-title">
			<div class="flex items-end justify-between gap-4">
				<div><h2 id="sources-title" class="text-xl font-[510] tracking-[-0.02em] text-foreground">Available sources</h2><p class="mt-1 text-sm text-muted-foreground">Read the pages and search snippets gathered for this decision.</p></div>
				<p class="font-mono text-xs text-muted-foreground">{result.sourceViews.length} total</p>
			</div>
			{#if result.sourceViews.length}
				<div class="mt-4 divide-y divide-border border-y border-border">
					{#each result.sourceViews as source}
						<article class="grid gap-4 py-5 sm:grid-cols-[1fr_auto] sm:items-start">
							<div class="min-w-0">
								<p class="break-words text-sm font-[510] text-foreground">{source.title}</p>
								<p class="mt-1 break-all text-xs leading-5 text-muted-foreground">{source.typeLabel} · {source.displayUrl}</p>
								{#if source.snippet}<p class="mt-3 text-sm leading-6 text-muted-foreground">Search snippet: {source.snippet}</p>{/if}
								<div class="mt-3 max-w-[760px]"><EvidenceDetails evidence={source.evidence} sources={[]} label="Evidence from this source" /></div>
							</div>
							{#if source.url}<Button href={source.url} target="_blank" rel="noreferrer noopener" variant="outline" size="sm">Open source <ExternalLink /></Button>{/if}
						</article>
					{/each}
				</div>
			{:else}
				<p class="mt-4 border-y border-border py-6 text-sm leading-6 text-muted-foreground">
					No sources were preserved for this result.
				</p>
			{/if}
		</section>
	{/if}

	{#if allowCorrections}
		<ManualProductFallback candidates={manualCandidates} error={manualError} pending={listingCheckPending} onSave={onSaveManual} />
		<ListingCorrection outcome={listingCheckOutcome} error={listingCheckError} pending={listingCheckPending} onCheck={onCheckListing} />
	{/if}

	<div class="mt-10 flex flex-col gap-4 border-t border-border pt-6 sm:flex-row sm:items-center sm:justify-between">
		<Button type="button" variant="outline" onclick={onStartOver}><ArrowLeft /> Ask another question</Button>
		<p class="max-w-[560px] text-xs leading-5 text-muted-foreground sm:text-right">Advice for “{question}”. Prices and availability can change.</p>
	</div>
</div>
