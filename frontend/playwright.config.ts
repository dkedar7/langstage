import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const stubAgent = path.resolve(here, 'e2e/stub_agent.py');
const PORT = 4180;

/**
 * E2E tests drive the real built app served by the FastAPI backend, wired to a
 * model-free stub agent (e2e/stub_agent.py) — no API key, deterministic.
 *
 * Prereqs (handled by `npm run build` + a pip-installed langstage):
 *   1. `npm run build` so the backend has static assets to serve.
 *   2. `langstage` on PATH (pip install -e .. from the repo root).
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'on-first-retry'
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } }
  ],
  webServer: {
    command: `langstage run --agent "${stubAgent}:graph" --port ${PORT} --no-browser --workspace e2e/.tmp-workspace`,
    url: `http://localhost:${PORT}/api/config`,
    timeout: 120 * 1000,
    reuseExistingServer: !process.env.CI
  }
});
