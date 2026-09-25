<script lang="ts">
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import { Button } from '$lib/components/ui/button/index.js';
	import type { ShopperProgressItem } from './run-progress.js';

	let {
		question,
		headline,
		progress,
		error = null,
		pending = false,
		onRetry,
	}: {
		question: string;
		headline: string;
		progress: ShopperProgressItem[];
		error?: string | null;
		pending?: boolean;
		onRetry: () => void;
	} = $props();

	const activeIndex = $derived(
		Math.max(
			0,
			progress.findIndex((item) => item.status === 'running' || item.status === 'failed'),
		),
	);
</script>

<div class="surface-enter mx-auto w-full max-w-[920px] text-center" aria-busy={!error}>
	<div class="mx-auto mb-7 flex h-12 min-w-16 items-center justify-center rounded-xl border border-border bg-card px-4 shadow-subtle" aria-hidden="true">
		{#if error}
			<span class="size-3 rounded-full bg-destructive"></span>
		{:else}
			<span class="progress-dots flex items-center gap-1.5">
				<span class="progress-dot size-2.5 rounded-full bg-accent"></span>
				<span class="progress-dot size-2.5 rounded-full bg-accent"></span>
				<span class="progress-dot size-2.5 rounded-full bg-accent"></span>
			</span>
		{/if}
	</div>
	<p class="text-xs font-medium tracking-[0.14em] text-muted-foreground uppercase">Working through the decision</p>
	<h1 class="mt-5 text-balance text-[clamp(2.6rem,5.5vw,4.75rem)] leading-[1.02] font-light tracking-[-0.04em] text-foreground">
		{error ? 'We could not finish the comparison.' : headline}
	</h1>
	<p class="mx-auto mt-5 max-w-[680px] text-pretty text-base leading-7 text-muted-foreground">
		{error ?? question}
	</p>

	<div class="mx-auto mt-10 max-w-[720px] border-y border-border py-5 text-left" aria-live="polite" aria-atomic="true">
		<div class="grid grid-cols-4 gap-2" aria-hidden="true">
			{#each progress.slice(0, 4) as item, index}
				<span class={`h-px ${item.status === 'succeeded' || item.status === 'running' ? 'bg-mist' : item.status === 'failed' ? 'bg-destructive' : 'bg-iron'}`}></span>
			{/each}
		</div>
		<div class="mt-5 flex items-start justify-between gap-6">
			<div>
				<p class="text-sm font-[510] text-foreground">
					{progress.find((item) => item.status === 'running' || item.status === 'failed')?.label ?? progress[Math.min(activeIndex, progress.length - 1)]?.label}
				</p>
				<p class="mt-1 text-sm leading-6 text-muted-foreground">
					{progress.find((item) => item.status === 'running' || item.status === 'failed')?.message ?? 'Preparing the next check.'}
				</p>
			</div>
			<p class="shrink-0 font-mono text-xs text-muted-foreground">
				{Math.min(activeIndex + 1, 4)} / 4
			</p>
		</div>
	</div>

	{#if error}
		<div class="mt-6 flex justify-center">
			<Button type="button" onclick={onRetry} disabled={pending}>
				<RotateCcw /> Try again
			</Button>
		</div>
	{/if}
</div>
