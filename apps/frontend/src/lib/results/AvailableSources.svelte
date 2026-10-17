<script lang="ts">
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import { Button } from '$lib/components/ui/button/index.js';
	import EvidenceDetails from './EvidenceDetails.svelte';
	import type { SourceView } from './result-view.js';

	let { sources }: { sources: SourceView[] } = $props();
</script>

<section id="available-source-details" class="mt-10" aria-labelledby="sources-title">
	<div class="flex items-end justify-between gap-4">
		<div><h2 id="sources-title" class="text-xl font-[510] tracking-[-0.02em] text-foreground">Available sources</h2><p class="mt-1 text-sm text-muted-foreground">Explore the pages, search snippets and optional videos gathered for this decision.</p></div>
		<p class="font-mono text-xs text-muted-foreground">{sources.length} total</p>
	</div>
	<div class="mt-4 divide-y divide-border border-y border-border">
		{#each sources as source}
			<article class="grid gap-4 py-5 sm:grid-cols-[1fr_auto] sm:items-start">
				<div class="min-w-0">
					<p class="break-words text-sm font-[510] text-foreground">{source.title}</p>
					<p class="mt-1 break-all text-xs leading-5 text-muted-foreground">{source.typeLabel} · {source.displayUrl}</p>
					{#if source.video}
						{#if source.video.creatorName}<p class="mt-1 text-xs leading-5 text-muted-foreground">By {source.video.creatorName}</p>{/if}
						<p class="mt-1 text-xs leading-5 text-muted-foreground">{source.video.basisLabel}</p>
					{/if}
					{#if source.snippet}<p class="mt-3 text-sm leading-6 text-muted-foreground">Search snippet: {source.snippet}</p>{/if}
					{#if source.evidence.length}<div class="mt-3 max-w-[760px]"><EvidenceDetails evidence={source.evidence} sources={[]} label="Evidence from this source" /></div>{/if}
				</div>
				{#if source.url}<Button href={source.url} target="_blank" rel="noreferrer noopener" variant="outline" size="sm">{source.video ? 'Watch video' : 'Open source'} <ExternalLink /></Button>{/if}
			</article>
		{/each}
	</div>
</section>
