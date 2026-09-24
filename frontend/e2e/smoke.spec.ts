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

    // Presets that name an hour are labeled UTC, matching the UTC cron
    // interpretation (gh #83).
    await expect(
      page.getByRole('button', { name: 'Weekdays 9am UTC' })
    ).toBeVisible();

    // Schedules persist in the test workspace across runs (gh #151), so use a
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
    // next_run is rendered in UTC (09:00 UTC), matching the entered cron. (gh #83)
    await expect(page.getByText(/09:00 UTC/).first()).toBeVisible();
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

  test('attaches each extraction to its own tool call and shows its duration', async ({
    page
  }) => {
    // Replays the frame order langstage-core >= 1.0.36 puts on the SSE wire:
    // `extraction` comes AFTER its call's `tool_end` (the call is no longer
    // "running"), and `tool_end` carries a real `duration_ms` (gh #160). Two
    // parallel calls to the same tool finish in start order. The stub agent has no
    // tools, so the stream is canned; everything after the wire is the real UI.
    const frames = [
      { type: 'session_init', session_id: 'e2e-extraction' },
      { type: 'tool_start', id: 'call_a', name: 'think_tool', args: { reflection: 'first' }, node: 'tools' },
      { type: 'tool_start', id: 'call_b', name: 'think_tool', args: { reflection: 'second' }, node: 'tools' },
      { type: 'tool_end', id: 'call_a', name: 'think_tool', result: 'ok', status: 'success', error_message: null, duration_ms: 42 },
      { type: 'extraction', tool_name: 'think_tool', extracted_type: 'reflection', data: 'Reflection A' },
      { type: 'tool_end', id: 'call_b', name: 'think_tool', result: 'ok', status: 'success', error_message: null, duration_ms: 1500 },
      { type: 'extraction', tool_name: 'think_tool', extracted_type: 'reflection', data: 'Reflection B' },
      { type: 'complete', outcome: 'complete' }
    ];
    // A long `retry` keeps EventSource from reconnecting and replaying the frames.
    const body =
      'retry: 3600000\n\n' + frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join('');
    await page.route('**/api/stream*', (route) =>
      route.fulfill({ status: 200, contentType: 'text/event-stream', body })
    );

    await page.goto('/');

    const card = (arg: string, other: string) =>
      page.locator('div.rounded', { hasText: `(${arg})` }).filter({ hasNotText: `(${other})` });
    const first = card('first', 'second');
    const second = card('second', 'first');

    // Before the fix, A's extraction landed on the still-running call_b and B's was
    // dropped.
    await expect(first.getByText('Reflection A')).toBeVisible();
    await expect(first.getByText('42ms')).toBeVisible();
    await expect(first.getByText('Reflection B')).toHaveCount(0);
    await expect(second.getByText('Reflection B')).toBeVisible();
    await expect(second.getByText('1.5s')).toBeVisible();
    await expect(second.getByText('Reflection A')).toHaveCount(0);
  });
});
