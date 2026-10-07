import { expect, type Page, test, type TestInfo } from '@playwright/test';
import type { SessionResultsResponse } from '../../src/lib/api/types.js';

const previewWarnings = [
	'Check the desk depth before buying.',
	'Confirm the ports match your laptop.',
	'Compare delivery costs before ordering.',
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

test('keeps later warnings and their evidence reachable through a keyboard disclosure', async ({ page }, testInfo) => {
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
		result.recommendation_bundle.warnings = previewWarnings;
		result.source_snapshots = result.source_snapshots.map((source) => {
			if (source.source_id === categorySource.source_id) return { ...source, url: 'https://example.test/returns?utm_source=cartcart&color=black#policy' };
			if (source.source_id === trustSource.source_id) return { ...source, url: 'https://example.test/seller?ref=affiliate&seller=shop#about', extraction_status: 'partial' };
			return source;
		});
		result.source_evidence = result.source_evidence.map((evidence) => {
			if (evidence.evidence_id === categoryEvidence.evidence_id) return { ...evidence, claim: 'Returns require the original packaging.' };
			if (evidence.evidence_id === trustEvidence.evidence_id) return { ...evidence, claim: 'The seller has not confirmed the return address or warranty coverage.' };
			return evidence;
		});
		result.category_analyses = [{
			...analysis, warnings: ['Confirm the return address before buying.'],
			evidence_ids: [categoryEvidence.evidence_id], source_ids: [categorySource.source_id],
		}];
		result.trust_assessments = [{
			...trust, red_flags: ['Confirm the return address before buying.', 'Warranty coverage is not confirmed.'],
			evidence_ids: [trustEvidence.evidence_id], source_ids: [trustSource.source_id],
		}];
	});
	const cautions = page.getByRole('region', { name: 'What to watch', exact: true });
	await expect(cautions).toBeVisible();
	for (const warning of previewWarnings) await expect(cautions.getByText(warning, { exact: true })).toBeVisible();
	await expect(cautions.getByText('Some sources could not be fully checked, so the comparison is based on the usable evidence.', { exact: true })).toBeVisible();
	await expect(cautions.getByText('Confirm the return address before buying.', { exact: true })).not.toBeVisible();
	await expect(cautions.getByText('Warranty coverage is not confirmed.', { exact: true })).not.toBeVisible();
	await cautions.scrollIntoViewIfNeeded();
	await testInfo.attach('warnings-preview', { body: await cautions.screenshot(), contentType: 'image/png' });
	const more = cautions.locator('summary').filter({ hasText: 'More warnings (2)' });
	await expect(more).toBeVisible();
	await more.focus();
	await page.keyboard.press('Enter');
	await expect(cautions.getByText('Confirm the return address before buying.', { exact: true })).toBeVisible();
	await expect(cautions.getByText('Warranty coverage is not confirmed.', { exact: true })).toBeVisible();
	await expect(cautions.locator('p').filter({ hasText: /^(Check the desk depth|Confirm the ports|Compare delivery costs|Confirm the return address|Warranty coverage)/ })).toHaveText([
		'Check the desk depth before buying.', 'Confirm the ports match your laptop.',
		'Compare delivery costs before ordering.', 'Confirm the return address before buying.',
		'Warranty coverage is not confirmed.',
	]);
	const returnWarning = cautions.getByText('Confirm the return address before buying.', { exact: true }).locator('..');
	await returnWarning.locator('summary').click();
	await expect(returnWarning.getByText('Returns require the original packaging.', { exact: true })).toBeVisible();
	await expect(returnWarning.getByText('The seller has not confirmed the return address or warranty coverage.', { exact: true })).toBeVisible();
	await expect(returnWarning.getByText('2 claims', { exact: true })).toBeVisible();
	const warrantyWarning = cautions.getByText('Warranty coverage is not confirmed.', { exact: true }).locator('..');
	await warrantyWarning.locator('summary').click();
	await expect(warrantyWarning.getByText('The seller has not confirmed the return address or warranty coverage.', { exact: true })).toBeVisible();
	await expect(warrantyWarning.getByText('1 claim', { exact: true })).toBeVisible();
	for (const warning of [returnWarning, warrantyWarning]) {
		const links = warning.getByRole('link');
		for (const link of await links.all()) {
			await expect(link).toHaveAttribute('href', /^https:\/\/example\.test\/(returns\?color=black|seller\?seller=shop)$/);
			await expect(link).toHaveAttribute('target', '_blank');
			await expect(link).toHaveAttribute('rel', 'noreferrer noopener');
		}
	}
	await expect(returnWarning.getByRole('link', { name: 'Open source', exact: true })).toHaveCount(2);
	await expect(warrantyWarning.getByRole('link', { name: 'Open source', exact: true })).toHaveCount(1);
	await page.setViewportSize({ width: 1280, height: 2600 });
	await page.evaluate(() => window.scrollTo(0, 0));
	await testInfo.attach('warnings-expanded', { body: await cautions.screenshot(), contentType: 'image/png' });
	await more.focus();
	await page.keyboard.press('Space');
	await expect(cautions.getByText('Confirm the return address before buying.', { exact: true })).not.toBeVisible();
	await expect(cautions.getByText('Warranty coverage is not confirmed.', { exact: true })).not.toBeVisible();
	await expect(more).toBeFocused();
	for (const warning of previewWarnings) await expect(cautions.getByText(warning, { exact: true })).toBeVisible();
});

for (const count of [0, 1, 3]) {
	test(`keeps a result with ${count} warnings free of an extra disclosure`, async ({ page }, testInfo) => {
		await openResult(page, testInfo, (result) => {
			result.recommendation_bundle.warnings = previewWarnings.slice(0, count);
			result.source_snapshots = result.source_snapshots.map((source) => ({ ...source, extraction_status: 'succeeded' }));
			result.source_evidence = result.source_evidence.map((evidence) => ({
				...evidence,
				evidence_type: 'product_spec',
				claim: 'The monitor has the stated ports.',
				confidence: { level: 'high', score: 0.9 },
			}));
		});
		await expect(page.getByRole('heading', { name: 'Here is the clear pick.', exact: true })).toBeVisible();
		const cautions = page.getByRole('region', { name: 'What to watch', exact: true });
		if (count === 0) {
			await expect(cautions).toHaveCount(0);
		} else {
			await expect(cautions).toBeVisible();
			for (const warning of previewWarnings.slice(0, count)) await expect(cautions.getByText(warning, { exact: true })).toBeVisible();
		}
		await expect(page.getByText(/^More warnings/)).toHaveCount(0);
	});
}

test('shows a partial-source caution without inventing a warning disclosure', async ({ page }, testInfo) => {
	await openResult(page, testInfo, (result) => {
		result.source_snapshots = result.source_snapshots.map((source) => ({ ...source, extraction_status: 'partial' }));
		result.source_evidence = result.source_evidence.map((evidence) => ({
			...evidence, evidence_type: 'product_spec', claim: 'The monitor has the stated ports.',
			confidence: { level: 'high', score: 0.9 },
		}));
	});
	const cautions = page.getByRole('region', { name: 'What to watch', exact: true });
	await expect(cautions.getByText('Some sources could not be fully checked, so the comparison is based on the usable evidence.', { exact: true })).toBeVisible();
	await expect(cautions.getByText(/^More warnings/)).toHaveCount(0);
});
