<script lang="ts">
	import EvidenceDetails from './EvidenceDetails.svelte';
	import type { ComparisonProductView, ConsideredProductView } from './result-view.js';

	let {
		considered,
		comparison,
	}: {
		considered: ConsideredProductView[];
		comparison: ComparisonProductView[];
	} = $props();

	const statusLabel = (item: ConsideredProductView) => {
		if (item.status === 'manual') return 'Details from you';
		if (item.status === 'excluded') return 'Excluded';
		if (item.status === 'confirmed') return 'Matched';
		if (item.status === 'possible') return 'Possible match';
		return 'Unresolved';
	};
</script>

{#if considered.length || comparison.length}
	<section class="mt-9 border-t border-border pt-7" aria-labelledby="considered-comparison-title">
		<h2 id="considered-comparison-title" class="text-xl font-[510] tracking-[-0.02em] text-foreground">Products considered</h2>
		<p class="mt-1 max-w-[760px] text-sm leading-6 text-muted-foreground">What happened to products you mentioned, and how the saved options compare.</p>

		{#if considered.length}
			<div class="mt-5 divide-y divide-border border-y border-border" aria-label="Products you asked CartCart to check">
				{#each considered as item (item.candidateId)}
					<article class="grid gap-2 py-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] sm:gap-6">
						<div class="min-w-0">
							<p class="break-words text-sm font-[510] text-foreground">{item.askedFor}</p>
							<p class="mt-1 text-xs text-muted-foreground">{statusLabel(item)}</p>
						</div>
						<div class="text-sm leading-6 text-muted-foreground">
							{#if item.status === 'confirmed' || item.status === 'excluded'}
								<p>Matched to {item.matchedName ?? 'a researched product'}{item.inComparison ? ' in the comparison.' : '.'}</p>
							{:else if item.status === 'possible'}
								<p>Several matches remain possible{item.possibleNames.length ? `: ${item.possibleNames.join(', ')}.` : '.'} No single product was confirmed.</p>
							{:else if item.status === 'manual'}
								<p>{item.matchedName ?? 'This product'} was added from your details. No independent product or listing check is available.</p>
								<p>Seller: {item.manualSeller ? `${item.manualSeller} (reported by you)` : 'Unknown'} · Price: {item.manualPrice ? `${item.manualPrice} (reported by you)` : 'Unknown'}</p>
								{#if item.manualUnknowns.length}<p>Still unknown: {item.manualUnknowns.join(', ')}.</p>{/if}
							{:else}
								<p>We could not confirm a product match. Its price, seller, and comparison details remain unknown.</p>
							{/if}
							{#if item.exclusionReason}<p class="mt-1 text-destructive">Why it was excluded: {item.exclusionReason}</p>{/if}
							{#if item.listingRisk}<p class="mt-1 text-destructive">Listing concern: {item.listingRisk}</p>{/if}
						</div>
					</article>
				{/each}
			</div>
		{/if}

		{#if comparison.length}
			<h3 class="mt-8 text-base font-[510] text-foreground">Saved comparison</h3>
			<p class="mt-1 text-sm leading-6 text-muted-foreground">Scores appear only where supporting evidence was saved. Unknown means there was not enough evidence to score that point.</p>
			<div class="mt-4 divide-y divide-border border-y border-border" aria-label="Saved product comparison">
				{#each comparison as product (product.key)}
					<article class="grid gap-3 py-5 md:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)] md:gap-8">
						<div>
							<p class="break-words text-sm font-[510] text-foreground">{product.name}</p>
							{#if product.manual}
								<p class="mt-1 text-xs text-muted-foreground">Added from your details · No verified listing</p>
							{:else}
								<p class="mt-1 text-xs text-muted-foreground">{product.seller ?? 'Seller unknown'} · {product.price ?? 'Price unknown'}</p>
							{/if}
							{#if product.listingRisk}<p class="mt-2 text-sm text-destructive">Listing concern: {product.listingRisk}</p>{/if}
						</div>
						<div>
							{#if product.criteria.length}
								<dl class="grid gap-x-5 gap-y-2 text-sm sm:grid-cols-2">
									{#each product.criteria as criterion}
										<div class="flex justify-between gap-3"><dt class="text-muted-foreground">{criterion.name}</dt><dd class="text-foreground">{criterion.value}</dd></div>
									{/each}
								</dl>
							{:else}
								<p class="text-sm text-muted-foreground">No comparison criteria were saved for this product.</p>
							{/if}
							{#if product.summary}<p class="mt-3 text-sm leading-6 text-muted-foreground">{product.summary}</p>{/if}
							<div class="mt-3"><EvidenceDetails evidence={product.evidence} sources={product.sources} label="Comparison evidence" /></div>
						</div>
					</article>
				{/each}
			</div>
		{/if}
	</section>
{/if}
