import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: './tests/e2e',
	testMatch: 'task226-local-options.spec.ts',
	outputDir: './test-results/task226-local',
	reporter: [['list']],
	use: { baseURL: 'http://127.0.0.1:5276', browserName: 'chromium', channel: 'chrome', headless: true },
	webServer: {
		command: 'pnpm exec vite dev --host 127.0.0.1 --port 5276 --strictPort',
		url: 'http://127.0.0.1:5276',
		reuseExistingServer: false,
		timeout: 30_000,
	},
});
