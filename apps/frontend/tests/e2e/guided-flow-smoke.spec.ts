import { expect, type Page, test } from '@playwright/test';

const REGION_STORAGE_KEY = 'cartcart.region';

test('covers the simplified guided fixture flow from prompt to recommendation details', async ({
	page,
}) => {
	await page.setViewportSize({ width: 1280, height: 900 });
	await page.goto('/');

	await expect(page).toHaveTitle(/CartCart/);
	await expect(page.getByRole('heading', { name: /What are you looking for/ })).toBeVisible();
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

	await expect(page.getByRole('heading', { name: 'Where will you be shopping?' })).toBeVisible();
	await expect(page.getByText(/realistic availability/)).toBeVisible();
	await page.getByLabel('Country or region').selectOption('PH');
	await page.getByRole('button', { name: 'Use this region' }).click();
	await expect(page.getByRole('heading', { name: 'Where will you be shopping?' })).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'Would one-cable setup be useful for this monitor?' })).toBeVisible();
	await page.getByRole('button', { name: 'Back' }).click();
	await expect(page.getByRole('heading', { name: /What are you looking for/ })).toBeVisible();
	await expect(page.getByLabel('Shopping question')).toHaveValue('Which monitor should I buy for coding?');
	const savedRegion = await page.evaluate((key) => window.localStorage.getItem(key), REGION_STORAGE_KEY);
	expect(savedRegion).toBe(JSON.stringify({ status: 'provided', code: 'PH' }));

	await startQuestion(page, 'Which monitor should I buy for coding?');
	await expect(page.getByRole('heading', { name: 'Where will you be shopping?' })).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'Would one-cable setup be useful for this monitor?' })).toBeVisible();
	await expect(page.locator('main textarea')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();

	await page.getByRole('button', { name: 'Yes' }).click();
	await expect(page.getByRole('button', { name: 'Continue' })).toBeEnabled();
	await page.getByRole('button', { name: 'Continue' }).click();

	await expect(page.getByRole('heading', { name: 'What budget should we stay near?' })).toBeVisible();
	await expect(page.getByText(/Share any budget|You do not need links|Useful details/)).toHaveCount(0);
	await expect(page.getByLabel('Your answer')).toHaveAttribute('placeholder', 'Type your answer.');
	await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();
	await expect(page.getByLabel(/Budget/i)).toHaveCount(0);
	await expect(page.getByLabel(/Product URL|Product link|Listing URL/i)).toHaveCount(0);
	await expectNavigationButtons(page);

	await page.getByRole('button', { name: 'Back' }).click();
	await expect(page.getByRole('heading', { name: 'Would one-cable setup be useful for this monitor?' })).toBeVisible();

	await page.goto('/');
	await expect(page.getByRole('heading', { name: /What are you looking for/ })).toBeVisible();
	await startQuestion(page, 'Which monitor should I buy for coding?');
	await expect(page.getByRole('heading', { name: 'Where will you be shopping?' })).toHaveCount(0);
	await page.getByRole('button', { name: 'Yes' }).click();
	await page.getByRole('button', { name: 'Continue' }).click();
	await expect(page.getByRole('heading', { name: 'What budget should we stay near?' })).toBeVisible();
	await page.getByRole('button', { name: 'Skip', exact: true }).click();
	await expect(
		page.getByRole('heading', { name: 'Are there any products you want CartCart to check?' }),
	).toBeVisible();
	await page.getByRole('button', { name: 'Skip all', exact: true }).click();

	await expect(
		page.getByRole('heading', { level: 2, name: 'Dell UltraSharp U2724DE' }),
	).toBeVisible();
	await expect(page.getByRole('link', { name: 'View listing' })).toBeVisible();
	await expect(page.getByText('Dell Official', { exact: true })).toBeVisible();
	await page.getByRole('tab', { name: 'Best value' }).click();
	await expect(
		page.getByRole('heading', { level: 2, name: 'ASUS ProArt Display PA278CV' }),
	).toBeVisible();
	await expect(
		page.getByRole('button', {
			name: /Change budget|Correct category|Start checking options/,
		}),
	).toHaveCount(0);
	await expect(page.getByText('Sources checked')).toHaveCount(0);
	await page.getByRole('button', { name: 'Supporting details' }).click();
	await expect(page.getByText('Seller and listing checks')).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Avoid' })).toBeVisible();
	await page.getByRole('button', { name: 'Source details' }).click();
	await expect(page.getByText('Sources checked')).toBeVisible();
	await page.getByRole('button', { name: /Buying region: Philippines/ }).click();
	await expect(page.getByRole('heading', { name: 'Where will you be shopping?' })).toBeVisible();
	await expectOldWorkspaceToBeGone(page);
	await expect(page.getByText(/fixture|trace|provider|agent/i)).toHaveCount(0);
});

