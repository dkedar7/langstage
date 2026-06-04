import { test, expect } from '@playwright/test';

/**
 * Visual-regression gate (pixel-diff vs committed baselines).
 *
 * Scoped to the deterministic empty/welcome state in light + dark — it captures
 * the full chrome (header, chat pane, right-panel tabs, empty Tasks panel) with
 * zero dynamic content. The conversation and Schedules views carry timestamps,
 * dates, and generated ids, so they're covered by the functional smoke + the
 * capture harness (screenshots.spec.ts) rather than pixel diffs.
 *
 * Baselines are platform-suffixed by Playwright (e.g. `-linux`) and are
 * generated/checked inside the pinned Playwright Docker image, so local
 * generation and CI render identically. Regenerate with:
 *   npm run test:visual:update   (see package.json / docker-visual.sh)
 */
const opts = { animations: 'disabled', maxDiffPixelRatio: 0.01 } as const;

for (const theme of ['light', 'dark'] as const) {
  test.describe(`visual-${theme}`, () => {
    test.use({ colorScheme: theme });

    test(`empty/welcome (${theme})`, async ({ page }) => {
      await page.goto('/');
      await expect(page.getByPlaceholder('Send a message...')).toBeVisible();
      await expect(page.getByText('What can I help you with?')).toBeVisible();
      await expect(page).toHaveScreenshot(`empty-${theme}.png`, opts);
    });
  });
}
