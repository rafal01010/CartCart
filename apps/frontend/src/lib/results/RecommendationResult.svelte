<script lang="ts">
	import AlertTriangle from '@lucide/svelte/icons/triangle-alert';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import ShieldCheck from '@lucide/svelte/icons/shield-check';
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
		onSelectMode,
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
		result.noStrongBuyReason ?? result.whyItWins ?? selectedMode?.rationale ?? '',
	);
</script>

<div class="surface-enter mx-auto w-full max-w-[1180px] pb-8">
	<div class="max-w-[900px]">
		<p class="text-xs font-medium tracking-[0.14em] text-muted-foreground uppercase">
			{result.noStrongBuyReason ? 'Buying decision' : 'CartCart recommendation'}
		</p>
		<h1 class="mt-4 text-balance text-[clamp(2.8rem,6vw,5.6rem)] leading-[0.98] font-light tracking-[-0.045em] text-foreground">
			{result.noStrongBuyReason ? 'None are strong buys yet.' : result.finalMode ? 'Here is the clear pick.' : 'The saved pick is unavailable.'}
		</h1>
		<p class="mt-6 max-w-[760px] text-pretty text-base leading-7 text-muted-foreground sm:text-[17px]">
			{decisionCopy}
		</p>
	</div>

	{#if !result.noStrongBuyReason && result.decisionModes.length > 1}
		<div class="mt-9 flex max-w-full gap-1 overflow-x-auto border-b border-border pb-px" role="tablist" aria-label="Recommendation mode">
			{#each result.decisionModes as mode}
				<button
					type="button"
					role="tab"
					aria-selected={selectedMode?.key === mode.key}
					class={`relative shrink-0 px-4 py-3 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none ${selectedMode?.key === mode.key ? 'text-foreground after:absolute after:right-0 after:bottom-[-1px] after:left-0 after:h-px after:bg-foreground' : 'text-muted-foreground hover:text-foreground'}`}
					onclick={() => onSelectMode(mode.key)}
				>
					{mode.label}
				</button>
			{/each}
		</div>
	{/if}

	<section class="mt-8 border-y border-border bg-card/45" aria-label="Recommendation summary">
		{#if selectedMode && !result.noStrongBuyReason}
			<div class="grid lg:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.55fr)]">
				<div class="p-5 sm:p-8 lg:border-r lg:border-border lg:p-10">
					<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
						<p class="text-xs font-medium tracking-[0.12em] text-muted-foreground uppercase">{selectedMode.label}</p>
						<span class="h-3 w-px bg-iron" aria-hidden="true"></span>
						<p class="text-xs text-muted-foreground">{selectedMode.confidence} confidence</p>
					</div>
					<h2 class="mt-4 text-balance text-3xl leading-tight font-[510] tracking-[-0.03em] text-foreground sm:text-4xl">
						{selectedMode.productName}
					</h2>
					<p class="mt-4 max-w-[680px] text-base leading-7 text-muted-foreground">{selectedMode.rationale || 'No explanation was saved for this pick.'}</p>

					<div class="mt-7 flex flex-wrap items-center gap-3">
						{#if selectedMode.purchaseUrl && !selectedMode.listingTrust?.isBlocking}
							<Button href={selectedMode.purchaseUrl} target="_blank" rel="noreferrer noopener">
								View listing <ExternalLink />
							</Button>
						{/if}
						<EvidenceDetails evidence={selectedMode.evidence} sources={selectedMode.sources} label="Why this fits" />
					</div>
				</div>

				<aside class="p-5 sm:p-8 lg:p-10" aria-label="Listing details">
					<div class="grid gap-6">
						<div>
							<p class="text-xs font-medium tracking-[0.12em] text-muted-foreground uppercase">Price found</p>
							<p class="mt-2 text-xl font-[510] text-foreground">{selectedMode.priceLabel ?? 'Price unavailable'}</p>
						</div>
						<div>
							<p class="text-xs font-medium tracking-[0.12em] text-muted-foreground uppercase">Seller</p>
							<p class="mt-2 break-words text-sm text-foreground">{selectedMode.sellerName ?? 'Seller details unavailable'}</p>
						</div>
						<div class="border-t border-border pt-5">
							<div class="flex items-center gap-2">
								{#if selectedMode.listingTrust?.isRisky}
									<AlertTriangle class="size-4 text-destructive" />
								{:else}
									<ShieldCheck class="size-4 text-muted-foreground" />
								{/if}
								<p class="text-sm font-[510] text-foreground">
									{selectedMode.listingTrust?.levelLabel ?? 'Listing not fully checked'}
								</p>
							</div>
							<p class="mt-2 text-sm leading-6 text-muted-foreground">
								{selectedMode.listingTrust?.summary ?? 'Open the evidence before deciding where to buy.'}
							</p>
							{#if selectedMode.listingTrust}
								<div class="mt-3">
									<EvidenceDetails evidence={selectedMode.listingTrust.evidence} sources={selectedMode.listingTrust.sources} label="Listing check" />
								</div>
							{/if}
						</div>
					</div>
				</aside>
			</div>
		{:else}
			<div class="p-5 sm:p-8 lg:p-10">
				{#if !result.noStrongBuyReason}<p class="text-sm leading-6 text-muted-foreground">The saved final pick is unavailable.</p>{/if}
				<div class="mt-5 max-w-[680px]">
					<EvidenceDetails evidence={result.resultEvidence} sources={result.resultSources} label={result.noStrongBuyReason ? 'What blocked a recommendation' : 'Saved decision evidence'} />
				</div>
			</div>
		{/if}
	</section>

	{#if result.warnings.length || result.hasWeakEvidence || result.hasConflictingEvidence || result.hasPartialSources}
		<section class="mt-6 border border-destructive/30 bg-destructive/[0.045] p-5 sm:p-6" aria-labelledby="watch-outs-title">
			<div class="flex items-start gap-3">
				<AlertTriangle class="mt-0.5 size-4 shrink-0 text-destructive" />
				<div class="min-w-0">
					<h2 id="watch-outs-title" class="text-sm font-[510] text-foreground">What to watch</h2>
					<div class="mt-2 grid gap-3 text-sm leading-6 text-muted-foreground">
						{#if result.hasConflictingEvidence}<p>Some sources disagree on details that may affect this decision.</p>{/if}
						{#if result.hasWeakEvidence}<p>Some supporting claims have limited evidence. Treat them as less certain.</p>{/if}
						{#if result.hasPartialSources}<p>Some sources could not be fully checked, so the comparison is based on the usable evidence.</p>{/if}
						{#each result.warnings.slice(0, 3) as warning}
							<div>
								<p>{warning.text}</p>
								<div class="mt-2 max-w-[680px]"><EvidenceDetails evidence={warning.evidence} sources={warning.sources} label="Supporting evidence" /></div>
							</div>
						{/each}
						{#if result.warnings.length > 3}
							<details class="group/warnings border-t border-destructive/20 pt-3">
								<summary class="flex cursor-pointer list-none items-center justify-between gap-3 rounded-sm text-sm font-[510] text-foreground marker:hidden focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none">
									<span>More warnings ({result.warnings.length - 3})</span>
									<ChevronRight class="size-4 shrink-0 text-muted-foreground transition-transform group-open/warnings:rotate-90" />
								</summary>
								<div class="mt-3 grid gap-3">
									{#each result.warnings.slice(3) as warning}
										<div>
											<p>{warning.text}</p>
											<div class="mt-2 max-w-[680px]"><EvidenceDetails evidence={warning.evidence} sources={warning.sources} label="Supporting evidence" /></div>
										</div>
									{/each}
								</div>
							</details>
						{/if}
					</div>
				</div>
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
			<span>Source details</span>
			{#if showSourceDetails}<ChevronDown />{:else}<ChevronRight />{/if}
		</button>
	</div>

	{#if showSupportingDetails}
		{#if !result.runnerUps.length && !result.trustViews.length && !result.rejectedItems.length}
			<p class="mt-8 border-y border-border py-6 text-sm leading-6 text-muted-foreground">
				No additional alternatives or listing checks were preserved for this result.
			</p>
		{/if}
		<div class="mt-8 grid gap-10 lg:grid-cols-2">
			{#if result.runnerUps.length}
				<section aria-labelledby="runner-ups-title">
					<h2 id="runner-ups-title" class="text-xl font-[510] tracking-[-0.02em] text-foreground">Runner-ups</h2>
					<div class="mt-4 divide-y divide-border border-y border-border">
						{#each result.runnerUps as runner}
							<article class="py-5">
								<div class="flex items-start justify-between gap-4">
									<div class="min-w-0">
										<p class="break-words text-base font-[510] text-foreground">{runner.productName}</p>
										<p class="mt-1 text-xs text-muted-foreground">{runner.label}{runner.priceLabel ? ` · ${runner.priceLabel}` : ''}</p>
									</div>
									{#if runner.purchaseUrl && !runner.listingTrust?.isBlocking}
										<a href={runner.purchaseUrl} target="_blank" rel="noreferrer noopener" class="shrink-0 rounded-md text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none" aria-label={`Open listing for ${runner.productName}`}><ExternalLink class="size-4" /></a>
									{/if}
								</div>
								<p class="mt-3 text-sm leading-6 text-muted-foreground">{runner.rationale || 'No explanation was saved for this alternative.'}</p>
								{#if runner.listingTrust?.isRisky}<p class="mt-2 text-sm leading-6 text-destructive">{runner.listingTrust.summary}</p>{/if}
								<div class="mt-3"><EvidenceDetails evidence={runner.evidence} sources={runner.sources} label="Why it placed" /></div>
							</article>
						{/each}
					</div>
				</section>
			{/if}

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
				<div><h2 id="sources-title" class="text-xl font-[510] tracking-[-0.02em] text-foreground">Sources checked</h2><p class="mt-1 text-sm text-muted-foreground">Open the evidence behind the recommendation.</p></div>
				<p class="font-mono text-xs text-muted-foreground">{result.sourceViews.length} total</p>
			</div>
			{#if result.sourceViews.length}
				<div class="mt-4 divide-y divide-border border-y border-border">
					{#each result.sourceViews as source}
						<article class="grid gap-4 py-5 sm:grid-cols-[1fr_auto] sm:items-start">
							<div class="min-w-0">
								<p class="break-words text-sm font-[510] text-foreground">{source.title}</p>
								<p class="mt-1 break-all text-xs leading-5 text-muted-foreground">{source.typeLabel} · {source.qualityLabel} · {source.displayUrl}</p>
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
		<p class="max-w-[560px] text-xs leading-5 text-muted-foreground sm:text-right">Decision based on the evidence available for “{question}”. Prices and availability can change.</p>
	</div>
</div>
