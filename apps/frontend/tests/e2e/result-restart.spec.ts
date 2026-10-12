import { expect, test } from '@playwright/test';
import type { SessionResultsResponse, SessionStateResponse, ShoppingRunRecord } from '../../src/lib/api/types.js';

const sessionId = 'saved-result-session';
const runId = 'saved-result-run';
const timestamp = '2026-10-12T00:00:00Z';
const matrix = { schema_version: 1, criteria: [], rows: [] } satisfies SessionResultsResponse['comparison_matrix'];
const session = {
	schema_version: 1, session_id: sessionId, original_input: { query: 'Which desk lamp should I buy?' },
	current_brief: { schema_version: 1, original_query: 'Which desk lamp should I buy?', category: 'lighting', constraints: [], preferences: [] },
	created_at: timestamp, updated_at: timestamp, user_added_products: [],
} satisfies SessionStateResponse;
const run = {
	schema_version: 1, run_id: runId, session_id: sessionId, status: 'succeeded', created_at: timestamp,
} satisfies ShoppingRunRecord;
const saved = {
	result_version: { result_version_id: 'saved-result-version', run_id: runId, version: 1, recommendation_bundle_id: 'saved-bundle', comparison_matrix_id: 'saved-matrix', refinement_id: null, prior_result_version_id: null, requested_result_mode: null },
	shopping_brief: session.current_brief,
	trust_assessments: [], category_analyses: [], agent_records: [], comparison_matrix: matrix,
	recommendation_bundle: {
		schema_version: 1, bundle_id: 'saved-bundle', final_product_id: 'lamp', final_listing_id: null,
		no_strong_buy: false, final_rationale: 'An adjustable arm keeps the light on your work.',
		primary_product_ids: ['lamp'], runner_up_product_ids: [],
		mode_results: [{ mode: 'best_overall', product_id: 'lamp', listing_id: null, title: 'Adjustable desk lamp', rationale: 'The adjustable arm suits reading and desk work.', confidence: { level: 'high' }, evidence_ids: ['lamp-evidence'], source_ids: ['lamp-source'] }],
		comparison_matrix: matrix, rejected_items: [], warnings: [], evidence_ids: ['lamp-evidence'], source_ids: ['lamp-source'],
	},
	products: [{ schema_version: 1, product_id: 'lamp', name: 'Adjustable desk lamp', source_ids: ['lamp-source'], listing_ids: [] }],
	listings: [], shortlist: [], considered_products: [],
	source_snapshots: [{ schema_version: 1, source_id: 'lamp-source', url: 'https://example.test/lamp?utm_source=test', title: 'Desk lamp guide', source_type: 'official_brand_page', provider: { provider_name: 'local-control' }, extraction_status: 'succeeded', quality: { level: 'strong' }, captured_at: timestamp }],
	source_evidence: [{ evidence_id: 'lamp-evidence', source_id: 'lamp-source', target: { target_type: 'product', product_id: 'lamp' }, evidence_type: 'product_spec', claim: 'The arm has two adjustment points.', confidence: { level: 'high' }, source_quality: { level: 'strong' } }],
} satisfies SessionResultsResponse;

for (const viewport of [{ width: 1440, height: 960 }, { width: 390, height: 844 }]) {
	test(`reads one saved result and restarts with a keyboard at ${viewport.width}px`, async ({ page }) => {
		await page.setViewportSize(viewport);
		const requests: { method: string; path: string }[] = [];
		await page.route('**/api/**', async (route) => {
			const method = route.request().method();
			const path = new URL(route.request().url()).pathname;
			requests.push({ method, path });
			if (method === 'GET' && path === `/api/sessions/${sessionId}`) return route.fulfill({ json: session });
			if (method === 'GET' && path === `/api/sessions/${sessionId}/runs/${runId}`) return route.fulfill({ json: run });
			if (method === 'GET' && path === `/api/sessions/${sessionId}/results`) return route.fulfill({ json: saved });
			await route.fulfill({ status: 409, json: { error: { code: 'unexpected_local_request', message: 'Unexpected local request.' } } });
		});
		await page.goto(`/?session=${sessionId}&run=${runId}`);
		await expect(page.getByRole('heading', { level: 2, name: 'Adjustable desk lamp' })).toBeVisible();
		const restart = page.getByRole('button', { name: 'Ask another question', exact: true });
		await expect(restart).toHaveCount(1);
		const box = await restart.boundingBox();
		if (!box) throw new Error('The restart action has no bounds.');
		expect(box.y).toBeGreaterThanOrEqual(0);
		expect(box.y + box.height).toBeLessThan(viewport.height);
		for (const name of ['Refine this decision', 'Check a listing', 'Supporting details']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
		for (const name of ['Decision history', 'Products considered', 'Saved comparison']) await expect(page.getByText(name, { exact: true })).toHaveCount(0);
		await page.getByRole('button', { name: 'Available sources', exact: true }).click();
		await expect(page.locator('a[href="https://example.test/lamp"]').first()).toHaveAttribute('rel', 'noreferrer noopener');
		await page.reload();
		await expect(page.getByRole('heading', { level: 2, name: 'Adjustable desk lamp' })).toBeVisible();
		expect(requests.every((request) => request.method === 'GET')).toBe(true);
		expect(requests.filter((request) => request.path.endsWith('/results'))).toHaveLength(2);
		const readCount = requests.length;
		await restart.focus();
		await expect(restart).toBeFocused();
		await restart.press('Enter');
		await expect(page.getByLabel('Shopping question')).toHaveValue('');
		await expect(page.getByRole('button', { name: 'Send question' })).toBeDisabled();
		expect(new URL(page.url()).search).toBe('');
		expect(requests).toHaveLength(readCount);
	});
}
