import { expect, test } from '@playwright/test';

test('creates a session, runs fixture analysis, and shows a final pick', async ({ page }) => {
	await page.goto('/');
	await page.waitForLoadState('networkidle');

	const shoppingGoal = page.getByLabel('Shopping goal');
	await expect(shoppingGoal).toBeEditable();
	await shoppingGoal.fill(
		'Reliable 27 inch monitor for coding, movies, and light gaming with a trustworthy seller.',
	);
	await page.getByLabel('Budget').first().fill('450');
	await page.getByLabel('Priorities').fill('text clarity, USB-C, reliable seller');
	await expect(shoppingGoal).toHaveValue(/Reliable 27 inch monitor/);

	await page.getByRole('button', { name: 'Create session' }).click();

	await expect(page.getByText(/Saved session/)).toBeVisible();
	await expect(page.getByRole('button', { name: 'Start run' })).toBeEnabled();

	await page.getByRole('button', { name: 'Start run' }).click();

	await expect(page.getByText('Fixture discovery stage recorded.')).toBeVisible();
	await expect(page.getByText('Fixture shopping run completed.')).toBeVisible();
	await expect(page.getByText('Run complete', { exact: true })).toBeVisible();
	await expect(
		page.getByText(/Dell UltraSharp U2724DE is the fixture best pick/),
	).toBeVisible();
	await expect(page.getByText('Best overall monitor fixture pick.')).toBeVisible();
});
