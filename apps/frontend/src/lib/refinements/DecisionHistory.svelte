<script lang="ts">
	import { Button } from '$lib/components/ui/button/index.js';
	import type { DecisionHistoryResponse } from '$lib/api/types.js';
	import { decisionContext } from './decision-history.js';
	let { history, selectedId, pending, error, onSelect, onReload }: {
		history: DecisionHistoryResponse | null;
		selectedId: string | null;
		pending: boolean;
		error: string | null;
		onSelect: (id: string) => void;
		onReload: () => void;
	} = $props();
</script>

<details class="mt-6 border-y border-border py-4" aria-label="Decision history">
	<summary class="cursor-pointer text-sm text-muted-foreground">Decision history</summary>
	{#if error}<p class="mt-4 text-sm text-destructive" role="alert">{error}</p><Button variant="outline" disabled={pending} onclick={onReload}>Try loading history again</Button>{/if}
	{#if history}
		<p class="mt-4 text-sm text-muted-foreground">Original question: {history.original_query}</p>
		<ol class="mt-4 divide-y divide-border">
			{#each history.versions as entry, index}
				<li class="flex flex-wrap items-start justify-between gap-4 py-4">
					<div class="min-w-0 flex-1"><p class="text-sm font-[510]">{index === 0 ? 'Original decision' : `Decision ${entry.version}`}{index === history.versions.length - 1 ? ' · Latest' : ''}</p><p class="mt-1 text-sm text-muted-foreground">{entry.change ?? 'Your starting shopping details.'}</p><p class="mt-1 text-xs leading-5 text-muted-foreground">{decisionContext(entry.brief)}</p></div>
					<Button variant="outline" disabled={pending || selectedId === entry.result_version_id} onclick={() => onSelect(entry.result_version_id)}>{selectedId === entry.result_version_id ? 'Viewing' : index === 0 ? 'View original decision' : `View decision ${entry.version}`}</Button>
				</li>
			{/each}
		</ol>
	{/if}
</details>
