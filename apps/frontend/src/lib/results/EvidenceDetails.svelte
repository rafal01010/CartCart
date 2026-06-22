<script lang="ts">
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import type { EvidenceView, SourceView } from './result-view.js';

	let {
		evidence = [],
		sources = [],
		label = 'Inspect evidence',
	}: {
		evidence?: EvidenceView[];
		sources?: SourceView[];
		label?: string;
	} = $props();
</script>

{#if evidence.length || sources.length}
	<details class="group rounded-md border border-border/80 bg-background/30 text-left">
		<summary
			class="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-sm font-medium text-foreground marker:hidden"
		>
			<span>{label}</span>
			<span class="text-xs font-normal text-muted-foreground">
				{evidence.length}
				{evidence.length === 1 ? 'claim' : 'claims'}
			</span>
		</summary>
		<div class="grid gap-4 border-t border-border/80 p-3">
			{#if evidence.length}
				<section>
					<h4 class="text-xs font-medium uppercase text-muted-foreground">Evidence snippets</h4>
					<div class="mt-2 grid gap-3">
						{#each evidence as item}
							<article class="border-l border-border pl-3">
								<div class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
									<span>{item.typeLabel}</span>
									<span aria-hidden="true">·</span>
									<span>{item.targetLabel}</span>
									<span aria-hidden="true">·</span>
									<span>confidence: {item.confidence}</span>
									<span aria-hidden="true">·</span>
									<span>source quality: {item.sourceQuality}</span>
								</div>
								<p class="mt-1 text-sm leading-6 text-foreground">{item.claim}</p>
								<div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
									<span>{item.sourceTitle}</span>
									{#if item.timestampLabels.length}
										<span aria-hidden="true">·</span>
										<span>{item.timestampLabels.join(', ')}</span>
									{/if}
								</div>
								{#if item.metadata.length}
									<p class="mt-1 text-xs leading-5 text-muted-foreground">
										{item.metadata.join(' · ')}
									</p>
								{/if}
								{#if item.sourceUrl}
									<a
										href={item.sourceUrl}
										target="_blank"
										rel="noreferrer noopener"
										class="mt-2 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
									>
										Open source
										<ExternalLink class="size-3" />
									</a>
								{/if}
							</article>
						{/each}
					</div>
				</section>
			{/if}

			{#if sources.length}
				<section>
					<h4 class="text-xs font-medium uppercase text-muted-foreground">Sources</h4>
					<div class="mt-2 grid gap-2">
						{#each sources as source}
							<div class="border-l border-border pl-3">
								<div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
									<div>
										<p class="text-sm font-medium text-foreground">{source.title}</p>
										<p class="mt-1 text-xs leading-5 text-muted-foreground">
											{source.typeLabel} · {source.extractionStatus} · quality:
											{source.qualityLabel} · captured {source.capturedLabel}
										</p>
										<p class="mt-1 text-xs text-muted-foreground">{source.displayUrl}</p>
									</div>
									{#if source.url}
										<a
											href={source.url}
											target="_blank"
											rel="noreferrer noopener"
											class="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-accent hover:underline"
										>
											Open link
											<ExternalLink class="size-3" />
										</a>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</section>
			{/if}
		</div>
	</details>
{/if}
