import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: './tests/e2e',
	testMatch: 'task225-local-selection.spec.ts',
	outputDir: './test-results/task225-local',
	reporter: [['list']],
	use: { baseURL: 'http://127.0.0.1:5275', browserName: 'chromium', channel: 'chrome', headless: true },
	webServer: {
		command: 'pnpm exec vite dev --host 127.0.0.1 --port 5275 --strictPort',
		url: 'http://127.0.0.1:5275',
		reuseExistingServer: false,
		timeout: 30_000,
	},
});
