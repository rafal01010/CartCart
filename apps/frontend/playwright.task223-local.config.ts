import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: './tests/e2e',
	testMatch: 'task223-local-projection.spec.ts',
	outputDir: './test-results/task223-local',
	reporter: [['list']],
	use: { baseURL: 'http://127.0.0.1:5274', browserName: 'chromium', channel: 'chrome', headless: true },
	webServer: {
		command: 'pnpm exec vite dev --host 127.0.0.1 --port 5274 --strictPort',
		url: 'http://127.0.0.1:5274',
		reuseExistingServer: false,
		timeout: 30_000,
	},
});
