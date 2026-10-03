import { expect, type Page, test } from '@playwright/test';

async function completedDecision(page: Page) {
	await page.addInitScript(() => window.localStorage.setItem('cartcart.region', JSON.stringify({ status: 'provided', code: 'US' })));
	await page.goto('/');
	await expect(page.locator('main')).toHaveAttribute('data-client-ready', 'true');
	await page.getByLabel('Shopping question').fill('Which monitor should I buy for coding?');
	const created = page.waitForResponse((response) => response.url().endsWith('/api/sessions/guided') && response.request().method() === 'POST');
	await page.getByRole('button', { name: 'Send question' }).click();
	const response = await created;
	const { session_id: sessionId } = await response.json();
	const apiOrigin = new URL(response.url()).origin;
	await page.getByRole('button', { name: 'Skip all', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Refine this decision' })).toBeEnabled();
	const original = await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}/results`)).json();
	return { apiOrigin, sessionId: sessionId as string, original };
}

for (const change of [
	{ kind: 'budget', choice: 'Budget', answer: '500', question: 'What budget should CartCart use now?' },
	{ kind: 'region', choice: 'Buying region', answer: 'CA', question: 'Where should CartCart check availability now?' },
	{ kind: 'category', choice: 'Kind of product', answer: 'headphones', question: 'What kind of product should CartCart compare instead?' },
	{ kind: 'preferences', choice: 'What matters most', answer: 'easy returns', question: 'What should CartCart prioritize now?' },
]) {
	test(`refines ${change.kind} from a completed decision and reviews saved versions`, async ({ page }) => {
		const { apiOrigin, sessionId, original } = await completedDecision(page);
		const path = `${apiOrigin}/api/sessions/${sessionId}`;
		await page.getByRole('button', { name: 'Refine this decision' }).click();
		await expect(page.getByRole('heading', { name: 'What would you like to change?' })).toBeVisible();
		await page.getByRole('button', { name: change.choice, exact: true }).click();
		await expect(page.getByRole('heading', { name: change.question })).toBeVisible();
		if (change.kind === 'region') await page.getByLabel('Country or region').selectOption(change.answer);
		else {
			await expect(page.getByRole('button', { name: 'Update decision' })).toBeDisabled();
			await page.getByLabel('Your answer').fill(change.answer);
		}
		const planResponse = page.waitForResponse((response) => response.url().endsWith(`/api/sessions/${sessionId}/refinements`) && response.request().method() === 'POST');
		const execution = page.waitForResponse((response) => response.url().endsWith('/execute'));
		await page.getByRole('button', { name: 'Update decision' }).click();
		const planned = await (await planResponse).json();
		expect((await execution).ok()).toBe(true);
		await expect(page.getByRole('button', { name: 'Refine this decision' })).toBeEnabled();
		const current = await (await page.request.get(`${path}/results`)).json();
		expect(current.result_version.version).toBe(original.result_version.version + 1);
		expect(current.result_version.refinement_id).toBe(planned.refinement.refinement_id);
		const events = await (await page.request.get(`${path}/runs/${planned.run.run_id}/events`)).text();
		if (change.kind === 'budget') {
			expect(planned.plan.stages).toEqual(['analysis', 'result_mode']);
			expect(events).not.toContain('"stage":"discovery"');
			expect(current.products).toEqual(original.products);
		} else {
			expect(planned.plan.stages).toContain('search');
			expect(events).toContain('"stage":"discovery"');
		}
		await page.getByText('Decision history', { exact: true }).click();
		await expect(page.getByText(`Original question: Which monitor should I buy for coding?`)).toBeVisible();
		await expect(page.getByText(planned.refinement.instruction, { exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'View original decision' }).click();
		await expect(page.getByText('Viewing an earlier decision.')).toBeVisible();
		await expect(page.getByRole('button', { name: 'Refine this decision' })).toHaveCount(0);
		await expect(page.getByRole('button', { name: 'Check a listing', exact: true })).toHaveCount(0);
		await expect(page.getByRole('heading', { name: 'Dell UltraSharp U2724DE', exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Return to latest decision' }).click();
		await expect(page.getByRole('button', { name: 'Refine this decision' })).toBeEnabled();
		await expect(page.getByText('Viewing an earlier decision.')).toHaveCount(0);
		const persistedOriginal = await (await page.request.get(`${path}/results/${original.result_version.result_version_id}`)).json();
		expect(persistedOriginal).toEqual(original);
		await expect(page.getByText(/GeneralShoppingAgent|re_intake|category_analysis|source_evidence/)).toHaveCount(0);
	});
}

test('keeps the prior result visible during an update, recovers from failure, and submits again', async ({ page }) => {
	const { apiOrigin, sessionId, original } = await completedDecision(page);
	let release: (() => void) | undefined;
	await page.route(`**/api/sessions/${sessionId}/refinements/*/execute`, async (route) => {
		await new Promise<void>((resolve) => { release = resolve; });
		await route.fulfill({ status: 200, json: { run_id: 'failed-run', status: 'failed' } });
	});
	await page.getByRole('button', { name: 'Refine this decision' }).click();
	await page.getByRole('button', { name: 'Kind of product' }).click();
	await page.getByLabel('Your answer').fill('headphones');
	await page.getByRole('button', { name: 'Update decision' }).click();
	await expect(page.getByRole('status')).toContainText('Updating your decision');
	await expect(page.getByRole('heading', { name: 'Dell UltraSharp U2724DE', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Refine this decision' })).toBeDisabled();
	await expect.poll(() => Boolean(release)).toBe(true);
	release!();
	await expect(page.getByRole('alert')).toContainText('Your previous decision is still available');
	await expect(page.getByRole('button', { name: 'Try refining again' })).toBeEnabled();
	const saved = await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}/results`)).json();
	expect(saved).toEqual(original);
	await page.unroute(`**/api/sessions/${sessionId}/refinements/*/execute`);
	await page.getByRole('button', { name: 'Try refining again' }).click();
	await page.getByRole('button', { name: 'Kind of product' }).click();
	await page.getByLabel('Your answer').fill('headphones');
	await page.getByRole('button', { name: 'Update decision' }).click();
	await expect(page.getByRole('button', { name: 'Refine this decision' })).toBeEnabled();
	const updated = await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}/results`)).json();
	expect(updated.result_version.version).toBe(2);
});

test('supports refinement Back navigation and a narrow screen without a transcript', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await completedDecision(page);
	await page.getByRole('button', { name: 'Refine this decision' }).click();
	await page.getByRole('button', { name: 'Budget', exact: true }).click();
	await page.getByLabel('Your answer').fill('abc');
	await page.getByRole('button', { name: 'Update decision' }).click();
	await expect(page.getByRole('alert')).toContainText('Type a budget amount');
	await page.getByRole('button', { name: 'Back', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'What would you like to change?' })).toBeVisible();
	await page.getByRole('button', { name: 'Back', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Refine this decision' })).toBeEnabled();
	await page.getByText('Decision history', { exact: true }).click();
	const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
	expect(overflow).toBe(false);
	await expect(page.getByRole('log')).toHaveCount(0);
});


test('opens the saved update when the execution response is lost', async ({ page }) => {
	const { apiOrigin, sessionId } = await completedDecision(page);
	await page.route(`**/api/sessions/${sessionId}/refinements/*/execute`, async (route) => {
		const response = await route.fetch();
		expect((await response.json()).status).toBe('succeeded');
		await route.abort('connectionfailed');
	});
	await page.getByRole('button', { name: 'Refine this decision' }).click();
	await page.getByRole('button', { name: 'Buying region', exact: true }).click();
	await page.getByLabel('Country or region').selectOption('CA');
	await page.getByRole('button', { name: 'Update decision' }).click();
	await expect(page.getByRole('button', { name: 'Refine this decision' })).toBeEnabled();
	await expect(page.getByRole('alert')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Buying region: Canada. Change region', exact: true })).toBeVisible();
	await page.getByText('Decision history', { exact: true }).click();
	await expect(page.getByText('Use Canada results.', { exact: true })).toBeVisible();
	const saved = await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}/results`)).json();
	expect(saved.result_version.version).toBe(2);
});
