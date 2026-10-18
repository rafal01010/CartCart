import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

function isObject(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function object(value: unknown): Record<string, unknown> {
	if (!isObject(value)) throw new Error('Expected an object.');
	return value;
}

function string(value: unknown): string {
	if (typeof value !== 'string') throw new Error('Expected a string.');
	return value;
}

function strings(value: unknown): string[] {
	if (!Array.isArray(value)) throw new Error('Expected names.');
	return value.map(string);
}

const fixture: unknown = JSON.parse(readFileSync(new URL('../../../../data/artifacts/task226/browser-cases.json', import.meta.url), 'utf8'));
if (!Array.isArray(fixture) || fixture.length < 3) throw new Error('Expected exported SQLite/API option controls.');
const cases = fixture.map((value: unknown) => {
	const row = object(value);
	const session = object(row.session);
	const run = object(row.run);
	const result = object(row.result);
	const projection = object(result.decision_sources);
	const packets = projection.sources;
	if (!Array.isArray(packets) || packets.length === 0) throw new Error('Expected selected source packets.');
	if (!Array.isArray(row.candidate_advice)) throw new Error('Expected candidate advice.');
	return {
		id: string(row.case_id), result, session, run,
		sessionId: string(session.session_id), runId: string(run.run_id),
		sourceUrls: packets.map((value: unknown) => string(object(value).url)),
		primaries: strings(row.primary_names), runners: strings(row.runner_names), rationale: string(row.rationale),
		advice: row.candidate_advice.map((value: unknown) => {
			const advice = object(value);
			return { name: string(advice.name), rationale: string(advice.rationale), tradeoff: string(advice.tradeoff) };
		}),
	};
});
const apiRoutes = /^https?:\/\/[^/]+\/api\//;

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
	test(`Task226 authored option sets at ${viewport.width}px`, async ({ page }, testInfo) => {
		await page.setViewportSize(viewport);
		await page.route('**/*', (route) => {
			const host = new URL(route.request().url()).hostname;
			return host === '127.0.0.1' || host === 'localhost' ? route.continue() : route.abort();
		});
		for (const control of cases) {
			const methods: string[] = [];
			await page.route(apiRoutes, async (route) => {
				const request = route.request();
				methods.push(request.method());
				const path = new URL(request.url()).pathname;
				if (request.method() === 'GET' && path === `/api/sessions/${control.sessionId}`) return route.fulfill({ json: control.session });
				if (request.method() === 'GET' && path === `/api/sessions/${control.sessionId}/runs/${control.runId}`) return route.fulfill({ json: control.run });
				if (request.method() === 'GET' && path === `/api/sessions/${control.sessionId}/results`) return route.fulfill({ json: control.result });
				return route.fulfill({ status: 409, json: { error: { code: 'unexpected_offline_request', message: 'Unexpected offline request.' } } });
			});
			await page.goto(`/?session=${control.sessionId}&run=${control.runId}`);
			const primaries = page.getByRole('region', { name: 'Recommended options', exact: true });
			await expect(primaries.locator('article')).toHaveCount(control.primaries.length);
			await expect(primaries.getByRole('heading', { level: 2 })).toHaveText(control.primaries);
			const runners = page.getByRole('region', { name: 'Runners-up', exact: true });
			if (control.runners.length) {
				await expect(runners.locator('article')).toHaveCount(control.runners.length);
				await expect(runners.getByRole('heading', { level: 3 })).toHaveText(control.runners);
			} else await expect(runners).toHaveCount(0);
			await expect(page.getByText(control.rationale, { exact: true }).first()).toBeVisible();
			for (const advice of control.advice) {
				const group = control.primaries.includes(advice.name) ? primaries : runners;
				const card = group.locator('article').filter({ has: page.getByRole('heading', { name: advice.name, exact: true }) });
				await expect(card.getByText(advice.rationale, { exact: true })).toBeVisible();
				await expect(card.getByText(advice.tradeoff, { exact: true })).toBeVisible();
			}
			await page.getByRole('button', { name: 'Available sources', exact: true }).click();
			const sources = page.getByRole('region', { name: 'Available sources', exact: true });
			await expect(sources.locator(':scope > div > article')).toHaveCount(control.sourceUrls.length);
			const links = sources.getByRole('link', { name: /^(Open source|Watch video)$/ });
			expect((await links.evaluateAll((nodes) => nodes.map((node) => node.getAttribute('href')))).sort()).toEqual([...control.sourceUrls].sort());
			expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
			expect([...new Set(methods)]).toEqual(['GET']);
			await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: 'instant' }));
			await page.screenshot({ path: testInfo.outputPath(`${control.id}-${viewport.width}.png`), fullPage: true, animations: 'disabled' });
			await page.unroute(apiRoutes);
		}
	});
}
