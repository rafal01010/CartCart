import { expect, type Page, test } from '@playwright/test';

const REGION_STORAGE_KEY = 'cartcart.region';

test('covers the guided fixture flow from prompt to staged recommendation details', async ({
	page,
}) => {
	await page.setViewportSize({ width: 1280, height: 900 });
	await page.goto('/');

	await expect(page).toHaveTitle(/CartCart/);
	await expect(page.getByRole('heading', { name: 'Send your question' })).toBeVisible();
	await expect(page.locator('.starter-question')).toContainText('Which phone should I buy?');
	await expect(page.locator('.starter-question')).not.toContainText('Which phone should I buy?', {
		timeout: 4_500,
	});
	await expect(page.getByLabel('Shopping question')).toHaveAttribute(
		'placeholder',
		'Ask what you should buy.',
	);
	await expect(page.getByRole('button', { name: 'Send question' })).toBeDisabled();
	await expectOldWorkspaceToBeGone(page);

	await startQuestion(page, 'Which monitor should I buy for coding?');

	await expect(page.getByRole('heading', { name: 'Where should CartCart look first?' })).toBeVisible();
	await expect(page.getByText(/products you can actually buy/)).toBeVisible();
	await page.getByLabel('Country or region').selectOption('CA');
	await page.getByRole('button', { name: 'Use this region' }).click();
	await expect(page.getByRole('heading', { name: 'Where should CartCart look first?' })).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'Would one-cable setup be useful for this monitor?' })).toBeVisible();
	await page.getByRole('button', { name: 'Back to question' }).click();
	await expect(page.getByRole('heading', { name: 'Send your question' })).toBeVisible();
	await expect(page.getByLabel('Shopping question')).toHaveValue('Which monitor should I buy for coding?');
	const savedRegion = await page.evaluate((key) => window.localStorage.getItem(key), REGION_STORAGE_KEY);
	expect(savedRegion).toBe(JSON.stringify({ status: 'provided', code: 'CA' }));

	await startQuestion(page, 'Which monitor should I buy for coding?');
	await expect(page.getByRole('heading', { name: 'Where should CartCart look first?' })).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'Would one-cable setup be useful for this monitor?' })).toBeVisible();
	await expect(page.locator('main textarea')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();

	await page.getByRole('button', { name: 'Yes' }).click();
	await expect(page.getByRole('button', { name: 'Continue' })).toBeEnabled();
	await page.getByRole('button', { name: 'Continue' }).click();

	await expect(page.getByRole('heading', { name: /Anything we should keep in mind/ })).toBeVisible();
	await expect(page.getByText(/Share any budget, must-haves/)).toBeVisible();
	await expect(page.getByLabel('Your answer')).toHaveAttribute('placeholder', 'Type your answer.');
	await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();
	await expect(page.getByLabel(/Budget/i)).toHaveCount(0);
	await expect(page.getByLabel(/Product URL|Product link|Listing URL/i)).toHaveCount(0);

	await page.getByRole('button', { name: 'Back' }).click();
	await expect(page.getByRole('heading', { name: 'Would one-cable setup be useful for this monitor?' })).toBeVisible();
	await page.getByRole('button', { name: 'No' }).click();
	await page.getByRole('button', { name: 'Continue' }).click();
	await expect(page.getByRole('heading', { name: /CartCart has enough/ })).toBeVisible();
	await page.getByRole('button', { name: 'Back' }).click();
	await expect(page.getByRole('heading', { name: 'Would one-cable setup be useful for this monitor?' })).toBeVisible();

	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Send your question' })).toBeVisible();
	await startQuestion(page, 'Which monitor should I buy for coding?');
	await expect(page.getByRole('heading', { name: 'Where should CartCart look first?' })).toHaveCount(0);
	await page.getByRole('button', { name: 'Yes' }).click();
	await page.getByRole('button', { name: 'Continue' }).click();
	await expect(page.getByRole('heading', { name: /Anything we should keep in mind/ })).toBeVisible();
	await page.getByRole('button', { name: 'Skip question' }).click();

	await expect(page.getByRole('heading', { name: /CartCart has enough/ })).toBeVisible();
	await page.getByRole('button', { name: 'Start checking options' }).click();
	await expect(page.getByRole('heading', { name: 'Here is the best pick.' })).toBeVisible();
	await expect(page.getByText(/Dell UltraSharp U2724DE/)).toBeVisible();
	await expect(page.getByText('Sources checked')).toHaveCount(0);
	await page.getByRole('button', { name: 'Supporting details' }).click();
	await expect(page.getByText('Seller and listing checks')).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Avoid' })).toBeVisible();
	await page.getByRole('button', { name: 'Source details' }).click();
	await expect(page.getByText('Sources checked')).toBeVisible();
	await expectOldWorkspaceToBeGone(page);
	await expect(page.getByText(/fixture|trace|provider|agent/i)).toHaveCount(0);
});

