<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Check from '@lucide/svelte/icons/check';
	import MapPin from '@lucide/svelte/icons/map-pin';
	import { Button } from '$lib/components/ui/button/index.js';
	import type { RegionOption } from '$lib/session/session-form.js';

	let {
		selectedCode = $bindable(),
		regions,
		pending = false,
		error = null,
		allowBack = false,
		onSave,
		onRefuse,
		onBack,
	}: {
		selectedCode: string;
		regions: RegionOption[];
		pending?: boolean;
		error?: string | null;
		allowBack?: boolean;
		onSave: () => void;
		onRefuse: () => void;
		onBack: () => void;
	} = $props();
</script>

<div class="surface-enter mx-auto w-full max-w-[820px]">
	<div class="text-center">
		<div class="mx-auto mb-6 flex size-11 items-center justify-center rounded-xl border border-border bg-card shadow-subtle" aria-hidden="true">
			<MapPin class="size-4.5 text-accent" />
		</div>
		<h1 class="text-balance text-4xl leading-[1.08] font-light tracking-[-0.035em] text-foreground sm:text-6xl">
			Where will you be shopping?
		</h1>
		<p class="mx-auto mt-5 max-w-[620px] text-pretty text-base leading-7 text-muted-foreground sm:text-[17px]">
			Buying region helps CartCart check realistic availability, shipping, warranty coverage, and seller risk. You only need to set it once.
		</p>
	</div>

	<div class="mx-auto mt-9 max-w-[600px] border-y border-border py-6">
		<label for="region-select" class="text-xs font-medium tracking-[0.12em] text-muted-foreground uppercase">
			Country or region
		</label>
		<div class="relative mt-3">
			<select
				id="region-select"
				bind:value={selectedCode}
				class="h-12 w-full appearance-none rounded-md border border-iron bg-card px-4 pr-11 text-sm text-foreground shadow-subtle outline-none transition-colors hover:border-slate focus:border-ring focus:ring-2 focus:ring-ring/30"
			>
				{#each regions as region}
					<option value={region.code}>{region.label}</option>
				{/each}
			</select>
			<span class="pointer-events-none absolute inset-y-0 right-4 flex items-center text-muted-foreground" aria-hidden="true">⌄</span>
		</div>

		{#if error}
			<p class="mt-4 text-sm text-destructive" role="alert">{error}</p>
		{/if}

		<div class="mt-5 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
			<div>
				{#if allowBack}
					<Button type="button" variant="outline" onclick={onBack} disabled={pending}>
						<ArrowLeft /> Back
					</Button>
				{/if}
			</div>
			<div class="flex flex-col-reverse gap-3 sm:flex-row">
				<Button type="button" variant="outline" onclick={onRefuse} disabled={pending}>I prefer not to say</Button>
				<Button type="button" onclick={onSave} disabled={pending}>
					<Check /> Use this region
				</Button>
			</div>
		</div>
	</div>
</div>
