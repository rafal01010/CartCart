import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(frontendDir, '../..');
const backendDir = path.join(repoRoot, 'apps/backend');

const backendHost = process.env.CARTCART_E2E_BACKEND_HOST ?? '127.0.0.1';
const backendPort = process.env.CARTCART_E2E_BACKEND_PORT ?? '8000';
const frontendHost = process.env.CARTCART_E2E_FRONTEND_HOST ?? '127.0.0.1';
const frontendPort = process.env.CARTCART_E2E_FRONTEND_PORT ?? '5173';
const backendUrl = `http://${backendHost}:${backendPort}`;
const frontendUrl = `http://${frontendHost}:${frontendPort}`;
const databasePath =
	process.env.CARTCART_E2E_DATABASE_PATH ??
	path.join(repoRoot, 'data/e2e/cartcart-e2e.sqlite3');
const frontendOrigins = JSON.stringify([
	frontendUrl,
	`http://localhost:${frontendPort}`,
	'http://localhost:5173',
	'http://127.0.0.1:5173',
]);

const backendEnv = [
	['CARTCART_ENVIRONMENT', 'test'],
	['CARTCART_DATABASE_PATH', databasePath],
	['CARTCART_BACKEND_HOST', backendHost],
	['CARTCART_BACKEND_PORT', backendPort],
	['CARTCART_FRONTEND_ORIGINS', frontendOrigins],
	['CARTCART_AGENT_WORKFLOW_MODE', 'fixture'],
	['CARTCART_LIVE_AGENTS_ENABLED', 'false'],
	['CARTCART_SEARCH_PROVIDER', 'fixture'],
	['CARTCART_SEARCH_PROVIDER_ENABLED', 'false'],
	['CARTCART_EXTRACTION_PROVIDER', 'fixture'],
	['CARTCART_EXTRACTION_PROVIDER_ENABLED', 'false'],
	['CARTCART_VIDEO_SEARCH_PROVIDER', 'fixture'],
	['CARTCART_VIDEO_SEARCH_PROVIDER_ENABLED', 'false'],
	['CARTCART_TRANSCRIPT_PROVIDER', 'fixture'],
	['CARTCART_TRANSCRIPT_PROVIDER_ENABLED', 'false'],
	['CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER', 'fixture'],
	['CARTCART_AMAZON_PRODUCT_INTELLIGENCE_PROVIDER_ENABLED', 'false'],
	['CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER', 'fixture'],
	['CARTCART_IKEA_STORE_INTELLIGENCE_PROVIDER_ENABLED', 'false'],
]
	.map(([key, value]) => `${key}=${shellQuote(value)}`)
	.join(' ');

export default defineConfig({
	testDir: './tests/e2e',
	timeout: 30_000,
	expect: {
		timeout: 10_000,
	},
	fullyParallel: false,
	reporter: [['list'], ['html', { open: 'never' }]],
	use: {
		baseURL: frontendUrl,
		trace: 'retain-on-failure',
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'] },
		},
	],
	webServer: [
		{
			command: [
				`${backendEnv} uv run alembic -c alembic.ini upgrade head`,
				`${backendEnv} uv run uvicorn --app-dir . app.main:create_app --factory --host ${shellQuote(backendHost)} --port ${backendPort}`,
			].join(' && '),
			cwd: backendDir,
			url: `${backendUrl}/readyz`,
			reuseExistingServer: false,
			timeout: 30_000,
			stdout: 'pipe',
			stderr: 'pipe',
		},
		{
			command: [
				`PUBLIC_CARTCART_API_BASE_URL=${shellQuote(backendUrl)}`,
				'pnpm exec vite dev',
				`--host ${shellQuote(frontendHost)}`,
				`--port ${frontendPort}`,
				'--strictPort',
			].join(' '),
			cwd: frontendDir,
			url: frontendUrl,
			reuseExistingServer: false,
			timeout: 30_000,
			stdout: 'pipe',
			stderr: 'pipe',
		},
	],
});

function shellQuote(value: string): string {
	return `'${value.replaceAll("'", "'\"'\"'")}'`;
}