test('resumes a pending question after explicit region refusal', async ({ page }) => {
	await page.goto('/');
	await startQuestion(page, 'Which desk should I buy?');
	await page.getByRole('button', { name: 'I prefer not to say' }).click();

	await expect(page.getByRole('heading', { name: /Anything we should keep in mind/ })).toBeVisible();
	await page.getByLabel('Your answer').fill('A small apartment desk under $300.');
	await page.getByRole('button', { name: 'Continue' }).click();
	await expect(page.getByRole('heading', { name: /CartCart has enough/ })).toBeVisible();
	await expect(page.getByText(/Which desk should I buy/)).toBeVisible();
	await expect(
		await page.evaluate((key) => window.localStorage.getItem(key), REGION_STORAGE_KEY),
	).toBe(JSON.stringify({ status: 'refused' }));
});

test('captures considered products by name and never asks for product links', async ({ page }) => {
	await page.goto('/');
	const { apiOrigin, sessionId } = await startQuestion(page, 'Which desk should I buy?');
	await page.getByRole('button', { name: 'I prefer not to say' }).click();

	await expect(page.getByRole('heading', { name: /Anything we should keep in mind/ })).toBeVisible();
	await expect(page.getByLabel(/Product URL|Product link|Listing URL/i)).toHaveCount(0);
	await page
		.getByLabel('Your answer')
		.fill('I am considering the IKEA Bekant and need a small desk under $300.');

	const answerResponse = page.waitForResponse((response) =>
		response.url().includes(`/api/sessions/${sessionId}/answers`),
	);
	await page.getByRole('button', { name: 'Continue' }).click();
	await answerResponse;

	const sessionResponse = await page.request.get(`${apiOrigin}/api/sessions/${sessionId}`);
	expect(sessionResponse.ok()).toBe(true);
	const session = await sessionResponse.json();
	expect(session.user_added_products).toHaveLength(1);
	expect(session.user_added_products[0].input_text).toContain('IKEA Bekant');
	expect(session.user_added_products[0].url).toBeNull();
});

test('supports comparison custom answers and shopping-scope guardrails', async ({ page }) => {
	await page.goto('/');
	await startQuestion(page, 'Compare iPhone 16 vs Pixel 10');
	await page.getByRole('button', { name: 'I prefer not to say' }).click();

	await expect(
		page.getByRole('heading', { name: 'For that comparison, what should matter most?' }),
	).toBeVisible();
	await page.getByRole('button', { name: 'Type my answer' }).click();
	await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();
	await page.getByLabel('Your answer').fill('Camera quality and battery life.');
	await page.getByRole('button', { name: 'Continue' }).click();
	await expect(page.getByRole('heading', { name: /Anything we should keep in mind/ })).toBeVisible();

	await page.goto('/');
	await startQuestion(page, 'Write my homework essay');
	await expect(
		page.getByRole('heading', { name: 'CartCart can help with shopping decisions.' }),
	).toBeVisible();
	await expect(page.getByText(/Try asking what to buy or compare/)).toBeVisible();
	await expect(page.getByRole('button', { name: 'Back to question' })).toBeVisible();

	await page.goto('/');
	await startQuestion(page, 'Which weapon should I buy?');
	await expect(page.getByRole('heading', { name: 'CartCart can help with shopping decisions.' })).toBeVisible();
	await expect(page.getByText(/ordinary consumer purchases/)).toBeVisible();
});

for (const { label, viewport } of [
	{ label: 'desktop', viewport: { width: 1280, height: 900 } },
	{ label: 'mobile', viewport: { width: 390, height: 844 } },
]) {
	test(`keeps the prompt-led guided composition on ${label}`, async ({ page }) => {
		await page.addInitScript(
			({ key }) => window.localStorage.setItem(key, JSON.stringify({ status: 'refused' })),
			{ key: REGION_STORAGE_KEY },
		);
		await page.setViewportSize(viewport);
		await page.goto('/');

		await expect(page.getByRole('heading', { name: 'Send your question' })).toBeVisible();
		await startQuestion(page, 'Which desk should I buy?');
		await expect(page.getByRole('heading', { name: /Anything we should keep in mind/ })).toBeVisible();
		await expect(page.getByLabel('Your answer')).toHaveAttribute('placeholder', 'Type your answer.');
		await expect(page.locator('main textarea')).toHaveCount(1);
		await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();
		await expect(page.getByRole('button', { name: 'Skip all and start analysis' })).toBeVisible();
		await expectOldWorkspaceToBeGone(page);
	});
}

async function startQuestion(page: Page, question: string) {
	await page.getByLabel('Shopping question').fill(question);
	const responsePromise = page.waitForResponse(
		(response) => response.url().endsWith('/api/sessions/guided') && response.request().method() === 'POST',
	);
	await page.getByRole('button', { name: 'Send question' }).click();
	const response = await responsePromise;
	const payload = await response.json();

	return {
		apiOrigin: new URL(response.url()).origin,
		sessionId: payload.session_id as string,
	};
}

async function expectOldWorkspaceToBeGone(page: Page) {
	await expect(page.getByText('Create session')).toHaveCount(0);
	await expect(page.getByText('Start run')).toHaveCount(0);
	await expect(page.getByText('Run progress')).toHaveCount(0);
	await expect(page.getByText('Source evidence')).toHaveCount(0);
}
