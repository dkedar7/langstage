import { test, expect } from '@playwright/test';

test.describe('langstage', () => {
  test('streams an agent reply in the chat', async ({ page }) => {
    await page.goto('/');

    const input = page.getByPlaceholder('Send a message...');
    await expect(input).toBeVisible();

    await input.fill('hi');
    await input.press('Enter');

    // User message echoed, then the stub agent's streamed reply. (langstage
    // appends context like the working dir to the message, so match the stable
    // "stub reply:" prefix rather than the exact echoed text.)
    await expect(page.getByText('hi', { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/stub reply:/)).toBeVisible({
      timeout: 30_000
    });
  });

  test('creates a schedule from the Schedules tab', async ({ page }) => {
    await page.goto('/');

    await page.getByRole('button', { name: 'Schedules' }).click();

    // The scheduler is in-memory and shared across the test run, so use a
    // unique name to avoid colliding with jobs from other tests/retries.
    const name = `Nightly digest ${Date.now()}`;
    await page.getByPlaceholder(/^Name/).fill(name);
    await page.getByPlaceholder(/^Cron/).fill('0 9 * * 1-5');
    await page
      .getByPlaceholder('Prompt to run on schedule')
      .fill('Summarize the day');
    await page.getByRole('button', { name: 'Add' }).click();

    // The new job appears in the list with its name and cron expression.
    await expect(page.getByText(name)).toBeVisible();
    await expect(page.getByText('0 9 * * 1-5').first()).toBeVisible();
  });

  test('rejects an invalid cron expression', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Schedules' }).click();

    await page.getByPlaceholder(/^Name/).fill('Bad schedule');
    await page.getByPlaceholder(/^Cron/).fill('not-a-cron');
    await page
      .getByPlaceholder('Prompt to run on schedule')
      .fill('whatever');
    await page.getByRole('button', { name: 'Add' }).click();

    await expect(page.getByText(/Invalid cron expression/i)).toBeVisible();
  });
});
