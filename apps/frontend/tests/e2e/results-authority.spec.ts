import { expect, test } from '@playwright/test';
import type { SessionResultsResponse } from '../../src/lib/api/types.js';

for (const variant of ['no modes', 'alternate only', 'product only', 'no strong buy', 'rowless runner-ups', 'uncited', 'no final'] as const) {
	test(`preserves the saved decision with ${variant}`, async ({ page }) => {
		await page.addInitScript(() => {
			window.localStorage.setItem('cartcart.region', JSON.stringify({ status: 'refused' }));
		});
		let saved: SessionResultsResponse | undefined;
		await page.route('**/api/sessions/*/results', async (route) => {
			const response = await route.fetch();
			const result: SessionResultsResponse = await response.json();
			const bundle = result.recommendation_bundle;
			if (variant === 'alternate only' || variant === 'no final' || variant === 'uncited') {
				bundle.mode_results = bundle.mode_results.filter((mode) => mode.mode === 'best_value');
			} else {
				bundle.mode_results = [];
			}
			if (variant === 'product only') bundle.final_listing_id = null;
		if (variant === 'no final') { bundle.final_product_id = null; bundle.final_listing_id = null; }
		if (variant === 'uncited') {
			result.source_evidence = []; result.source_snapshots = []; result.source_results = [];
			bundle.evidence_ids = []; bundle.source_ids = [];
			bundle.mode_results = bundle.mode_results.map((mode) => ({ ...mode, evidence_ids: [], source_ids: [] }));
		}
			if (variant === 'rowless runner-ups') {
				const runnerIds = new Set(bundle.runner_up_product_ids);
				bundle.comparison_matrix.rows = bundle.comparison_matrix.rows.filter((row) => !runnerIds.has(row.product_id));
				result.comparison_matrix.rows = bundle.comparison_matrix.rows;
			}
			if (variant === 'no strong buy') {
				bundle.final_product_id = null;
				bundle.final_listing_id = null;
				bundle.final_rationale = null;
				bundle.no_strong_buy = true;
				bundle.primary_product_ids = [];
			bundle.runner_up_product_ids = [];
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
		await expect(page.getByRole('button', { name: 'Ask another question', exact: true })).toBeVisible();
		if (!saved) throw new Error('The saved fixture result was not loaded.');
		const options = page.getByRole('region', { name: 'Recommended options', exact: true });
		if (variant === 'no strong buy') {
			await expect(page.getByRole('heading', { name: 'No suitable option to suggest yet.' })).toBeVisible();
			await expect(options.getByRole('heading', { level: 2 })).toHaveCount(0);
		} else {
			if (variant !== 'no final') {
				const final = saved.products.find((item) => item.product_id === saved?.recommendation_bundle.final_product_id);
				if (!final) throw new Error('The fixture final product is missing.');
				await expect(options.getByRole('heading', { level: 2, name: final.name, exact: true })).toBeVisible();
				const card = options.locator('article').filter({ has: page.getByRole('heading', { level: 2, name: final.name, exact: true }) });
				if (variant === 'product only') {
					await expect(card.getByRole('link', { name: 'View listing' })).toHaveCount(0);
					await expect(card).not.toContainText('Check the current price, availability and seller before buying.');
					if (saved.recommendation_bundle.final_rationale) await expect(page.locator('main')).toContainText(saved.recommendation_bundle.final_rationale);
				} else {
					const listing = saved.listings.find((item) => item.listing_id === saved?.recommendation_bundle.final_listing_id);
					if (listing) await expect(card).toContainText(listing.seller.seller_name);
				}
			}
			const primaryIds = saved.recommendation_bundle.primary_product_ids
				?? [saved.recommendation_bundle.final_product_id].filter((id): id is string => id !== null && id !== undefined);
			await expect(options.getByRole('heading', { level: 2 })).toHaveCount(primaryIds.length);
			for (const id of primaryIds) {
				const product = saved.products.find((item) => item.product_id === id);
				if (!product) throw new Error('A saved primary product is missing.');
				await expect(options.getByRole('heading', { level: 2, name: product.name, exact: true })).toBeVisible();
			}
			const runners = page.getByRole('region', { name: 'Runners-up', exact: true });
			await expect(runners.getByRole('heading', { level: 3 })).toHaveCount(saved.recommendation_bundle.runner_up_product_ids.length);
			for (const id of saved.recommendation_bundle.runner_up_product_ids) {
				const product = saved.products.find((item) => item.product_id === id);
				if (!product) throw new Error('A saved runner-up product is missing.');
				await expect(runners.getByRole('heading', { level: 3, name: product.name, exact: true })).toBeVisible();
			}

		}
	});
}
