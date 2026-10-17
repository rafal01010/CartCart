import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

function record(path: string) {
	const value: unknown = JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
	if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('Expected a fixture object.');
	return value;
}

const saved = record('../../../../data/artifacts/task221/resume-20261017/phone-attempt4-result-api.json');
const session = record('../../../../data/artifacts/task221/resume-20261017/phone-attempt4-session-api.json');
const run = record('../../../../data/artifacts/task221/resume-20261017/phone-attempt4-run-api.json');
const projection = record('../../../../data/artifacts/task225/saved-replay-selection.json');
if (!('selected_source_ids' in projection) || !Array.isArray(projection.selected_source_ids)) throw new Error('Missing selected source IDs.');
const selectedCount = projection.selected_source_ids.length;
if (!('deferred_source_ids' in projection) || !Array.isArray(projection.deferred_source_ids)) throw new Error('Missing deferred source IDs.');
const result = { ...saved, decision_sources: projection };
const sessionId = '2e2555cb-0d14-42d1-9efa-934d7fa3b216';
const runId = '37da9a8b-1641-456c-94b4-bcd652c03346';

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
	test(`Task225 selected saved sources at ${viewport.width}px`, async ({ page }, testInfo) => {
		await page.setViewportSize(viewport);
		const methods: string[] = [];
		await page.route('**/api/sessions/**', async (route) => {
			const request = route.request();
			methods.push(request.method());
			const path = new URL(request.url()).pathname;
			if (request.method() === 'GET' && path === `/api/sessions/${sessionId}`) return route.fulfill({ json: session });
			if (request.method() === 'GET' && path === `/api/sessions/${sessionId}/runs/${runId}`) return route.fulfill({ json: run });
			if (request.method() === 'GET' && path === `/api/sessions/${sessionId}/results`) return route.fulfill({ json: result });
			return route.fulfill({ status: 409, json: { error: { code: 'unexpected_offline_request', message: 'Unexpected offline request.' } } });
		});
		await page.goto(`/?session=${sessionId}&run=${runId}`);
		const toggle = page.getByRole('button', { name: 'Available sources', exact: true });
		await expect(toggle).toHaveAttribute('aria-expanded', 'false');
		await toggle.click();
		const sources = page.getByRole('region', { name: 'Available sources', exact: true });
		await expect(sources.locator(':scope > div > article')).toHaveCount(selectedCount);
		await expect(sources.getByText('Page excerpts', { exact: true }).first()).toBeVisible();
		await expect(sources.getByText('Caption excerpts available', { exact: true })).toBeVisible();
		await expect(sources.getByText('Video information only', { exact: true })).toHaveCount(0);
		const speech = sources.locator('article').filter({ hasText: 'Caption excerpts available' });
		await speech.getByText('Evidence from this source', { exact: true }).click();
		await expect(speech.getByRole('link', { name: 'Watch at 4:09-4:14', exact: true })).toHaveAttribute('href', 'https://www.youtube.com/watch?v=e9WGaciZgsc&t=249s');
		expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
		expect([...new Set(methods)]).toEqual(['GET']);
		await page.screenshot({ path: testInfo.outputPath(`saved-selected-${viewport.width}.png`), fullPage: true });
	});
}
