import { test, expect, type Page } from '@playwright/test';
import { spawn, execFileSync, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { currentTurnStart, findAnnouncedCall, findEndedCall } from '../src/toolCards';
import type { ChatMessage, ToolCall } from '../src/types';

/**
 * gh #239: a tool call id is only unique within one model response. A later turn
 * that reuses an id (the keyless demo agent always sends `demo_lookup_1`) gets its
 * own card, and never writes its result into an earlier turn's card.
 */

/* ── the matching rules ───────────────────────────────────────────────────── */

const card = (id: string, status: ToolCall['status'], query: string): ToolCall => ({
  id,
  name: 'demo_lookup',
  args: { query },
  status
});
const user = (content: string): ChatMessage => ({ id: content, role: 'user', content, toolCalls: [] });
const assistant = (...toolCalls: ToolCall[]): ChatMessage => ({
  id: `a-${Math.random()}`,
  role: 'assistant',
  content: '',
  toolCalls
});

test.describe('tool card matching', () => {
  test('the current turn starts after the last user message', () => {
    expect(currentTurnStart([])).toBe(0);
    expect(currentTurnStart([assistant()])).toBe(0);
    expect(currentTurnStart([user('a'), assistant(), user('b'), assistant()])).toBe(3);
  });

  test("a reused id in a later turn is a new call, and its result doesn't touch the old card", () => {
    const msgs = [user('one'), assistant(card('x', 'success', 'one')), user('two')];
    expect(findAnnouncedCall(msgs, 'x')).toBeNull();
    msgs.push(assistant(card('x', 'running', 'two')));
    expect(findEndedCall(msgs, 'x')).toEqual([3, 0]);
  });

  test('a resumed turn re-announces the running card it paused in', () => {
    // Answering an approval adds no user message: still the same turn (#200).
    const msgs = [user('refund it'), assistant(card('r', 'running', 'NW-1041'))];
    expect(findAnnouncedCall(msgs, 'r')).toEqual([1, 0]);
    expect(findEndedCall(msgs, 'r')).toEqual([1, 0]);
  });

  test('a reused id within one turn, after the first call finished, is a new call', () => {
    const msgs = [user('go'), assistant(card('x', 'success', 'step 1'), card('x', 'running', 'step 2'))];
    expect(findAnnouncedCall([user('go'), assistant(card('x', 'success', 'step 1'))], 'x')).toBeNull();
    expect(findEndedCall(msgs, 'x')).toEqual([1, 1]);
  });

  test("a result with no card in this turn completes an earlier turn's running card, never a finished one", () => {
    const stopped = [user('one'), assistant(card('x', 'running', 'one')), user('two')];
    expect(findEndedCall(stopped, 'x')).toEqual([1, 0]);
    const finished = [user('one'), assistant(card('x', 'success', 'one')), user('two')];
    expect(findEndedCall(finished, 'x')).toBeNull();
  });
});

/* ── the live chat and the Board task view (frames served by the test) ───── */

const sse = (frames: object[]) =>
  'retry: 3600000\n\n' + frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join('');

const lookupEnd = (query: string, ms: number) => ({
  type: 'tool_end',
  id: 'demo_lookup_1',
  name: 'demo_lookup',
  result: `answer for ${query}`,
  status: 'success',
  error_message: null,
  duration_ms: ms
});
const lookupStart = (query: string) => ({
  type: 'tool_start',
  id: 'demo_lookup_1',
  name: 'demo_lookup',
  args: { query },
  node: 'tools'
});

/** Expand every demo_lookup card under `scope` and read each one's text. */
async function cardTexts(scope: Page | ReturnType<Page['locator']>) {
  const buttons = scope.getByRole('button', { name: /demo_lookup/ });
  const n = await buttons.count();
  const texts: string[] = [];
  for (let i = 0; i < n; i++) {
    const button = buttons.nth(i);
    await button.click();
    texts.push((await button.locator('xpath=..').innerText()).replace(/\s+/g, ' '));
  }
  return texts;
}

/**
 * Serve `frames` on the page's first stream connection only. The page reconnects
 * when a stream ends; a real server never repeats frames on a reconnect (gh #236),
 * so later connections get just the session.
 */
async function streamOnce(page: Page, sessionId: string, frames: object[]) {
  let served = false;
  await page.route('**/api/stream*', (route) => {
    const first = !served;
    served = true;
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: sse([{ type: 'session_init', session_id: sessionId }, ...(first ? frames : [])])
    });
  });
}

test('a call that reuses a finished call id in the same turn gets its own card', async ({ page }) => {
  await streamOnce(page, 'e2e-reused-id', [
    lookupStart('first'),
    lookupEnd('first', 11),
    lookupStart('second'),
    lookupEnd('second', 22),
    { type: 'content', content: 'Both looked up.', role: 'assistant', node: 'agent' },
    { type: 'complete', outcome: 'complete' }
  ]);
  await page.goto('/');
  await expect(page.getByText('Both looked up.', { exact: true })).toBeVisible();

  const [one, two, ...rest] = await cardTexts(page);
  expect(rest).toEqual([]);
  expect(one).toContain('"first"');
  expect(one).toContain('answer for first');
  expect(one).not.toContain('answer for second');
  expect(two).toContain('"second"');
  expect(two).toContain('answer for second');
});

