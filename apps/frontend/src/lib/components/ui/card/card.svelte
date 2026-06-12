<script lang="ts">
	import { cn } from '$lib/utils.js';
	import type { HTMLAttributes } from 'svelte/elements';

	let { class: className, children, ...restProps }: HTMLAttributes<HTMLDivElement> = $props();
</script>

<div
	data-slot="card"
	class={cn('rounded-xl bg-card text-card-foreground shadow-subtle', className)}
	{...restProps}
>
	{@render children?.()}
</div>
