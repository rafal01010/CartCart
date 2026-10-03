import type { ShoppingBrief } from '$lib/api/types.js';

export function decisionContext(brief: ShoppingBrief): string {
	const context: string[] = [];
	if (brief.category) context.push(brief.category);
	const region = brief.region?.region;
	if (region) {
		const label = new Intl.DisplayNames(['en'], { type: 'region' }).of(region.country_code);
		context.push(`${label ?? region.country_code}${brief.region?.source === 'user_provided' ? '' : ' (assumed region)'}`);
	}
	if (brief.budget) {
		context.push(`${brief.budget.amount.currency} ${brief.budget.amount.amount}${brief.budget.mode === 'hard_cap' ? ' maximum' : ' preferred'}`);
	}
	context.push(...brief.constraints.map((item) => item.text), ...brief.preferences.map((item) => item.text));
	return context.join(' · ') || brief.original_query;
}