test("a Board task's follow-up that reuses an id gets its own card", async ({ page }) => {
  const task = {
    task_id: 'e2e-task-reused-id',
    parent_id: null,
    title: 'Reused id task',
    prompt: 'use a tool',
    agent_spec: null,
    state: 'done',
    thread_id: 't239',
    created_at: '2026-11-19T00:00:00Z',
    started_at: '2026-11-19T00:00:01Z',
    finished_at: '2026-11-19T00:00:09Z',
    result: 'Done.',
    artifacts: null,
    error: null,
    interrupt: null
  };
  const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route(/\/api\/tasks(\?.*)?$/, (route) => route.fulfill(json([task])));
  await page.route(/\/api\/tasks\/e2e-task-reused-id$/, (route) => route.fulfill(json(task)));
  await page.route(/\/api\/tasks\/e2e-task-reused-id\/events$/, (route) =>
    route.fulfill(
      json([
        lookupStart('first'),
        lookupEnd('first', 11),
        { type: 'content', content: 'First done.', role: 'assistant', node: 'agent' },
        { type: 'complete', outcome: 'complete' },
        { type: 'user', content: 'and again' },
        lookupStart('second'),
        lookupEnd('second', 22),
        { type: 'content', content: 'Second done.', role: 'assistant', node: 'agent' },
        { type: 'complete', outcome: 'complete' }
      ])
    )
  );

  await page.goto('/');
  await page.getByRole('button', { name: /^Board/ }).click();
  await page.getByText('Reused id task').click();
  const modal = page.locator('div.fixed.inset-0');
  await expect(modal.getByText('Second done.', { exact: true })).toBeVisible();

  const [one, two, ...rest] = await cardTexts(modal);
  expect(rest).toEqual([]);
  expect(one).toContain('answer for first');
  expect(one).not.toContain('answer for second');
  expect(two).toContain('answer for second');
});

/* ── the keyless demo agent, end to end (the issue's repro) ──────────────── */

const PORT = 4193;
const BASE = `http://localhost:${PORT}`;
let server: ChildProcess | null = null;
let workspace = '';

function probe(pathname: string): Promise<number | null> {
  // node:http rather than fetch (see history.spec.ts).
  return new Promise((resolve) => {
    const req = http.get(`${BASE}${pathname}`, (res) => {
      res.resume();
      resolve(res.statusCode ?? null);
    });
    req.on('error', () => resolve(null));
    req.setTimeout(2000, () => {
      req.destroy();
      resolve(null);
    });
  });
}

test.describe('the keyless demo agent', () => {
  test.describe.configure({ mode: 'serial' });
  test.use({ baseURL: BASE });
  test.setTimeout(120_000);

  test.beforeAll(async () => {
    test.setTimeout(120_000); // a cold start on a busy machine takes a while
    if ((await probe('/api/health')) !== null) {
      throw new Error(`port ${PORT} is already in use; stop the process listening on it and rerun`);
    }
    workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'langstage-tool-cards-'));
    const args = ['run', '--agent', 'langstage_core.demo.tools:graph', '--port', String(PORT), '--no-browser', '--workspace', workspace];
    server = spawn(process.platform === 'win32' ? 'langstage.exe' : 'langstage', args, { stdio: 'ignore', windowsHide: true });
    server.on('error', () => {});
    const deadline = Date.now() + 90_000;
    while (Date.now() < deadline) {
      if ((await probe('/api/config')) === 200) return;
      await new Promise((r) => setTimeout(r, 250));
    }
    throw new Error('the demo agent server did not start');
  });

  test.afterAll(async () => {
    const proc = server;
    server = null;
    if (proc && proc.exitCode === null) {
      const exited = new Promise((r) => proc.once('exit', r));
      if (process.platform === 'win32') {
        try {
          execFileSync('taskkill', ['/pid', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
        } catch {
          // already gone
        }
      } else {
        proc.kill('SIGTERM');
      }
      await Promise.race([exited, new Promise((r) => setTimeout(r, 15_000))]);
    }
    fs.rmSync(workspace, { recursive: true, force: true });
  });

  test('two "use a tool" turns show two cards, each with its own result', async ({ page }) => {
    await page.goto('/');
    const input = page.getByPlaceholder('Send a message...');
    await expect(page.getByText('Connected', { exact: true })).toBeVisible();

    await input.fill('use a tool');
    await input.press('Enter');
    await expect(page.getByRole('button', { name: /demo_lookup/ })).toHaveCount(1, { timeout: 30_000 });
    await expect(input).toBeEnabled();
    await expect(page.getByText(/The demo tool returned/)).toHaveCount(1, { timeout: 30_000 });

    await input.fill('use a tool please, second turn');
    await input.press('Enter');
    await expect(page.getByText(/The demo tool returned/)).toHaveCount(2, { timeout: 30_000 });
    await expect(page.getByRole('button', { name: /demo_lookup/ })).toHaveCount(2);

    const [one, two] = await cardTexts(page);
    expect(one).toContain('"use a tool"');
    expect(one).not.toContain('second turn');
    expect(two).toContain('"use a tool please, second turn"');
    // Each result names the query it answered (the demo tool echoes it back).
    expect(one).toContain('"query": "use a tool", "answer"');
    expect(two).toContain('"query": "use a tool please, second turn", "answer"');
  });
});
