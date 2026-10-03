<script lang="ts">
	import { Button } from '$lib/components/ui/button/index.js';
	import { normalizeListingLink, type ListingCheckOutcome } from './listing-check.js';

	let {
		outcome = null,
		pending = false,
		error = null,
		onCheck,
	}: {
		outcome?: ListingCheckOutcome | null;
		pending?: boolean;
		error?: string | null;
		onCheck: (url: string) => void;
	} = $props();

	let expanded = $state(false);
	let link = $state('');
	let validationError = $state<string | null>(null);

	function submit() {
		const normalized = normalizeListingLink(link);
		if (!normalized) {
			validationError = 'Enter a full http or https listing link.';
			return;
		}
		validationError = null;
		expanded = false;
		onCheck(normalized);
	}
</script>

<section id="listing-correction" class="mt-8 border-t border-border pt-6" aria-label="Check a listing you found">
	<div class="flex flex-wrap items-start justify-between gap-4">
		<div>
			<h2 class="text-base font-[510] text-foreground">Have a listing you want checked?</h2>
			<p class="mt-1 max-w-[650px] text-sm leading-6 text-muted-foreground">Add it to this decision so CartCart can check the page and seller.</p>
		</div>
		<Button type="button" variant="outline" onclick={() => (expanded = !expanded)} disabled={pending}>
			{outcome?.status === 'unreadable' ? 'Try another link' : 'Check a listing'}
		</Button>
	</div>

	{#if expanded}
		<form class="mt-5 max-w-[720px]" onsubmit={(event) => { event.preventDefault(); submit(); }}>
			<label for="listing-correction-url" class="text-sm text-foreground">Listing link</label>
			<div class="mt-2 flex flex-col gap-3 sm:flex-row">
				<input id="listing-correction-url" type="url" bind:value={link} placeholder="https://shop.example/item" class="min-w-0 flex-1 rounded-md border border-iron bg-steel px-3 py-2 text-sm text-foreground placeholder:text-slate focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none" />
				<Button type="submit" variant="outline" disabled={pending}>Check this listing</Button>
			</div>
			{#if validationError}<p class="mt-2 text-sm text-destructive" role="alert">{validationError}</p>{/if}
		</form>
	{/if}
	{#if error}<p class="mt-4 text-sm text-destructive" role="alert">{error}</p>{/if}
	{#if outcome}
		<div class="mt-5 border-l-2 border-iron pl-4">
			<p class="text-sm font-[510] text-foreground">{outcome.title}</p>
			<p class="mt-1 break-all text-xs text-muted-foreground">{outcome.url}</p>
			<p class="mt-2 text-sm leading-6 text-muted-foreground">{outcome.detail}</p>
			{#if outcome.seller}<p class="mt-2 text-sm text-foreground">Seller: {outcome.seller}</p>{/if}
			{#if outcome.trust}<p class="mt-1 text-sm leading-6 text-muted-foreground">{outcome.trust}</p>{/if}
		</div>
	{/if}
</section>
