<script lang="ts">
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Check from '@lucide/svelte/icons/check';
	import { Button } from '$lib/components/ui/button/index.js';
	import type { CurrentGuidedQuestion, GuidedIntakeState } from '$lib/api/types.js';
	import type { GuidedAnswerSurfaceView, GuidedDraft } from './guided-state.js';
	import { submitTextareaOnEnter } from './textarea-submit.js';

	let {
		question,
		guide,
		draft = $bindable(),
		surface,
		canContinue,
		pending = false,
		error = null,
		onContinue,
		onBack,
		onSkip,
		onSkipAll,
		onSelectChoice,
		onSelectCustom,
	}: {
		question: CurrentGuidedQuestion;
		guide: GuidedIntakeState;
		draft: GuidedDraft;
		surface: GuidedAnswerSurfaceView;
		canContinue: boolean;
		pending?: boolean;
		error?: string | null;
		onContinue: () => void;
		onBack: () => void;
		onSkip: () => void;
		onSkipAll: () => void;
		onSelectChoice: (choiceId: string) => void;
		onSelectCustom: () => void;
	} = $props();
</script>

<div class="surface-enter mx-auto w-full max-w-[1180px]">
	<div class="mx-auto text-center">
		<h1 class="text-balance text-[clamp(2.55rem,5.5vw,5rem)] leading-[1.02] font-light tracking-[-0.042em] text-foreground">
			{question.text}
		</h1>
	</div>

	<form
		class="mx-auto mt-10 max-w-[780px]"
		aria-label="Guided answer"
		onsubmit={(event) => {
			event.preventDefault();
			onContinue();
		}}
	>
		{#if surface === 'textbox'}
			<div class="guided-composer grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 rounded-xl border border-iron bg-card p-3 shadow-[0_18px_70px_rgb(0_0_0/0.28),inset_0_1px_0_rgb(255_255_255/0.025)] transition-colors focus-within:border-slate">
				<label for="guided-answer" class="sr-only">Your answer</label>
				<textarea
					id="guided-answer"
					bind:value={draft.text}
					rows="1"
					class="max-h-52 min-h-11 resize-none overflow-y-auto bg-transparent px-3 py-2 text-[17px] leading-7 text-foreground outline-none [field-sizing:content] placeholder:text-muted-foreground sm:text-lg"
					placeholder="Type your answer."
					use:submitTextareaOnEnter={{
						disabled: !canContinue || pending,
						submit: () => onContinue(),
					}}
				></textarea>
				<Button type="submit" disabled={!canContinue || pending} class="h-11 px-4">
					Continue <ArrowRight />
				</Button>
			</div>
		{:else}
			<div class="mx-auto grid max-w-[720px] gap-3 sm:grid-cols-2" role="group" aria-label="Answer choices">
				{#each question.inline_choice?.options ?? [] as option}
					<button
						type="button"
						class={`group relative min-h-24 rounded-xl border p-5 text-left shadow-subtle transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none ${
							draft.choiceId === option.choice_id && !draft.isCustomAnswer
								? 'border-mist bg-secondary text-foreground'
								: 'border-border bg-card text-muted-foreground hover:border-iron hover:text-foreground'
						}`}
						onclick={() => onSelectChoice(option.choice_id)}
						disabled={pending}
						aria-pressed={draft.choiceId === option.choice_id && !draft.isCustomAnswer}
					>
						<span class="flex items-center justify-between gap-3">
							<span class="text-[15px] font-[510] text-foreground">{option.label}</span>
							<span class={`flex size-5 items-center justify-center rounded-full border ${draft.choiceId === option.choice_id && !draft.isCustomAnswer ? 'border-mist bg-foreground text-background' : 'border-iron text-transparent'}`} aria-hidden="true">
								<Check class="size-3" />
							</span>
						</span>
						{#if option.description}
							<span class="mt-2 block text-sm leading-6">{option.description}</span>
						{/if}
					</button>
				{/each}
			</div>

			{#if surface === 'two_option_plus_text'}
				<div class="mx-auto mt-3 max-w-[720px]">
					<button
						type="button"
						class={`w-full rounded-md border px-4 py-3 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none ${draft.isCustomAnswer ? 'border-mist bg-secondary text-foreground' : 'border-border bg-card text-muted-foreground hover:border-iron hover:text-foreground'}`}
						onclick={onSelectCustom}
						disabled={pending}
						aria-pressed={draft.isCustomAnswer}
					>
						{question.inline_choice?.custom_answer_label ?? 'Type my answer'}
					</button>
					{#if draft.isCustomAnswer}
						<div class="mt-3 rounded-xl border border-iron bg-card p-3 shadow-subtle focus-within:border-slate">
							<label for="guided-custom-answer" class="sr-only">Your answer</label>
							<textarea
								id="guided-custom-answer"
								bind:value={draft.text}
								rows="1"
								class="max-h-52 min-h-11 w-full resize-none overflow-y-auto bg-transparent px-3 py-2 text-[17px] leading-7 text-foreground outline-none [field-sizing:content] placeholder:text-muted-foreground"
								placeholder="Type your answer."
								use:submitTextareaOnEnter={{
									disabled: !canContinue || pending,
									submit: () => onContinue(),
								}}
							></textarea>
						</div>
					{/if}
				</div>
			{/if}

			<div class="mt-5 flex justify-center">
				<Button type="submit" disabled={!canContinue || pending} class="h-11 px-5">
					Continue <ArrowRight />
				</Button>
			</div>
		{/if}

		<p class="sr-only" aria-live="polite">{pending ? 'Saving your answer' : ''}</p>
		{#if error}
			<p class="mt-4 text-center text-sm text-destructive" role="alert">{error}</p>
		{/if}

		<div class="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border/80 pt-4">
			<Button type="button" variant="outline" onclick={onBack} disabled={pending}>
				<ArrowLeft /> Back
			</Button>
			<div class="flex flex-wrap items-center justify-end gap-2">
				{#if guide.skippable_question.can_skip}
					<Button type="button" variant="outline" onclick={onSkip} disabled={pending}>Skip</Button>
				{/if}
				{#if guide.analysis_start.can_skip_all_and_start_analysis}
					<Button type="button" variant="outline" onclick={onSkipAll} disabled={pending}>Skip all</Button>
				{/if}
			</div>
		</div>
	</form>
</div>
