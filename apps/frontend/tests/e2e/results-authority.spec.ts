import { expect, test } from '@playwright/test';
import type { SessionResultsResponse } from '../../src/lib/api/types.js';

for (const variant of ['no modes', 'alternate only', 'product only', 'no strong buy'] as const) {
	test(`preserves the saved decision with ${variant}`, async ({ page }) => {
		await page.addInitScript(() => {
			window.localStorage.setItem('cartcart.region', JSON.stringify({ status: 'refused' }));
		});
		let saved: SessionResultsResponse | undefined;
		await page.route('**/api/sessions/*/results', async (route) => {
			const response = await route.fetch();
			const result: SessionResultsResponse = await response.json();
			const bundle = result.recommendation_bundle;
			if (variant === 'alternate only') {
				bundle.mode_results = bundle.mode_results.filter((mode) => mode.mode === 'best_value');
			} else {
				bundle.mode_results = [];
			}
			if (variant === 'product only') bundle.final_listing_id = null;
			if (variant === 'no strong buy') {
				bundle.final_product_id = null;
				bundle.final_listing_id = null;
				bundle.final_rationale = null;
				bundle.no_strong_buy = true;
				bundle.no_strong_buy_reason = 'The available evidence does not support a strong buy.';
			}
			saved = result;
			await route.fulfill({ response, json: result });
		});
		await page.goto('/');
		await expect(page.locator('main')).toHaveAttribute('data-client-ready', 'true');
		await page.getByLabel('Shopping question').fill('Which monitor should I buy for coding?');
		await page.getByRole('button', { name: 'Send question', exact: true }).click();
		await page.getByRole('button', { name: 'Skip all', exact: true }).click();
		await expect(page.getByRole('button', { name: 'Refine this decision', exact: true })).toBeVisible();
		if (!saved) throw new Error('The saved fixture result was not loaded.');
		const summary = page.getByRole('region', { name: 'Recommendation summary', exact: true });
		if (variant === 'no strong buy') {
			await expect(page.getByRole('heading', { name: 'None are strong buys yet.' })).toBeVisible();
			await expect(summary.getByRole('heading', { level: 2 })).toHaveCount(0);
			await expect(page.getByRole('tab')).toHaveCount(0);
		} else {
			const final = saved.products.find((item) => item.product_id === saved?.recommendation_bundle.final_product_id);
			if (!final) throw new Error('The fixture final product is missing.');
			await expect(summary.getByRole('heading', { level: 2, name: final.name, exact: true })).toBeVisible();
			await expect(summary).toContainText('Dell UltraSharp U2724DE is the best pick because it balances monitor fit, USB-C convenience, evidence quality, and a trustworthy official listing.');
			if (variant === 'product only') {
				await expect(summary.getByRole('link', { name: 'View listing' })).toHaveCount(0);
				await expect(summary).toContainText('Seller details unavailable');
			} else {
				const listing = saved.listings.find((item) => item.listing_id === saved?.recommendation_bundle.final_listing_id);
				if (!listing) throw new Error('The fixture final listing is missing.');
				await expect(summary).toContainText(listing.seller.seller_name);
				await expect(summary.getByRole('link', { name: 'View listing' })).toHaveAttribute('href', listing.canonical_url ?? listing.url);
			}
			if (variant === 'alternate only') {
				const mode = saved.recommendation_bundle.mode_results[0];
				const alternate = saved.products.find((item) => item.product_id === mode?.product_id);
				if (!alternate) throw new Error('The fixture alternate product is missing.');
				await page.getByRole('tab', { name: 'Best value', exact: true }).click();
				await expect(summary.getByRole('heading', { level: 2, name: alternate.name, exact: true })).toBeVisible();
				await page.getByRole('tab', { name: 'Best overall', exact: true }).click();
				await expect(summary.getByRole('heading', { level: 2, name: final.name, exact: true })).toBeVisible();
			}
		}
		await page.getByRole('button', { name: 'Supporting details', exact: true }).click();
		const runners = page.locator('section[aria-labelledby="runner-ups-title"]');
		for (const id of saved.recommendation_bundle.runner_up_product_ids) {
			const product = saved.products.find((item) => item.product_id === id);
			if (!product) throw new Error('A saved fixture runner-up is missing.');
			await expect(runners).toContainText(product.name);
		}
	});
}
