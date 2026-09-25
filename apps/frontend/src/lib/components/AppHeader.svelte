<script lang="ts">
	import MapPin from '@lucide/svelte/icons/map-pin';
	import SearchCheck from '@lucide/svelte/icons/search-check';

	let {
		regionLabel,
		onRegionClick,
		onHome,
	}: {
		regionLabel: string;
		onRegionClick: () => void;
		onHome: () => void;
	} = $props();
</script>

<header class="sticky top-0 z-30 border-b border-border/70 bg-background/95 backdrop-blur-md">
	<div class="mx-auto flex h-16 w-full max-w-[1440px] items-center justify-between px-4 sm:px-8 lg:px-10">
		<button
			type="button"
			class="group flex items-center gap-2.5 rounded-md text-sm font-[590] tracking-[-0.01em] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
			onclick={onHome}
			aria-label="CartCart home"
		>
			<span
				class="flex size-7 items-center justify-center rounded-md border border-border bg-card shadow-subtle transition-colors group-hover:border-iron"
				aria-hidden="true"
			>
				<SearchCheck class="size-3.5 text-accent" />
			</span>
			<span>CartCart</span>
		</button>

		<button
			type="button"
			class="inline-flex h-9 max-w-[12rem] items-center gap-2 rounded-md border border-border bg-card/70 px-3 text-xs text-muted-foreground shadow-subtle transition-colors hover:border-iron hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:outline-none sm:max-w-none sm:text-sm"
			onclick={onRegionClick}
			aria-label={`Buying region: ${regionLabel}. Change region`}
		>
			<MapPin class="size-3.5 shrink-0 text-muted-foreground" />
			<span class="truncate">{regionLabel}</span>
		</button>
	</div>
</header>
