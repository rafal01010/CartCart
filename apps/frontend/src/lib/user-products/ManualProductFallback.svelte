<script lang="ts">
	import { Button } from '$lib/components/ui/button/index.js';
	import type { CreateUserAddedProductRequest, UserAddedProduct } from '$lib/api/types.js';
	import { manualFallbackRequest, type ManualCandidateView, type ManualFallbackReason } from './manual-fallback.js';

	let {
		candidates,
		pending = false,
		error = null,
		onSave,
	}: {
		candidates: ManualCandidateView[];
		pending?: boolean;
		error?: string | null;
		onSave: (request: CreateUserAddedProductRequest) => void;
	} = $props();

	let editingId = $state<string | null>(null);
	let editingReason = $state<ManualFallbackReason>('retrieval_insufficient');
	let name = $state('');
	let seller = $state('');
	let price = $state('');
	let currency = $state('');
	let availability = $state('');
	let review = $state('');
	let warranty = $state('');
	let specifications = $state('');
	let validationError = $state<string | null>(null);

	function openEditor(view: ManualCandidateView, correction: boolean) {
		const candidate = view.candidate;
		editingId = candidate.candidate_id;
		editingReason = correction ? 'user_correction' : view.reason ?? 'retrieval_insufficient';
		name = correction ? '' : candidate.product?.name ?? candidate.input_text ?? '';
		seller = correction ? '' : candidate.manual_details?.seller ?? '';
		price = correction ? '' : candidate.manual_details?.price ? String(candidate.manual_details.price.amount) : '';
		currency = correction ? '' : candidate.manual_details?.price?.currency ?? '';
		availability = correction ? '' : candidate.manual_details?.availability ?? '';
		review = correction ? '' : candidate.manual_details?.review ?? '';
		warranty = correction ? '' : candidate.manual_details?.warranty ?? '';
		specifications = correction ? '' : candidate.manual_details?.specifications ?? '';
		validationError = null;
	}

	function save(candidate: UserAddedProduct) {
		const request = manualFallbackRequest(candidate, editingReason, {
			name, seller, price, currency, availability, review, warranty, specifications,
		});
		if (!request) {
			validationError = 'Enter a product name and, if adding a price, a valid amount and three-letter currency.';
			return;
		}
		validationError = null;
		onSave(request);
	}

	const suppliedFacts = (candidate: UserAddedProduct) => [
		['Seller', candidate.manual_details?.seller],
		['Price', candidate.manual_details?.price ? `${candidate.manual_details.price.amount} ${candidate.manual_details.price.currency}` : null],
		['Availability', candidate.manual_details?.availability],
		['Review', candidate.manual_details?.review],
		['Warranty', candidate.manual_details?.warranty],
		['Specifications', candidate.manual_details?.specifications],
	] as const;
</script>

