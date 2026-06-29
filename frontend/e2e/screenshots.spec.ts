import { test, expect } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Visual capture harness: drives the real app (model-free stub agent) into key
 * states across light + dark themes and saves PNGs to e2e/screenshots/. These
 * are for autonomous visual inspection (and a basis for future
 * toHaveScreenshot regression baselines once generated on a Linux/CI image).
 *
 * Run: npm run test:e2e -- screenshots.spec.ts
 */
const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(here, 'screenshots');

for (const theme of ['light', 'dark'] as const) {
  test.describe(`visual:${theme}`, () => {
    test.use({ colorScheme: theme });

    test(`captures key states (${theme})`, async ({ page }) => {
      const shot = (name: string) =>
        page.screenshot({ path: path.join(outDir, `${theme}-${name}.png`), fullPage: false });

      // 1. Empty / welcome
      await page.goto('/');
      await expect(page.getByPlaceholder('Send a message...')).toBeVisible();
      await page.waitForTimeout(300);
      await shot('01-empty');

      // 2. A streamed conversation
      const input = page.getByPlaceholder('Send a message...');
      await input.fill('Give me a quick hello');
      await input.press('Enter');
      await expect(page.getByText(/stub reply:/)).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(300);
      await shot('02-conversation');

      // 3. Schedules tab with a job (unique name: the scheduler is in-memory
      // and shared across the run, so avoid colliding with other captures).
      const jobName = `Morning digest ${theme}-${Date.now()}`;
      await page.getByRole('button', { name: 'Schedules' }).click();
      await page.getByPlaceholder(/^Name/).fill(jobName);
      await page.getByPlaceholder(/^Cron/).fill('0 9 * * 1-5');
      await page.getByPlaceholder('Prompt to run on schedule').fill('Summarize overnight activity');
      await page.getByRole('button', { name: 'Add' }).click();
      await expect(page.getByText(jobName)).toBeVisible();
      await page.waitForTimeout(300);
      await shot('03-schedules');

      // 4. Plan tab (default right panel)
      await page.getByRole('button', { name: 'Plan' }).click();
      await page.waitForTimeout(300);
      await shot('04-tasks');
    });
  });
}