test('resumes a pending question after explicit region refusal', async ({ page }) => {
	await page.goto('/');
	await startQuestion(page, 'Which desk should I buy?');
	await page.getByRole('button', { name: 'I prefer not to say' }).click();

	await expect(page.getByRole('heading', { name: 'What budget should we stay near?' })).toBeVisible();
	await page.getByLabel('Your answer').fill('A small apartment desk under $300.');
	await page.getByRole('button', { name: 'Continue' }).click();
	await expect(
		page.getByRole('heading', { name: 'Are there any products you want CartCart to check?' }),
	).toBeVisible();
	await expect(
		await page.evaluate((key) => window.localStorage.getItem(key), REGION_STORAGE_KEY),
	).toBe(JSON.stringify({ status: 'refused' }));
});

test('captures volunteered links in the main question and guided answer', async ({ page }) => {
	await page.addInitScript(
		({ key }) => window.localStorage.setItem(key, JSON.stringify({ status: 'refused' })),
		{ key: REGION_STORAGE_KEY },
	);
	await page.goto('/');
	const linked = await startQuestion(page, 'https://shop.example/items/kettle-42');
	await expect(page.getByRole('heading', { name: 'What would you like help deciding about this item?' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Skip all' })).toHaveCount(0);
	let session = await (await page.request.get(`${linked.apiOrigin}/api/sessions/${linked.sessionId}`)).json();
	expect(session.user_added_products.map((item: { url: string | null }) => item.url)).toContain('https://shop.example/items/kettle-42');
	await page.getByLabel('Your answer').fill('Is this kettle worth buying?');
	await page.getByRole('button', { name: 'Continue' }).click();
	await expect(page.getByRole('heading', { name: 'What budget should we stay near?' })).toBeVisible();
	await page.getByRole('button', { name: 'Skip all' }).click();
	await expect(page.getByRole('button', { name: 'Check a listing', exact: true })).toBeVisible();
	session = await (await page.request.get(`${linked.apiOrigin}/api/sessions/${linked.sessionId}`)).json();
	expect(session.user_added_products[0].research_attempted).toBe(true);

	await page.goto('/');
	const sentence = await startQuestion(page, 'Compare ThinkPad X1 Carbon and Dell XPS 13; check https://shop.example/items/xps-13');
	session = await (await page.request.get(`${sentence.apiOrigin}/api/sessions/${sentence.sessionId}`)).json();
	expect(session.user_added_products.filter((item: { url: string | null }) => item.url).length).toBe(1);
	expect(session.user_added_products.filter((item: { input_text: string | null }) => item.input_text).length).toBe(2);
	await page.getByRole('button', { name: 'Skip all' }).click();
	await expect(page.getByRole('button', { name: 'Check a listing', exact: true })).toBeVisible();
	session = await (await page.request.get(`${sentence.apiOrigin}/api/sessions/${sentence.sessionId}`)).json();
	expect(session.user_added_products.find((item: { url: string | null }) => item.url)?.research_attempted).toBe(true);
	await page.goto('/');
	const answered = await startQuestion(page, 'Which laptop should I buy?');
	await page.getByRole('button', { name: 'Skip', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Are there any products you want CartCart to check?' })).toBeVisible();
	await page.getByLabel('Your answer').fill('Check https://shop.example/items/x1');
	await page.getByRole('button', { name: 'Continue' }).click();
	await expect(page.getByRole('button', { name: 'Check a listing', exact: true })).toBeVisible();
	session = await (await page.request.get(`${answered.apiOrigin}/api/sessions/${answered.sessionId}`)).json();
	expect(session.user_added_products.some((item: { url: string | null; research_attempted: boolean }) => item.url === 'https://shop.example/items/x1' && item.research_attempted)).toBe(true);
});

test('checks an optional listing after a result and recovers from an unreadable page', async ({ page }) => {
	await page.addInitScript(
		({ key }) => window.localStorage.setItem(key, JSON.stringify({ status: 'refused' })),
		{ key: REGION_STORAGE_KEY },
	);
	await page.goto('/');
	const { apiOrigin, sessionId } = await startQuestion(page, 'Which monitor should I buy for coding?');
	await page.getByRole('button', { name: 'Skip all' }).click();
	await expect(page.getByRole('button', { name: 'Check a listing', exact: true })).toBeVisible();
	const prior = await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}/results`)).json();
	await expect(page.getByLabel('Listing link')).toHaveCount(0);
	await page.getByRole('button', { name: 'Check a listing', exact: true }).click();
	await page.getByLabel('Listing link').fill('https://shop.example/items/unreadable-monitor');
	await page.getByRole('button', { name: 'Check this listing' }).click();
	await expect(page.getByText('This link could not be checked')).toBeVisible();
	const refreshed = await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}/results`)).json();
	expect(refreshed.result_version.run_id).not.toBe(prior.result_version.run_id);
	const session = await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}`)).json();
	expect(session.user_added_products.some((item: { url: string | null; research_attempted: boolean }) => item.url === 'https://shop.example/items/unreadable-monitor' && item.research_attempted)).toBe(true);
	await page.getByRole('button', { name: 'Try another link' }).click();
	await expect(page.getByLabel('Listing link')).toBeVisible();
	await page.getByRole('button', { name: 'Add what you know' }).click();
	await page.getByLabel('Product name').fill('Monitor from local shop');
	await page.getByRole('button', { name: 'Save and check again' }).click();
	await expect(page.getByText('Monitor from local shop', { exact: true }).first()).toBeVisible();
	const manual = (await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}`)).json()).user_added_products;
	const supplied = manual.find((item: { product?: { name: string } }) => item.product?.name === 'Monitor from local shop');
	expect(supplied.manual_fallback_reason).toBe('retrieval_unavailable');
	expect(supplied.manual_evidence_status.source).toBe('unknown');
});

