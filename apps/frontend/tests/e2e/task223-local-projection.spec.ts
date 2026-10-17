import { expect, test } from '@playwright/test';
import type { SessionResultsResponse, SessionStateResponse, ShoppingRunRecord } from '../../src/lib/api/types.js';

const timestamp = '2026-10-16T00:00:00Z';
const sessionId = 'task223-local-session';
const runId = 'task223-local-run';
const matrix = { schema_version: 1, criteria: [], rows: [] } satisfies SessionResultsResponse['comparison_matrix'];
const session = {
	schema_version: 1, session_id: sessionId, original_input: { query: 'Local Task 223 projection control' },
	current_brief: { schema_version: 1, original_query: 'Local Task 223 projection control', constraints: [], preferences: [] },
	created_at: timestamp, updated_at: timestamp, user_added_products: [],
} satisfies SessionStateResponse;
const run = {
	schema_version: 1, run_id: runId, session_id: sessionId, status: 'succeeded', created_at: timestamp,
} satisfies ShoppingRunRecord;
const video = {
	video_id: 'local-control', url: 'https://www.youtube.com/watch?v=local-control&utm_source=local&affiliate=tracking',
	title: 'Local control review', channel_name: 'Local control creator', transcript_availability: 'available',
};
const saved = {
	result_version: { result_version_id: 'local-version', run_id: runId, version: 1, recommendation_bundle_id: 'local-bundle', comparison_matrix_id: 'local-matrix', refinement_id: null, prior_result_version_id: null, requested_result_mode: null },
	shopping_brief: session.current_brief,
	trust_assessments: [], category_analyses: [], agent_records: [], comparison_matrix: matrix,
	recommendation_bundle: {
		schema_version: 1, bundle_id: 'local-bundle', final_product_id: 'local-product', no_strong_buy: false,
		final_rationale: 'Local control buying advice.', primary_product_ids: ['local-product'], runner_up_product_ids: [],
		mode_results: [], comparison_matrix: matrix, rejected_items: [], warnings: [], evidence_ids: [], source_ids: [],
	},
	products: [{ schema_version: 1, product_id: 'local-product', name: 'Local control product', source_ids: [], listing_ids: [] }],
	listings: [], shortlist: [], considered_products: [],
	source_snapshots: [
		{ schema_version: 1, source_id: 'local-source', url: video.url, title: video.title, source_type: 'video', provider: { provider_name: 'local-control' }, extraction_status: 'succeeded', quality: { level: 'unknown' }, captured_at: timestamp, video },
		{ schema_version: 1, source_id: 'local-metadata-source', url: 'https://www.youtube.com/watch?v=local-metadata', title: 'Local metadata-only review', source_type: 'video', provider: { provider_name: 'local-control' }, extraction_status: 'succeeded', quality: { level: 'unknown' }, captured_at: timestamp, video: { ...video, video_id: 'local-metadata', url: 'https://www.youtube.com/watch?v=local-metadata', title: 'Local metadata-only review' } },
	],
	source_evidence: [{
		evidence_id: 'local-evidence', source_id: 'local-source', target: { target_type: 'product', product_id: 'local-product' },
		evidence_type: 'video_claim', claim: 'The smaller stand leaves more desk space.', confidence: { level: 'medium' }, source_quality: { level: 'unknown' },
		video, timestamp_references: [{ start_seconds: 75, end_seconds: 91 }], transcript_segment_ids: ['local-segment'],
		transcript_support: [{
			segment_id: 'local-segment', video_id: 'local-control', start_seconds: 75, end_seconds: 91,
			text: 'Local control speech. The smaller stand leaves more desk space.',
			content_sha256: 'aed2e34068802a7a874c97baa693d4c04f4e3e58b74c3be6752533bbcf7ef559',
		}],
	}],
} satisfies SessionResultsResponse;

test('local optional video sources preserve speech proof and metadata distinction at phone width', async ({ page }, testInfo) => {
	await page.setViewportSize({ width: 390, height: 844 });
	const methods: string[] = [];
	await page.route('**/api/sessions/**', async (route) => {
		const request = route.request();
		methods.push(request.method());
		const path = new URL(request.url()).pathname;
		if (request.method() === 'GET' && path === `/api/sessions/${sessionId}`) return route.fulfill({ json: session });
		if (request.method() === 'GET' && path === `/api/sessions/${sessionId}/runs/${runId}`) return route.fulfill({ json: run });
		if (request.method() === 'GET' && path === `/api/sessions/${sessionId}/results`) return route.fulfill({ json: saved });
		return route.fulfill({ status: 409, json: { error: { code: 'unexpected_local_request', message: 'Unexpected local control request.' } } });
	});
	await page.goto(`/?session=${sessionId}&run=${runId}`);
	await expect(page.getByRole('heading', { level: 2, name: 'Local control product' })).toBeVisible();
	await expect(page.getByText('Local control buying advice.', { exact: true })).toBeVisible();
	const toggle = page.getByRole('button', { name: 'Available sources', exact: true });
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
	const sources = page.getByRole('region', { name: 'Available sources', exact: true });
	await expect(sources.getByText('By Local control creator', { exact: true })).toHaveCount(2);
	const captionSource = sources.locator('article').filter({ hasText: 'Local control review' });
	await expect(captionSource.getByRole('link', { name: 'Watch video', exact: true })).toHaveAttribute('href', 'https://www.youtube.com/watch?v=local-control');
	await expect(captionSource.getByText('Caption excerpts available', { exact: true })).toBeVisible();
	await captionSource.getByText('Evidence from this source', { exact: true }).click();
	await expect(captionSource.getByText('Local control speech. The smaller stand leaves more desk space.', { exact: true })).toBeVisible();
	const timestampLink = captionSource.getByRole('link', { name: 'Watch at 1:15-1:31', exact: true });
	await expect(timestampLink).toHaveAttribute('href', 'https://www.youtube.com/watch?v=local-control&t=75s');
	await expect(timestampLink).toHaveAttribute('rel', 'noreferrer noopener');
	const metadataSource = sources.locator('article').filter({ hasText: 'Local metadata-only review' });
	await expect(metadataSource.getByText('Video information only', { exact: true })).toBeVisible();
	await expect(metadataSource.getByRole('link', { name: 'Watch video', exact: true })).toHaveAttribute('href', 'https://www.youtube.com/watch?v=local-metadata');
	await expect(metadataSource.getByText('Caption excerpts available', { exact: true })).toHaveCount(0);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
	expect([...new Set(methods)]).toEqual(['GET']);
	await page.screenshot({ path: testInfo.outputPath('local-phone-video-sources.png'), fullPage: true });
});
