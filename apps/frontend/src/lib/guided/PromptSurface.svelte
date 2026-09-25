<script lang="ts">
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import { Button } from '$lib/components/ui/button/index.js';
	import { submitTextareaOnEnter } from './textarea-submit.js';

	let {
		question = $bindable(),
		starter,
		pending = false,
		error = null,
		onSubmit,
		onChooseStarter,
	}: {
		question: string;
		starter: string;
		pending?: boolean;
		error?: string | null;
		onSubmit: (question: string) => void;
		onChooseStarter: (starter: string) => void;
	} = $props();
</script>

<div class="surface-enter mx-auto w-full max-w-[1180px]">
	<div class="mx-auto text-center">
		<p class="mb-5 text-xs font-medium tracking-[0.16em] text-muted-foreground uppercase">
			Send your question
		</p>
		<h1 class="text-balance text-[clamp(2.7rem,6.4vw,5.5rem)] leading-[0.98] font-light tracking-[-0.045em] text-foreground">
			What are you looking for?
			<span class="mt-3 block min-h-[1.05em] text-foreground/52">
				{#key starter}
					<button
						type="button"
						class="starter-question rounded-md text-balance transition-colors hover:text-foreground/78 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
						onclick={() => onChooseStarter(starter)}
					>
						{starter}
					</button>
				{/key}
			</span>
		</h1>
	</div>

	<form
		class="mx-auto mt-10 max-w-[780px]"
		aria-label="Question entry"
		onsubmit={(event) => {
			event.preventDefault();
			onSubmit(question);
		}}
	>
		<div class="question-composer group grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 rounded-xl border border-iron bg-card p-3 shadow-[0_18px_70px_rgb(0_0_0/0.28),inset_0_1px_0_rgb(255_255_255/0.025)] transition-colors focus-within:border-slate">
			<label for="shopping-question" class="sr-only">Shopping question</label>
			<textarea
				id="shopping-question"
				bind:value={question}
				rows="1"
				class="max-h-52 min-h-11 resize-none overflow-y-auto bg-transparent px-3 py-2 text-[17px] leading-7 text-foreground outline-none [field-sizing:content] placeholder:text-muted-foreground sm:text-lg"
				placeholder="Ask what you should buy."
				use:submitTextareaOnEnter={{ disabled: !question.trim() || pending, submit: onSubmit }}
			></textarea>
			<Button
				type="submit"
				size="icon"
				aria-label="Send question"
				disabled={!question.trim() || pending}
				class="size-11"
			>
				<ArrowUp class="size-4.5" />
			</Button>
		</div>
		{#if error}
			<p class="mt-4 text-center text-sm text-destructive" role="alert">{error}</p>
		{/if}
	</form>
</div>