test('adds manual details after unresolved research and corrects the product in the same session', async ({ page }) => {
	await page.addInitScript(
		({ key }) => window.localStorage.setItem(key, JSON.stringify({ status: 'refused' })),
		{ key: REGION_STORAGE_KEY },
	);
	await page.goto('/');
	const { apiOrigin, sessionId } = await startQuestion(page, 'Which compact kettle should I buy?');
	await page.getByRole('button', { name: 'Skip', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Are there any products you want CartCart to check?' })).toBeVisible();
	await page.getByLabel('Your answer').fill('Acme Mini Kettle');
	await page.getByRole('button', { name: 'Continue' }).click();
	await expect(page.getByRole('heading', { name: 'Add or correct product details' })).toBeVisible();
	await expect(page.getByText('We could not confirm a product match from the available research.')).toBeVisible();
	const before = await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}/results`)).json();
	await page.getByRole('button', { name: 'Add what you know' }).click();
	await page.getByLabel('Seller, if known').fill('Local shop');
	await page.getByLabel('Price, if known').fill('49');
	await page.getByLabel('Currency').fill('USD');
	await page.getByLabel('Warranty, if known').fill('Shop says one year');
	await page.getByRole('button', { name: 'Save and check again' }).click();
	await expect(page.getByText('Details supplied by you. Product, seller, and purchase terms are not independently verified.')).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Saved comparison' })).toBeVisible();
	const manualComparison = page.getByRole('region', { name: 'Products considered' }).getByRole('article').filter({ hasText: 'Acme Mini Kettle' }).last();
	await expect(manualComparison.getByText('No verified listing')).toBeVisible();
	await expect(manualComparison.getByRole('link')).toHaveCount(0);
	await expect(page.locator('#manual-product-fallback').getByText('Seller:')).toBeVisible();
	await expect(page.getByText('Unknown', { exact: true }).first()).toBeVisible();
	const after = await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}/results`)).json();
	expect(after.result_version.run_id).not.toBe(before.result_version.run_id);
	let candidates = (await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}`)).json()).user_added_products;
	expect(candidates).toHaveLength(1);
	expect(candidates[0].manual_evidence_status.seller).toBe('user_reported');
	expect(candidates[0].listing).toBeNull();

	await page.getByRole('button', { name: 'Wrong product? Correct it' }).click();
	await page.getByLabel('Product name').fill('Acme Mini Kettle Plus');
	await page.getByRole('button', { name: 'Save and check again' }).click();
	await expect(page.getByText('Acme Mini Kettle Plus', { exact: true }).first()).toBeVisible();
	candidates = (await (await page.request.get(`${apiOrigin}/api/sessions/${sessionId}`)).json()).user_added_products;
	expect(candidates).toHaveLength(1);
	expect(candidates[0].product.name).toBe('Acme Mini Kettle Plus');
	expect(candidates[0].manual_fallback_reason).toBe('user_correction');
});

test('normal product-name intake has no manual form before research', async ({ page }) => {
	await page.addInitScript(
		({ key }) => window.localStorage.setItem(key, JSON.stringify({ status: 'refused' })),
		{ key: REGION_STORAGE_KEY },
	);
	await page.goto('/');
	await startQuestion(page, 'Which compact kettle should I buy?');
	await expect(page.getByLabel('Product name')).toHaveCount(0);
	await expect(page.getByLabel('Seller, if known')).toHaveCount(0);
	await page.getByRole('button', { name: 'Skip', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Are there any products you want CartCart to check?' })).toBeVisible();
	await page.getByLabel('Your answer').fill('Acme Mini Kettle');
	await expect(page.getByLabel('Product name')).toHaveCount(0);
});

test('shows matched, possible, unresolved, and manual products beside saved comparison gaps', async ({ page }) => {
	await page.addInitScript(
		({ key }) => window.localStorage.setItem(key, JSON.stringify({ status: 'refused' })),
		{ key: REGION_STORAGE_KEY },
	);
	await page.goto('/');
	const { sessionId } = await startQuestion(page, 'Which monitor should I buy for coding?');
	await page.route(`**/api/sessions/${sessionId}/results`, async (route) => {
		const response = await route.fetch();
		const result = await response.json();
		const [matched, alternative] = result.products;
		const listing = result.listings.find((item: { product_id: string }) => item.product_id === matched.product_id);
		const manualProduct = { schema_version: 1, product_id: 'manual-only-product', name: 'Local monitor', source_ids: [], listing_ids: [] };
		result.products.push(manualProduct);
		result.shortlist.push({ candidate_id: 'manual-only', product_id: manualProduct.product_id, listing_id: null, position: 99 });
		result.comparison_matrix.rows.push({ product_id: manualProduct.product_id, listing_id: null, scores: {}, evidence_ids: [], summary: 'Details need independent checking.' });
		const candidate = (candidate_id: string, input_text: string) => ({ schema_version: 1, candidate_id, input_text, research_attempted: true, created_at: '2026-05-31T00:00:00Z' });
		result.considered_products = [
			{ candidate: { ...candidate('matched', 'The Dell monitor'), product: matched, listing }, status: 'confirmed', exclusion_reason: null },
			{ candidate: { ...candidate('possible', 'A ProArt display'), possible_product_ids: [matched.product_id, alternative.product_id] }, status: 'possible', exclusion_reason: null },
			{ candidate: candidate('unresolved', 'Unknown display'), status: 'unresolved', exclusion_reason: null },
			{ candidate: { ...candidate('manual-only', 'Local monitor'), product: manualProduct, manual_fallback_reason: 'retrieval_insufficient', manual_details: { seller: 'Neighborhood shop' } }, status: 'manual', exclusion_reason: null },
		];
		await route.fulfill({ response, json: result });
	});
	await page.getByRole('button', { name: 'Skip all' }).click();
	const considered = page.getByRole('region', { name: 'Products considered' });
	await expect(considered.getByText('The Dell monitor')).toBeVisible();
	await expect(considered.getByText('Matched', { exact: true })).toBeVisible();
	await expect(considered.getByText('A ProArt display')).toBeVisible();
	await expect(considered.getByText('Possible match')).toBeVisible();
	await expect(considered.getByText('Unknown display')).toBeVisible();
	await expect(considered.getByText('Unresolved')).toBeVisible();
	await expect(considered.getByText('Neighborhood shop (reported by you)', { exact: false })).toBeVisible();
	const manualComparison = considered.getByRole('article').filter({ hasText: 'Local monitor' }).last();
	await expect(manualComparison.getByText('No verified listing')).toBeVisible();
	await expect(manualComparison.getByText('Unknown', { exact: true }).first()).toBeVisible();
	await expect(manualComparison.getByRole('link')).toHaveCount(0);
});

test('captures considered products by name and never asks for product links', async ({ page }) => {
	await page.goto('/');
	const { apiOrigin, sessionId } = await startQuestion(page, 'Which desk should I buy?');
	await page.getByRole('button', { name: 'I prefer not to say' }).click();

	await expect(page.getByRole('heading', { name: 'What budget should we stay near?' })).toBeVisible();
	await page.getByLabel('Your answer').fill('Under $300.');
	await page.getByRole('button', { name: 'Continue' }).click();
	await expect(
		page.getByRole('heading', { name: 'Are there any products you want CartCart to check?' }),
	).toBeVisible();
	await expect(page.getByLabel(/Product URL|Product link|Listing URL/i)).toHaveCount(0);
	await page.getByLabel('Your answer').fill('IKEA Bekant');

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
	await page.getByLabel('Your answer').press('Enter');
	await expect(page.getByRole('heading', { name: 'What budget should we stay near?' })).toBeVisible();

	await page.goto('/');
	await startQuestion(page, 'Write my homework essay');
	await expect(
		page.getByRole('heading', { name: 'CartCart can help with what to buy.' }),
	).toBeVisible();
	await expect(page.getByText(/Try asking what to buy or compare/)).toBeVisible();
	await expect(page.getByRole('button', { name: 'Back' })).toBeVisible();

	await page.goto('/');
	await startQuestion(page, 'Which weapon should I buy?');
	await expect(page.getByRole('heading', { name: 'CartCart can help with what to buy.' })).toBeVisible();
	await expect(page.getByText(/ordinary consumer purchases/)).toBeVisible();
});

for (const { label, viewport } of [
	{ label: 'desktop', viewport: { width: 1280, height: 900 } },
	{ label: 'mobile', viewport: { width: 390, height: 844 } },
]) {
	test(`keeps one-big-text guided composition on ${label}`, async ({ page }) => {
		await page.addInitScript(
			({ key }) => window.localStorage.setItem(key, JSON.stringify({ status: 'refused' })),
			{ key: REGION_STORAGE_KEY },
		);
		await page.setViewportSize(viewport);
		await page.goto('/');

		await expect(page.getByRole('heading', { name: /What are you looking for/ })).toBeVisible();
		await startQuestion(page, 'Which desk should I buy?');
		await expect(page.getByRole('heading', { name: 'What budget should we stay near?' })).toBeVisible();
		await expect(page.getByLabel('Your answer')).toHaveAttribute('placeholder', 'Type your answer.');
		await expect(page.locator('main textarea')).toHaveCount(1);
		await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();
		await expect(page.getByRole('button', { name: 'Skip all', exact: true })).toBeVisible();
		await expect(page.getByText(/Useful details|One sentence is enough|You do not need links/)).toHaveCount(0);
		await expectOldWorkspaceToBeGone(page);
		await expectNoHorizontalOverflow(page);
	});
}

test('supports visible keyboard focus on the primary question action', async ({ page }) => {
	await page.goto('/');
	const input = page.getByLabel('Shopping question');
	await input.focus();
	await expect(input).toBeFocused();
	await input.fill('Which laptop should I buy?');
	const send = page.getByRole('button', { name: 'Send question' });
	await send.focus();
	await expect(send).toBeFocused();
	await expect(send).toBeEnabled();
});

test('sends the main question with Enter and keeps Shift+Enter for a new line', async ({
	page,
}) => {
	await page.goto('/');
	await waitForPromptReady(page);
	const question = page.getByLabel('Shopping question');
	const compactComposer = await page.locator('.question-composer').boundingBox();
	expect(compactComposer).not.toBeNull();
	expect(compactComposer!.height).toBeLessThanOrEqual(72);

	await question.fill('A monitor');
	await question.press('Shift+Enter');
	await question.type('for coding');
	await expect(question).toHaveValue('A monitor\nfor coding');
	await expect(page.getByRole('heading', { name: 'Where will you be shopping?' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Send question' })).toBeEnabled();

	await question.press('Enter');
	await expect(page.getByRole('heading', { name: 'Where will you be shopping?' })).toBeVisible();
});

test('sends guided text answers with Enter and keeps Shift+Enter for a new line', async ({
	page,
}) => {
	await page.addInitScript(
		({ key }) => window.localStorage.setItem(key, JSON.stringify({ status: 'refused' })),
		{ key: REGION_STORAGE_KEY },
	);
	await page.goto('/');
	await waitForPromptReady(page);

	await page.getByLabel('Shopping question').fill('Which desk should I buy?');
	await page.getByLabel('Shopping question').press('Enter');
	await expect(page.getByRole('heading', { name: 'What budget should we stay near?' })).toBeVisible();

	const answer = page.getByLabel('Your answer');
	const compactComposer = await page.locator('.guided-composer').boundingBox();
	expect(compactComposer).not.toBeNull();
	expect(compactComposer!.height).toBeLessThanOrEqual(72);
	await answer.fill('Around $300');
	await answer.press('Shift+Enter');
	await answer.type('including delivery');
	await expect(answer).toHaveValue('Around $300\nincluding delivery');
	await answer.press('Enter');
	await expect(
		page.getByRole('heading', { name: 'Are there any products you want CartCart to check?' }),
	).toBeVisible();
});

async function startQuestion(page: Page, question: string) {
	await waitForPromptReady(page);
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

async function waitForPromptReady(page: Page) {
	await expect(page.locator('main')).toHaveAttribute('data-client-ready', 'true');
}

async function expectNavigationButtons(page: Page) {
	const back = page.getByRole('button', { name: 'Back', exact: true });
	const skip = page.getByRole('button', { name: 'Skip', exact: true });
	const skipAll = page.getByRole('button', { name: 'Skip all', exact: true });
	await expect(back).toBeVisible();
	await expect(skip).toBeVisible();
	await expect(skipAll).toBeVisible();
	await expect(back).toHaveClass(/border-border/);
	await expect(skip).toHaveClass(/border-border/);
	await expect(skipAll).toHaveClass(/border-border/);

	const backBox = await back.boundingBox();
	const skipBox = await skip.boundingBox();
	expect(backBox).not.toBeNull();
	expect(skipBox).not.toBeNull();
	expect(backBox!.x).toBeLessThan(skipBox!.x);
}

async function expectOldWorkspaceToBeGone(page: Page) {
	await expect(page.getByText('Create session')).toHaveCount(0);
	await expect(page.getByText('Start run')).toHaveCount(0);
	await expect(page.getByText('Run progress')).toHaveCount(0);
	await expect(page.getByText('Source evidence')).toHaveCount(0);
}

async function expectNoHorizontalOverflow(page: Page) {
	const hasOverflow = await page.evaluate(
		() => document.documentElement.scrollWidth > document.documentElement.clientWidth,
	);
	expect(hasOverflow).toBe(false);
}
