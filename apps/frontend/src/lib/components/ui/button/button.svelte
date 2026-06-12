<script lang="ts" module>
	import { cn } from '$lib/utils.js';
	import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements';
	import { type VariantProps, tv } from 'tailwind-variants';

	export const buttonVariants = tv({
		base: "group/button inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-md border border-transparent bg-clip-padding text-sm font-medium tracking-normal shadow-button transition-colors outline-none select-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-45 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
		variants: {
			variant: {
				default: 'bg-primary text-primary-foreground hover:bg-primary/90',
				outline:
					'border-border bg-transparent text-foreground shadow-none hover:border-muted-foreground hover:bg-secondary',
				secondary: 'border-border bg-secondary text-secondary-foreground hover:bg-card',
				ghost: 'bg-transparent text-muted-foreground shadow-none hover:text-foreground',
				link: 'bg-transparent text-accent shadow-none underline-offset-4 hover:underline'
			},
			size: {
				default: 'h-9 gap-1.5 px-4',
				sm: 'h-8 gap-1 px-3 text-xs',
				lg: 'h-10 gap-1.5 px-5',
				icon: 'size-10',
				'icon-sm': 'size-8'
			}
		},
		defaultVariants: {
			variant: 'default',
			size: 'default'
		}
	});

	export type ButtonVariant = VariantProps<typeof buttonVariants>['variant'];
	export type ButtonSize = VariantProps<typeof buttonVariants>['size'];
	type ButtonElement = HTMLButtonElement | HTMLAnchorElement;
	export type ButtonProps = Omit<HTMLButtonAttributes, 'ref'> &
		Omit<HTMLAnchorAttributes, 'ref'> & {
			ref?: ButtonElement | null;
			variant?: ButtonVariant;
			size?: ButtonSize;
		};
</script>

<script lang="ts">
	let {
		class: className,
		variant = 'default',
		size = 'default',
		ref = $bindable(null),
		href = undefined,
		type = 'button',
		disabled,
		children,
		...restProps
	}: ButtonProps = $props();
</script>

{#if href}
	<a
		bind:this={ref}
		data-slot="button"
		class={cn(buttonVariants({ variant, size }), className)}
		href={disabled ? undefined : href}
		aria-disabled={disabled}
		role={disabled ? 'link' : undefined}
		tabindex={disabled ? -1 : undefined}
		{...restProps}
	>
		{@render children?.()}
	</a>
{:else}
	<button
		bind:this={ref}
		data-slot="button"
		class={cn(buttonVariants({ variant, size }), className)}
		{type}
		{disabled}
		{...restProps}
	>
		{@render children?.()}
	</button>
{/if}
