import { expect, type Page, test } from '@playwright/test';
import type { RunEvent, SessionResultsResponse, ShoppingRunRecord } from '../../src/lib/api/types.js';

async function startAnalysis(page: Page) {
	await page.addInitScript(() => window.localStorage.setItem('cartcart.region', JSON.stringify({ status: 'refused' })));
	await page.goto('/');
	await expect(page.locator('main')).toHaveAttribute('data-client-ready', 'true');
	await page.getByLabel('Shopping question').fill('Which monitor should I buy for coding?');
	await page.getByRole('button', { name: 'Send question', exact: true }).click();
	await page.getByRole('button', { name: 'Skip all', exact: true }).click();
}

for (const status of ['failed', 'cancelled'] as const) {
	test(`keeps a returned ${status} run failed when events are unavailable`, async ({ page }) => {
		await page.route('**/api/sessions/*/runs', async (route) => {
			const response = await route.fetch();
			const run: ShoppingRunRecord = await response.json();
			await route.fulfill({ response, json: { ...run, status } });
		});
		await page.route('**/api/sessions/*/runs/*/events', (route) => route.abort('connectionfailed'));
		await startAnalysis(page);
		await expect(page.getByRole('heading', { name: 'We could not finish the comparison.' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Try again', exact: true })).toBeEnabled();
		await expect(page.getByRole('region', { name: 'Recommendation summary', exact: true })).toHaveCount(0);
	});
}

test('opens a successful matching result without events', async ({ page }) => {
	await page.route('**/api/sessions/*/runs/*/events', (route) => route.abort('connectionfailed'));
	await startAnalysis(page);
	await expect(page.getByRole('heading', { name: 'Dell UltraSharp U2724DE', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Refine this decision', exact: true })).toBeEnabled();
});

for (const retryStatus of ['failed', 'succeeded'] as const) {
	test(`does not open an older saved result after a ${retryStatus} retry`, async ({ page }) => {
		let original: SessionResultsResponse | undefined;
		let attempts = 0;
		let failSessionLoad = true;
		await page.route('**/api/sessions/*/runs', async (route) => {
			const response = await route.fetch();
			const run: ShoppingRunRecord = await response.json();
			attempts += 1;
			await route.fulfill({ response, json: attempts === 1 ? run : { ...run, status: retryStatus } });
		});
		await page.route('**/api/sessions/*/results', async (route) => {
			const response = await route.fetch();
			original ??= await response.json();
			await route.fulfill({ response, json: original });
		});
		await page.route(/\/api\/sessions\/[^/]+$/, async (route) => {
			if (route.request().method() !== 'GET' || !failSessionLoad) return route.continue();
			failSessionLoad = false;
			await route.fulfill({ status: 503, json: { error: { code: 'unavailable', message: 'Temporarily unavailable' } } });
		});
		await page.route('**/api/sessions/*/runs/*/events', (route) => route.abort('connectionfailed'));
		await startAnalysis(page);
		await expect(page.getByRole('heading', { name: 'We could not finish the comparison.' })).toBeVisible();
		await expect.poll(() => original?.result_version.run_id).toBeTruthy();
		await page.getByRole('button', { name: 'Try again', exact: true }).click();
		await expect.poll(() => attempts).toBe(2);
		await expect(page.getByRole('heading', { name: 'We could not finish the comparison.' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Try again', exact: true })).toBeEnabled();
		await expect(page.getByRole('region', { name: 'Recommendation summary', exact: true })).toHaveCount(0);
	});
}

for (const returnedStatus of ['pending', 'running'] as const) {
	for (const savedStatus of ['failed', 'succeeded'] as const) {
		test(`checks a ${returnedStatus} run status after losing events and respects ${savedStatus}`, async ({ page }) => {
			let statusReads = 0;
			await page.route('**/api/sessions/*/runs', async (route) => {
				const response = await route.fetch();
				const run: ShoppingRunRecord = await response.json();
				await route.fulfill({ response, json: { ...run, status: returnedStatus } });
			});
			await page.route(/\/api\/sessions\/[^/]+\/runs\/[^/]+$/, async (route) => {
				const response = await route.fetch();
				const run: ShoppingRunRecord = await response.json();
				statusReads += 1;
				await route.fulfill({ response, json: { ...run, status: savedStatus } });
			});
			await page.route('**/api/sessions/*/runs/*/events', (route) => route.abort('connectionfailed'));
			await startAnalysis(page);
			if (savedStatus === 'failed') {
				await expect(page.getByRole('heading', { name: 'We could not finish the comparison.' })).toBeVisible();
				await expect(page.getByRole('region', { name: 'Recommendation summary', exact: true })).toHaveCount(0);
			} else {
				await expect(page.getByRole('heading', { name: 'Dell UltraSharp U2724DE', exact: true })).toBeVisible();
			}
			expect(statusReads).toBe(1);
		});
	}
}

test('opens only the matching successful result when EventSource is unavailable', async ({ page }) => {
	await page.addInitScript(() => Object.defineProperty(window, 'EventSource', { value: undefined }));
	await startAnalysis(page);
	await expect(page.getByRole('heading', { name: 'Dell UltraSharp U2724DE', exact: true })).toBeVisible();
});

test('keeps a terminal stream failure visible without opening the saved result', async ({ page }) => {
	await page.route('**/api/sessions/*/runs', async (route) => {
		const response = await route.fetch();
		const run: ShoppingRunRecord = await response.json();
		await route.fulfill({ response, json: { ...run, status: 'running' } });
	});
	await page.route('**/api/sessions/*/runs/*/events', async (route) => {
		const runId = new URL(route.request().url()).pathname.split('/').at(-2);
		if (!runId) throw new Error('The event request has no run ID.');
		const event = {
			schema_version: 1, event_id: 'failed-event', run_id: runId, sequence: 1,
			stage: 'discovery', status: 'failed', message: 'Research could not finish.',
			occurred_at: '2026-10-05T00:00:00Z',
		} satisfies RunEvent;
		await route.fulfill({ contentType: 'text/event-stream', body: `event: run_event\ndata: ${JSON.stringify(event)}\n\n` });
	});
	await startAnalysis(page);
	await expect(page.getByRole('heading', { name: 'We could not finish the comparison.' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Try again', exact: true })).toBeEnabled();
	await expect(page.getByRole('region', { name: 'Recommendation summary', exact: true })).toHaveCount(0);
});

test('ignores an analysis response after returning Home', async ({ page }) => {
	let release: (() => void) | undefined;
	await page.route('**/api/sessions/*/runs', async (route) => {
		const response = await route.fetch();
		await new Promise<void>((resolve) => { release = resolve; });
		await route.fulfill({ response });
	});
	await startAnalysis(page);
	await expect.poll(() => Boolean(release)).toBe(true);
	await page.getByRole('button', { name: 'CartCart home', exact: true }).click();
	const returned = page.waitForResponse((response) => response.url().endsWith('/runs'));
	if (!release) throw new Error('The analysis response was not held.');
	release();
	await returned;
	await expect(page.getByRole('heading', { name: 'What are you looking for?' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send question', exact: true })).toBeDisabled();
	await expect(page.getByRole('region', { name: 'Recommendation summary', exact: true })).toHaveCount(0);
});

test('preserves the earlier decision when a listing analysis fails', async ({ page }) => {
	await startAnalysis(page);
	await expect(page.getByRole('button', { name: 'Refine this decision', exact: true })).toBeEnabled();
	await page.route('**/api/sessions/*/runs', async (route) => {
		const response = await route.fetch();
		const run: ShoppingRunRecord = await response.json();
		await route.fulfill({ response, json: { ...run, status: 'failed' } });
	});
	await page.route('**/api/sessions/*/runs/*/events', (route) => route.abort('connectionfailed'));
	await page.getByRole('button', { name: 'Check a listing', exact: true }).click();
	await page.getByLabel('Listing link').fill('https://shop.example/items/unreadable-monitor');
	await page.getByRole('button', { name: 'Check this listing', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('Your previous decision is still');
	await expect(page.getByRole('heading', { name: 'Dell UltraSharp U2724DE', exact: true })).toBeVisible();
	await expect(page.getByText('This link could not be checked', { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Check a listing', exact: true }).click();
	await expect(page.getByLabel('Listing link')).toBeVisible();
	await page.unroute('**/api/sessions/*/runs');
	await page.getByRole('button', { name: 'Refine this decision', exact: true }).click();
	await page.getByRole('button', { name: 'Buying region', exact: true }).click();
	await page.getByLabel('Country or region').selectOption('CA');
	await page.getByRole('button', { name: 'Update decision', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Refine this decision', exact: true })).toBeEnabled();
	await expect(page.getByRole('button', { name: 'Buying region: Canada. Change region', exact: true })).toBeVisible();
	await expect(page.getByRole('alert')).toHaveCount(0);
});

test('preserves the earlier decision when manual detail analysis fails', async ({ page }) => {
	await page.addInitScript(() => window.localStorage.setItem('cartcart.region', JSON.stringify({ status: 'refused' })));
	await page.goto('/');
	await expect(page.locator('main')).toHaveAttribute('data-client-ready', 'true');
	await page.getByLabel('Shopping question').fill('Which compact kettle should I buy?');
	await page.getByRole('button', { name: 'Send question', exact: true }).click();
	await page.getByRole('button', { name: 'Skip', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Are there any products you want CartCart to check?' })).toBeVisible();
	await page.getByLabel('Your answer').fill('Acme Mini Kettle');
	await page.getByRole('button', { name: 'Continue', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Add what you know', exact: true })).toBeVisible();
	await page.route('**/api/sessions/*/runs', async (route) => {
		const response = await route.fetch();
		const run: ShoppingRunRecord = await response.json();
		await route.fulfill({ response, json: { ...run, status: 'failed' } });
	});
	await page.route('**/api/sessions/*/runs/*/events', (route) => route.abort('connectionfailed'));
	await page.getByRole('button', { name: 'Add what you know', exact: true }).click();
	await page.getByLabel('Seller, if known').fill('Local shop');
	await page.getByRole('button', { name: 'Save and check again', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('Your previous decision is still');
	await expect(page.getByText('We could not confirm a product match from the available research.', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Add what you know', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Save and check again', exact: true })).toBeEnabled();
});

for (const status of ['failed', 'cancelled'] as const) {
	test(`keeps a returned ${status} refinement failed even when status recovery could find success`, async ({ page }) => {
		await startAnalysis(page);
		await expect(page.getByRole('button', { name: 'Refine this decision', exact: true })).toBeEnabled();
		let statusReads = 0;
		await page.route('**/api/sessions/*/refinements/*/execute', async (route) => {
			const response = await route.fetch();
			const run: ShoppingRunRecord = await response.json();
			expect(run.status).toBe('succeeded');
			await route.fulfill({ response, json: { ...run, status } });
		});
		await page.route(/\/api\/sessions\/[^/]+\/runs\/[^/]+$/, async (route) => {
			statusReads += 1;
			await route.continue();
		});
		await page.getByRole('button', { name: 'Refine this decision', exact: true }).click();
		await page.getByRole('button', { name: 'Buying region', exact: true }).click();
		await page.getByLabel('Country or region').selectOption('CA');
		await page.getByRole('button', { name: 'Update decision', exact: true }).click();
		await expect(page.getByRole('alert')).toContainText('Your previous decision is still available');
		await expect(page.getByRole('button', { name: 'Try refining again', exact: true })).toBeEnabled();
		await expect(page.getByRole('button', { name: 'Buying region: Region not set. Change region', exact: true })).toBeVisible();
		await page.getByText('Decision history', { exact: true }).click();
		await expect(page.getByRole('button', { name: 'Viewing', exact: true })).toHaveCount(1);
		await expect(page.getByText('Use Canada results.', { exact: true })).toHaveCount(0);
		expect(statusReads).toBe(0);
	});
}

test('ignores a saved-result response after returning Home', async ({ page }) => {
	let release: (() => void) | undefined;
	await page.route('**/api/sessions/*/results', async (route) => {
		const response = await route.fetch();
		await new Promise<void>((resolve) => { release = resolve; });
		await route.fulfill({ response });
	});
	await startAnalysis(page);
	await expect.poll(() => Boolean(release)).toBe(true);
	await page.getByRole('button', { name: 'CartCart home', exact: true }).click();
	const returned = page.waitForResponse((response) => response.url().endsWith('/results'));
	if (!release) throw new Error('The saved-result response was not held.');
	release();
	await returned;
	await expect(page.getByRole('heading', { name: 'What are you looking for?' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send question', exact: true })).toBeDisabled();
	await expect(page.getByRole('region', { name: 'Recommendation summary', exact: true })).toHaveCount(0);
});

test('preserves configuration guidance when initial analysis cannot start', async ({ page }) => {
	await page.route('**/api/sessions/*/runs', (route) => route.fulfill({ status: 409, json: {
		error: { code: 'research_mode_mismatch', message: 'Research settings do not match.', request_id: 'offline-config-failure' },
	} }));
	await startAnalysis(page);
	await expect(page.getByRole('heading', { name: 'We could not finish the comparison.' })).toBeVisible();
	await expect(page.getByText('CartCart is using sample-data mode with live research settings. Enable live research or use sample data, then restart the app.', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Try again', exact: true })).toBeEnabled();
});
