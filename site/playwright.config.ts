import { defineConfig } from '@playwright/test';

// End-to-end checks run against the built site (so this is also the build check), with the
// search server running on the fixture corpus. The build asks that server for the landing
// page's example and the follow pages; scripts/serve.mjs stands in for the host.
export default defineConfig({
  testDir: 'tests',
  testMatch: '*.e2e.ts',
  fullyParallel: true,
  reporter: 'list',
  use: { baseURL: 'http://localhost:4493', channel: 'chrome' },
  webServer: [
    { command: 'npm run api -- 8893', url: 'http://127.0.0.1:8893/health', reuseExistingServer: true, timeout: 60000 },
    {
      command: 'SAFETYPAGE_API=http://127.0.0.1:8893 npx astro build --outDir dist-e2e && SAFETYPAGE_API=http://127.0.0.1:8893 node scripts/serve.mjs dist-e2e 4493',
      url: 'http://localhost:4493', reuseExistingServer: true, timeout: 180000,
    },
  ],
});
