import { test, expect, type Page } from '@playwright/test';

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

  // Canned SSE body: a long `retry` keeps EventSource from reconnecting and
  // replaying the frames.
  const sse = (frames: object[]) =>
    'retry: 3600000\n\n' + frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join('');

  test('answers an interrupt that allows respond', async ({ page }) => {
    // The interrupt the keyless demo agent raises on "ask me" (gh #195): an
    // `ask_user` request keyed `action`, not `tool`, with `respond` allowed.
    await page.route('**/api/stream*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse([
          { type: 'session_init', session_id: 'e2e-respond' },
          {
            type: 'interrupt',
            action_requests: [{ action: 'ask_user', args: { question: 'What should I call you?' } }],
            review_configs: [],
            allowed_decisions: ['respond', 'approve']
          }
        ])
      })
    );
    const posted: unknown[] = [];
    await page.route('**/api/chat/interrupt', (route) => {
      posted.push(route.request().postDataJSON());
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' });
    });

    await page.goto('/');

    // The label falls back to `action` instead of rendering blank.
    await expect(page.getByText('ask_user', { exact: true })).toBeVisible();
    await expect(page.getByText(/What should I call you\?/)).toBeVisible();
    // Approve is still offered alongside the answer box.
    await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reject' })).toHaveCount(0);

    const answer = page.getByRole('textbox', { name: 'Your response' });
    const respond = page.getByRole('button', { name: 'Respond' });
    await expect(respond).toBeDisabled();
    await answer.fill('   ');
    await expect(respond).toBeDisabled();

    await answer.fill('Call me Ada');
    await expect(respond).toBeEnabled();
    await answer.press('Enter');

    // One respond decision per action request, carrying the typed answer.
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toEqual({
      session_id: 'e2e-respond',
      decisions: [{ type: 'respond', message: 'Call me Ada' }]
    });
    await expect(answer).toHaveCount(0);
  });

  test('shows the text of a bare-string interrupt', async ({ page }) => {
    // `interrupt("What is your name?")` reaches the wire as a string action request,
    // with core's default decisions. The question must show, not a blank card.
    await page.route('**/api/stream*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse([
          { type: 'session_init', session_id: 'e2e-scalar' },
          {
            type: 'interrupt',
            action_requests: ['What is your name?'],
            review_configs: [],
            allowed_decisions: ['reject', 'edit', 'respond', 'approve']
          }
        ])
      })
    );

    await page.goto('/');

    await expect(page.getByText('What is your name?', { exact: true })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Your response' })).toBeVisible();
  });

  test('shows no respond control when respond is not allowed', async ({ page }) => {
    // LangChain's HITL middleware keys the request `name` (the label's last fallback).
    await page.route('**/api/stream*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse([
          { type: 'session_init', session_id: 'e2e-approve' },
          {
            type: 'interrupt',
            action_requests: [{ name: 'delete_file', args: { path: 'notes.txt' } }],
            review_configs: [],
            allowed_decisions: ['approve', 'reject']
          }
        ])
      })
    );
    const posted: unknown[] = [];
    await page.route('**/api/chat/interrupt', (route) => {
      posted.push(route.request().postDataJSON());
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' });
    });

    await page.goto('/');

    await expect(page.getByText('delete_file', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reject' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Respond' })).toHaveCount(0);
    await expect(page.getByRole('textbox', { name: 'Your response' })).toHaveCount(0);

    // Approve is unchanged.
    await page.getByRole('button', { name: 'Approve' }).click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toEqual({ session_id: 'e2e-approve', decisions: [{ type: 'approve' }] });
  });

  test('renders reasoning as a collapsed Thinking block above the answer', async ({ page }) => {
    // The frames the demo agent streams on "think" (gh #196).
    await page.route('**/api/stream*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: sse([
          { type: 'session_init', session_id: 'e2e-reasoning' },
          { type: 'reasoning', content: 'Let me reason about this step by step. ', node: 'agent' },
          { type: 'reasoning', content: 'The answer is a reasoning frame demo.', node: 'agent' },
          { type: 'content', content: 'Done reasoning.', role: 'assistant', node: 'agent' },
          { type: 'complete', outcome: 'complete' }
        ])
      })
    );

    await page.goto('/');

    const thinking = page.getByRole('button', { name: 'Thinking' });
    const answer = page.getByText('Done reasoning.', { exact: true });
    await expect(thinking).toBeVisible();
    await expect(answer).toBeVisible();
    // Collapsed by default, and above the answer.
    await expect(thinking).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByText(/reason about this step by step/)).toHaveCount(0);
    const [t, a] = [await thinking.boundingBox(), await answer.boundingBox()];
    expect(t!.y).toBeLessThan(a!.y);

    // Expanding shows the chunks accumulated in order.
    await thinking.click();
    await expect(thinking).toHaveAttribute('aria-expanded', 'true');
    await expect(
      page.getByText(
        'Let me reason about this step by step. The answer is a reasoning frame demo.',
        { exact: true }
      )
    ).toBeVisible();
  });

  test('renders reasoning in the Board task detail', async ({ page }) => {
    const task = {
      task_id: 'e2e-task-reasoning',
      parent_id: null,
      title: 'Reasoning task',
      prompt: 'think about it',
      agent_spec: null,
      state: 'done',
      thread_id: 't1',
      created_at: '2026-10-11T00:00:00Z',
      started_at: '2026-10-11T00:00:01Z',
      finished_at: '2026-10-11T00:00:02Z',
      result: null,
      artifacts: null,
      error: null,
      interrupt: null
    };
    const json = (body: unknown) => ({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body)
    });
    await page.route(/\/api\/tasks(\?.*)?$/, (route) => route.fulfill(json([task])));
    await page.route(/\/api\/tasks\/e2e-task-reasoning$/, (route) => route.fulfill(json(task)));
    await page.route(/\/api\/tasks\/e2e-task-reasoning\/events$/, (route) =>
      route.fulfill(
        json([
          { type: 'reasoning', content: 'Task reasoning, ', node: 'agent' },
          { type: 'reasoning', content: 'in two chunks.', node: 'agent' },
          { type: 'content', content: 'Task answer.', role: 'assistant', node: 'agent' },
          { type: 'complete', outcome: 'complete' }
        ])
      )
    );

    await page.goto('/');
    await page.getByRole('button', { name: /^Board/ }).click();
    await page.getByText('Reasoning task').click();

    const thinking = page.getByRole('button', { name: 'Thinking' });
    await expect(thinking).toBeVisible();
    await expect(page.getByText('Task answer.', { exact: true })).toBeVisible();
    await thinking.click();
    await expect(page.getByText('Task reasoning, in two chunks.', { exact: true })).toBeVisible();
  });

  // A Board task paused on an interrupt, served with its transcript; returns the
  // decisions the page posts to /resume.
  async function openPausedTask(page: Page, interrupt: object) {
    const task = {
      task_id: 'e2e-task-review',
      parent_id: null,
      title: 'Paused task',
      prompt: 'deploy it',
      agent_spec: null,
      state: 'review_needed',
      thread_id: 't2',
      created_at: '2026-10-11T00:00:00Z',
      started_at: '2026-10-11T00:00:01Z',
      finished_at: null,
      result: null,
      artifacts: null,
      error: null,
      interrupt
    };
    const json = (body: unknown) => ({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body)
    });
    await page.route(/\/api\/tasks(\?.*)?$/, (route) => route.fulfill(json([task])));
    await page.route(/\/api\/tasks\/e2e-task-review$/, (route) => route.fulfill(json(task)));
    await page.route(/\/api\/tasks\/e2e-task-review\/events$/, (route) =>
      route.fulfill(json([{ type: 'content', content: 'Checking the target.', role: 'assistant', node: 'agent' }]))
    );
    const posted: unknown[] = [];
    await page.route(/\/api\/tasks\/e2e-task-review\/resume$/, (route) => {
      posted.push(route.request().postDataJSON());
      return route.fulfill(json({ ok: true }));
    });

    await page.goto('/');
    await page.getByRole('button', { name: /^Board/ }).click();
    await page.getByText('Paused task').click();
    return posted;
  }

  test('answers a paused Board task that allows respond', async ({ page }) => {
    // gh #198: the review gate offered only Approve/Reject and never showed the
    // question, so a background task that asked one couldn't be answered.
    const posted = await openPausedTask(page, {
      type: 'interrupt',
      action_requests: [{ action: 'ask_user', args: { question: 'Which region should I deploy to?' } }],
      review_configs: [],
      allowed_decisions: ['respond', 'approve']
    });

    await expect(page.getByText('ask_user', { exact: true })).toBeVisible();
    await expect(page.getByText(/Which region should I deploy to\?/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reject' })).toHaveCount(0);

    const respond = page.getByRole('button', { name: 'Respond' });
    await expect(respond).toBeDisabled();
    await page.getByRole('textbox', { name: 'Your response' }).fill('us-west-2');
    await respond.click();
    await expect.poll(() => posted).toEqual([
      { decisions: [{ type: 'respond', message: 'us-west-2' }] }
    ]);
  });

  test('a paused Board task offers Edit when the interrupt allows it', async ({ page }) => {
    const posted = await openPausedTask(page, {
      type: 'interrupt',
      action_requests: [{ tool: 'deploy', args: { region: 'us-east-1' }, description: 'Deploy the app' }],
      review_configs: [],
      allowed_decisions: ['approve', 'edit', 'reject']
    });

    await expect(page.getByText('deploy', { exact: true })).toBeVisible();
    await expect(page.getByText('Deploy the app')).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Your response' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Edit' }).click();
    await page.getByPlaceholder('Edit args JSON...').fill('{"region": "eu-west-1"}');
    await page.getByRole('button', { name: 'Submit' }).click();
    await expect.poll(() => posted).toEqual([
      { decisions: [{ type: 'edit', edited_action: { name: 'deploy', args: { region: 'eu-west-1' } } }] }
    ]);
  });

  test('a paused Board task with no allowed verbs keeps Approve and Reject', async ({ page }) => {
    const posted = await openPausedTask(page, {
      type: 'interrupt',
      action_requests: [{ tool: 'deploy', args: {} }]
    });

    await expect(page.getByRole('button', { name: 'Reject' })).toBeVisible();
    await page.getByRole('button', { name: 'Approve' }).click();
    await expect.poll(() => posted).toEqual([{ decisions: [{ type: 'approve' }] }]);
  });
});