{#if candidates.length}
	<section id="manual-product-fallback" class="mt-8 border-t border-border pt-6" aria-label="Add or correct product details">
		<h2 class="text-base font-[510] text-foreground">Add or correct product details</h2>
		<p class="mt-1 max-w-[720px] text-sm leading-6 text-muted-foreground">If we could not verify a product, you can add what you know. Your details help the comparison, but they are not independently checked.</p>
		{#if error}<p class="mt-4 text-sm text-destructive" role="alert">{error}</p>{/if}
		<div class="mt-5 divide-y divide-border border-y border-border">
			{#each candidates as view (view.candidate.candidate_id)}
				{@const candidate = view.candidate}
				<article class="py-5">
					<p class="break-words text-sm font-[510] text-foreground">{candidate.manual_fallback_reason ? candidate.product?.name ?? view.label : view.label}</p>
					{#if candidate.manual_fallback_reason}
						<p class="mt-1 text-sm text-muted-foreground">Details supplied by you. {view.matchedName ? 'CartCart found a listing, but your details are still unverified.' : 'Product, seller, and purchase terms are not independently verified.'}</p>
						<dl class="mt-3 grid gap-x-5 gap-y-2 text-sm sm:grid-cols-2">
							{#each suppliedFacts(candidate) as [label, value]}
								<div class="flex gap-2"><dt class="text-muted-foreground">{label}:</dt><dd class="text-foreground">{value || 'Unknown'}</dd></div>
							{/each}
						</dl>
					{:else if view.matchedName}
						<p class="mt-1 text-sm text-muted-foreground">CartCart matched this to {view.matchedName}.</p>
					{:else}
						<p class="mt-1 text-sm text-muted-foreground">{view.reason === 'retrieval_unavailable' ? 'We could not read enough from this listing to verify the product.' : 'We could not confirm a product match from the available research.'}</p>
					{/if}
					<div class="mt-3 flex flex-wrap gap-3">
						{#if !view.matchedName}
							<Button type="button" variant="outline" size="sm" disabled={pending} onclick={() => openEditor(view, false)}>{candidate.manual_fallback_reason ? 'Edit your details' : 'Add what you know'}</Button>
						{/if}
						{#if view.matchedName || candidate.manual_fallback_reason}
							<Button type="button" variant="outline" size="sm" disabled={pending} onclick={() => openEditor(view, true)}>Wrong product? Correct it</Button>
						{/if}
					</div>
					{#if editingId === candidate.candidate_id}
						<form class="mt-5 grid max-w-[760px] gap-4 border-l-2 border-iron pl-4 sm:grid-cols-2" onsubmit={(event) => { event.preventDefault(); save(candidate); }}>
							<div class="sm:col-span-2"><label class="text-sm text-foreground" for="manual-name">Product name</label><input id="manual-name" bind:value={name} required maxlength="300" class="mt-2 w-full rounded-md border border-iron bg-steel px-3 py-2 text-sm text-foreground" /></div>
							<div><label class="text-sm text-foreground" for="manual-seller">Seller, if known</label><input id="manual-seller" bind:value={seller} maxlength="200" class="mt-2 w-full rounded-md border border-iron bg-steel px-3 py-2 text-sm text-foreground" /></div>
							<div class="grid grid-cols-[1fr_110px] gap-2"><div><label class="text-sm text-foreground" for="manual-price">Price, if known</label><input id="manual-price" bind:value={price} type="text" inputmode="decimal" placeholder="49.00" class="mt-2 w-full rounded-md border border-iron bg-steel px-3 py-2 text-sm text-foreground" /></div><div><label class="text-sm text-foreground" for="manual-currency">Currency</label><input id="manual-currency" bind:value={currency} maxlength="3" placeholder="USD" class="mt-2 w-full rounded-md border border-iron bg-steel px-3 py-2 text-sm text-foreground" /></div></div>
					<div><label class="text-sm text-foreground" for="manual-availability">Availability, if known</label><input id="manual-availability" bind:value={availability} maxlength="200" class="mt-2 w-full rounded-md border border-iron bg-steel px-3 py-2 text-sm text-foreground" /></div>
					<div><label class="text-sm text-foreground" for="manual-warranty">Warranty, if known</label><input id="manual-warranty" bind:value={warranty} maxlength="500" class="mt-2 w-full rounded-md border border-iron bg-steel px-3 py-2 text-sm text-foreground" /></div>
					<div class="sm:col-span-2"><label class="text-sm text-foreground" for="manual-review">Your review or experience, if any</label><textarea id="manual-review" bind:value={review} maxlength="1000" rows="2" class="mt-2 w-full rounded-md border border-iron bg-steel px-3 py-2 text-sm text-foreground"></textarea></div>
					<div class="sm:col-span-2"><label class="text-sm text-foreground" for="manual-specifications">Specifications you know, if any</label><textarea id="manual-specifications" bind:value={specifications} maxlength="1000" rows="2" class="mt-2 w-full rounded-md border border-iron bg-steel px-3 py-2 text-sm text-foreground"></textarea></div>
					{#if validationError}<p class="text-sm text-destructive sm:col-span-2" role="alert">{validationError}</p>{/if}
					<div class="flex flex-wrap gap-3 sm:col-span-2"><Button type="submit" variant="outline" disabled={pending}>Save and check again</Button><Button type="button" variant="ghost" disabled={pending} onclick={() => (editingId = null)}>Cancel</Button></div>
						</form>
					{/if}
				</article>
			{/each}
		</div>
	</section>
{/if}
