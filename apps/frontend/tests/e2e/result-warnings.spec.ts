import { expect, type Page, test, type TestInfo } from '@playwright/test';
import type { SessionResultsResponse } from '../../src/lib/api/types.js';

const previewWarnings = [
	'Check the desk depth before buying.',
	'Confirm the ports match your laptop.',
	'Compare delivery costs before ordering.',
	'Verify local stock before purchasing.',
];

async function openResult(page: Page, testInfo: TestInfo, revise: (result: SessionResultsResponse) => void) {
	await page.addInitScript(() => {
		window.localStorage.setItem('cartcart.region', JSON.stringify({ status: 'refused' }));
	});
	await page.route('**/api/sessions/*/results', async (route) => {
		const response = await route.fetch();
		const result: SessionResultsResponse = await response.json();
		result.recommendation_bundle.warnings = [];
		result.category_analyses = result.category_analyses.map((analysis) => ({ ...analysis, warnings: [] }));
		result.trust_assessments = result.trust_assessments.map((trust) => ({ ...trust, red_flags: [] }));
		revise(result);
		await testInfo.attach('warning-result-response', { body: Buffer.from(JSON.stringify(result)), contentType: 'application/json' });
		await route.fulfill({ response, json: result });
	});
	await page.goto('/');
	await expect(page.locator('main')).toHaveAttribute('data-client-ready', 'true');
	await page.getByLabel('Shopping question').fill('Which monitor should I buy for coding?');
	await page.getByRole('button', { name: 'Send question', exact: true }).click();
	await page.getByRole('button', { name: 'Skip all', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Refine this decision', exact: true })).toBeVisible();
}

for (const count of [0, 1, 4]) {
	test(`keeps ${count} diagnostic warnings out of advice while preserving source facts`, async ({ page }, testInfo) => {
		await page.setViewportSize({ width: 1280, height: 900 });
		await openResult(page, testInfo, (result) => {
			const categoryEvidence = result.source_evidence[0];
			const trustEvidence = result.source_evidence.find((evidence) => evidence.source_id !== categoryEvidence?.source_id);
			const categorySource = result.source_snapshots.find((source) => source.source_id === categoryEvidence?.source_id);
			const trustSource = result.source_snapshots.find((source) => source.source_id === trustEvidence?.source_id);
			const analysis = result.category_analyses[0];
			const trust = result.trust_assessments[0];
			if (!categorySource || !trustSource || !categoryEvidence || !trustEvidence || !analysis || !trust) {
				throw new Error('The saved monitor result needs category and seller evidence.');
			}
			result.recommendation_bundle.warnings = previewWarnings.slice(0, count);
			result.recommendation_bundle.final_rationale = 'The USB-C hub keeps a laptop desk setup simple.';
			result.recommendation_bundle.mode_results = result.recommendation_bundle.mode_results.map((mode) => ({
				...mode, rationale: 'A USB-C hub and adjustable stand suit a laptop desk.',
				tradeoffs: ['Costs more than a basic monitor.'],
				unknowns: ['Current local stock is not confirmed.'],
			}));
			result.source_snapshots = result.source_snapshots.map((source) => {
				if (source.source_id === categorySource.source_id) return { ...source, url: 'https://example.test/returns?utm_source=cartcart&color=black#policy' };
				if (source.source_id === trustSource.source_id) return { ...source, url: 'https://example.test/seller?ref=affiliate&seller=shop#about', extraction_status: 'partial' };
				return source;
			});
			result.source_evidence = result.source_evidence.map((evidence) => {
				if (evidence.evidence_id === categoryEvidence.evidence_id) return {
					...evidence, claim: 'Returns require the original packaging.', confidence: { level: 'low', score: 0.2 },
				};
				if (evidence.evidence_id === trustEvidence.evidence_id) return { ...evidence, claim: 'The seller has not confirmed the return address or warranty coverage.' };
				return evidence;
			});
			result.category_analyses = [{
				...analysis, warnings: ['Confirm the return address before buying.'],
				evidence_ids: [categoryEvidence.evidence_id], source_ids: [categorySource.source_id],
			}];
			result.trust_assessments = [{
				...trust, red_flags: ['Warranty coverage is not confirmed.'],
				evidence_ids: [trustEvidence.evidence_id], source_ids: [trustSource.source_id],
			}];
		});
		const options = page.getByRole('region', { name: 'Recommended options', exact: true });
		await expect(options.getByRole('heading', { level: 2 }).first()).toBeVisible();
		await expect(options.getByText('A USB-C hub and adjustable stand suit a laptop desk.', { exact: true }).first()).toBeVisible();
		await expect(options.getByText('Costs more than a basic monitor.', { exact: true }).first()).toBeVisible();
		await expect(page.getByRole('region', { name: 'What to watch', exact: true })).toHaveCount(0);
		await expect(page.getByText(/^More warnings/)).toHaveCount(0);
		for (const warning of previewWarnings) await expect(page.getByText(warning, { exact: true })).toHaveCount(0);
		await expect(options.getByText('Current local stock is not confirmed.', { exact: true })).toHaveCount(0);
		await expect(page.getByText('Confirm the return address before buying.', { exact: true })).toHaveCount(0);
		await expect(page.getByText('Warranty coverage is not confirmed.', { exact: true })).toHaveCount(0);
		await expect(page.getByText('Some pages could not be fully read.', { exact: true })).toHaveCount(0);
		await expect(page.getByText('Some source details are uncertain.', { exact: true })).toHaveCount(0);
		await expect(options.getByText(/confidence/)).toHaveCount(0);
		await page.getByRole('button', { name: 'Available sources', exact: true }).click();
		const sources = page.locator('section[aria-labelledby="sources-title"]');
		for (const article of await sources.locator('article').all()) {
			const disclosure = article.locator('summary');
			if (await disclosure.count()) await disclosure.click();
		}
		await expect(sources.getByText('Returns require the original packaging.', { exact: true })).toBeVisible();
		await expect(sources.getByText('The seller has not confirmed the return address or warranty coverage.', { exact: true })).toBeVisible();
		await expect(sources.getByText(/confidence:|quality:|captured/)).toHaveCount(0);
		for (const url of ['https://example.test/returns?color=black', 'https://example.test/seller?seller=shop']) {
			const link = sources.locator(`a[href="${url}"]`).first();
			await expect(link).toHaveAttribute('target', '_blank');
			await expect(link).toHaveAttribute('rel', 'noreferrer noopener');
		}
	});
}
