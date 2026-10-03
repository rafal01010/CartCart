<script lang="ts">
	import { Button } from '$lib/components/ui/button/index.js';
	import { REGION_OPTIONS } from '$lib/session/session-form.js';
	import { submitTextareaOnEnter } from '$lib/guided/textarea-submit.js';
	import { refinementPromptCanContinue, refinementPromptSpec, type RefinementPromptDraft, type RefinementPromptKind } from './contextual-refinement-prompt.js';

	let { draft = $bindable(), error = null, onChoose, onSubmit, onBack }: {
		draft: RefinementPromptDraft | null;
		error?: string | null;
		onChoose: (kind: RefinementPromptKind) => void;
		onSubmit: () => void;
		onBack: () => void;
	} = $props();
	const spec = $derived(draft ? refinementPromptSpec(draft.kind) : null);
</script>

<div class="surface-enter mx-auto w-full max-w-[1180px]">
	<h1 class="text-center text-balance text-[clamp(2.55rem,5.5vw,5rem)] leading-[1.02] font-light tracking-[-0.042em]">{spec?.question ?? 'What would you like to change?'}</h1>
	<div class="mx-auto mt-10 max-w-[780px]">
		{#if draft && spec}
			<form aria-label="Refine decision" onsubmit={(event) => { event.preventDefault(); onSubmit(); }}>
				{#if spec.usesRegionChoice}
					<label for="refinement-region" class="sr-only">Country or region</label>
					<select id="refinement-region" bind:value={draft.regionCode} class="w-full rounded-md border border-iron bg-card p-4 text-foreground">
						{#each REGION_OPTIONS as region}<option value={region.code}>{region.label}</option>{/each}
					</select>
				{:else}
					<div class="guided-composer rounded-xl border border-iron bg-card p-3 focus-within:border-slate">
						<label for="refinement-answer" class="sr-only">Your answer</label>
						<textarea id="refinement-answer" bind:value={draft.text} rows="2" maxlength={draft.kind === 'category' ? 120 : 800} placeholder={spec.placeholder} class="w-full resize-none bg-transparent px-3 py-2 text-lg outline-none placeholder:text-muted-foreground" use:submitTextareaOnEnter={{ disabled: !refinementPromptCanContinue(draft), submit: onSubmit }}></textarea>
					</div>
				{/if}
				{#if draft.kind === 'budget'}
					<div class="mt-4 flex flex-wrap gap-4">
						<label class="text-sm text-muted-foreground">Currency <input aria-label="Currency" bind:value={draft.currency} maxlength="3" class="ml-2 w-20 rounded-md border border-border bg-card p-2 text-foreground" /></label>
						<label class="text-sm text-muted-foreground">Budget limit <select aria-label="Budget limit" bind:value={draft.budgetMode} class="ml-2 rounded-md border border-border bg-card p-2 text-foreground"><option value="preferred">Aim near this</option><option value="hard_cap">Do not go over</option></select></label>
					</div>
				{/if}
				<div class="mt-5 flex justify-center"><Button type="submit" disabled={!refinementPromptCanContinue(draft)}>Update decision</Button></div>
			</form>
		{:else}
			<div class="grid gap-3 sm:grid-cols-2" role="group" aria-label="What to change">
				{#each [{ kind: 'budget', label: 'Budget' }, { kind: 'region', label: 'Buying region' }, { kind: 'category', label: 'Kind of product' }, { kind: 'preferences', label: 'What matters most' }] as option}
					<Button variant="outline" class="min-h-20" onclick={() => onChoose(option.kind as RefinementPromptKind)}>{option.label}</Button>
				{/each}
			</div>
		{/if}
		{#if error}<p class="mt-4 text-center text-sm text-destructive" role="alert">{error}</p>{/if}
		<div class="mt-6 border-t border-border pt-4"><Button variant="outline" onclick={onBack}>Back</Button></div>
	</div>
</div>
