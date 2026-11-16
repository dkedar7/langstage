import { test, expect, type Page } from '@playwright/test';
import { spawn, execFileSync, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * History (gh #232): past conversations are listed from the server's checkpointer,
 * reopened, continued and deleted.
 *
 * These tests run their own server (own port, own temp workspace) so they can
 * restart it and so no other spec's conversations show up in the list. The agent
 * (history_agent.py) has no checkpointer of its own, so the server attaches the
 * durable SQLite one, like a normal `langstage run`.
 */
const here = path.dirname(fileURLToPath(import.meta.url));
const agent = `${path.resolve(here, 'history_agent.py')}:graph`;
const PORT = 4191;
const BASE = `http://localhost:${PORT}`;

let server: ChildProcess | null = null;
let workspace = '';

/** GET a path on the test server; resolves to the status, or null when nothing answers. */
function probe(pathname: string): Promise<number | null> {
  // node:http rather than fetch: polling a closed port with fetch can abort the
  // Playwright worker on Windows (a libuv assertion in Node).
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

const listening = async () => (await probe('/api/health')) !== null;

async function startServer(): Promise<void> {
  // A server left over from an interrupted run would answer for ours, with its own
  // workspace: refuse to mistake it for the one started here.
  if (await listening()) {
    throw new Error(`port ${PORT} is already in use; stop the process listening on it and rerun`);
  }
  const args = ['run', '--agent', agent, '--port', String(PORT), '--no-browser', '--workspace', workspace];
  // On Windows the console script is langstage.exe (a launcher that runs Python as
  // its child, which is why stopServer ends the whole process tree).
  server = spawn(process.platform === 'win32' ? 'langstage.exe' : 'langstage', args, {
    stdio: 'ignore',
    windowsHide: true
  });
  server.on('error', () => {
    // Reported by the readiness wait below, which then times out.
  });
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if ((await probe('/api/config')) === 200) return;
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('the History test server did not start');
}

async function stopServer(): Promise<void> {
  const proc = server;
  server = null;
  if (!proc || proc.exitCode !== null) return;
  const exited = new Promise((r) => proc.once('exit', r));
  if (process.platform === 'win32') {
    // The console-script launcher runs Python as a child: stop the whole tree.
    try {
      execFileSync('taskkill', ['/pid', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
    } catch {
      // already gone
    }
  } else {
    proc.kill('SIGTERM');
  }
  await Promise.race([exited, new Promise((r) => setTimeout(r, 15_000))]);
  // Wait until the port is released, so a restart can bind it.
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline && (await listening())) {
    await new Promise((r) => setTimeout(r, 200));
  }
}

async function send(page: Page, text: string) {
  const input = page.getByPlaceholder('Send a message...');
  await expect(page.getByText('Connected', { exact: true })).toBeVisible();
  await input.fill(text);
  await input.press('Enter');
}

const historyButton = (page: Page) => page.getByRole('button', { name: 'History', exact: true });
const historyList = (page: Page) => page.getByRole('dialog', { name: 'Past conversations' });
const row = (page: Page, title: string) => historyList(page).getByRole('listitem').filter({ hasText: title });

async function newConversation(page: Page, expectPrompt: RegExp) {
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toMatch(expectPrompt);
    await dialog.accept();
  });
  await page.getByRole('button', { name: 'New', exact: true }).click();
  await expect(page.getByText('What can I help you with?')).toBeVisible();
}

test.describe('history', () => {
  test.describe.configure({ mode: 'serial' });
  test.use({ baseURL: BASE });
  test.setTimeout(120_000);

  test.beforeAll(async () => {
    workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'langstage-history-'));
    await startServer();
  });

  test.afterAll(async () => {
    await stopServer();
    fs.rmSync(workspace, { recursive: true, force: true });
  });

  test('a cleared conversation is reopened, continued, and survives a restart', async ({ page, browser }) => {
    await page.goto('/');
    // Nothing yet: the list says so instead of being blank.
    await historyButton(page).click();
    await expect(historyList(page).getByText('No conversations yet.')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(historyList(page)).toBeHidden();

    await send(page, 'use a tool MANGO');
    await expect(page.getByText('reply 1 to: use a tool MANGO')).toBeVisible({ timeout: 30_000 });

    // New no longer says the conversation is lost.
    await newConversation(page, /stays in History/);
    await expect(page.getByText('reply 1 to: use a tool MANGO')).toBeHidden();

    // It is in History; opening it brings back the user turn, the tool call and the reply.
    await historyButton(page).click();
    await expect(row(page, 'use a tool MANGO')).toContainText('2 messages');
    await row(page, 'use a tool MANGO').getByRole('button').first().click();
    await expect(historyList(page)).toBeHidden();
    await expect(page.getByText('use a tool MANGO', { exact: true })).toBeVisible();
    await expect(page.getByText('lookup').first()).toBeVisible();
    await expect(page.getByText('reply 1 to: use a tool MANGO')).toBeVisible();

    // The next turn continues on the old thread: the agent counts two user messages.
    await send(page, 'and then?');
    await expect(page.getByText('reply 2 to: and then?')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('reply 1 to: use a tool MANGO')).toHaveCount(1);
    await historyButton(page).click();
    await expect(row(page, 'use a tool MANGO')).toContainText('Current');
    await expect(row(page, 'use a tool MANGO')).toContainText('4 messages');
    await page.keyboard.press('Escape');

    // Restart the server, then come back from a browser with no local state at all.
    await stopServer();
    await startServer();
    const context = await browser.newContext({ baseURL: BASE });
    const other = await context.newPage();
    await other.goto('/');
    await expect(other.getByText('What can I help you with?')).toBeVisible();
    await historyButton(other).click();
    await row(other, 'use a tool MANGO').getByRole('button').first().click();
    await expect(other.getByText('reply 2 to: and then?')).toBeVisible();
    await send(other, 'after the restart');
    await expect(other.getByText('reply 3 to: after the restart')).toBeVisible({ timeout: 30_000 });
    await context.close();
  });

  test('a message sent before the stream is up is not lost', async ({ page }) => {
    // Hold every event-stream connection back, so each send below lands in the gap
    // between asking for a session and the server announcing it. A message sent in
    // that gap used to vanish (page load, New) or reach a session the server did
    // not have yet (reopening a conversation).
    await page.route('**/api/stream*', async (route) => {
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    const sendNow = async (text: string) => {
      const input = page.getByPlaceholder('Send a message...');
      await input.fill(text);
      await input.press('Enter');
      await expect(page.getByText(text, { exact: true })).toBeVisible(); // shown at once
    };

    await page.goto('/');
    await sendNow('early bird');
    await expect(page.getByText('reply 1 to: early bird')).toBeVisible({ timeout: 30_000 });

    await newConversation(page, /stays in History/);
    await sendNow('right after new');
    await expect(page.getByText('reply 1 to: right after new')).toBeVisible({ timeout: 30_000 });

    await historyButton(page).click();
    await row(page, 'early bird').getByRole('button').first().click();
    await expect(page.getByText('reply 1 to: early bird')).toBeVisible();
    await sendNow('right after reopening');
    // Reply 2: it went to the reopened thread, not to a new one.
    await expect(page.getByText('reply 2 to: right after reopening')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Error: the message was not sent/)).toHaveCount(0);
  });

  test('a second browser reads a live conversation, then takes it over once it is free', async ({ browser }) => {
    const contextA = await browser.newContext({ baseURL: BASE });
    const a = await contextA.newPage();
    await a.goto('/');
    await send(a, 'slow question'); // the agent takes a few seconds

    const contextB = await browser.newContext({ baseURL: BASE });
    const b = await contextB.newPage();
    await b.goto('/');
    await historyButton(b).click();
    await expect(row(b, 'slow question')).toContainText('Running', { timeout: 15_000 });
    await row(b, 'slow question').getByRole('button').first().click();

    // Read-only while the turn runs: no composer, no takeover.
    const notice = b.getByRole('status').filter({ hasText: 'Read-only.' });
    await expect(notice).toContainText('A turn is running in this conversation');
    await expect(b.getByRole('button', { name: 'Continue here' })).toBeDisabled();
    await expect(b.getByPlaceholder(/Read-only/)).toBeDisabled();
    await expect(b.getByText('slow question', { exact: true })).toBeVisible();

    // The turn finishes in A, complete and unduplicated; B's copy catches up.
    await expect(a.getByText('reply 1 to: slow question')).toBeVisible({ timeout: 30_000 });
    await expect(a.getByText('reply 1 to: slow question')).toHaveCount(1);
    await expect(b.getByText('reply 1 to: slow question')).toBeVisible({ timeout: 15_000 });
    await expect(notice).toContainText('open in another window', { timeout: 15_000 });
    await expect(b.getByRole('button', { name: 'Continue here' })).toBeDisabled();

    // A goes away; B can continue it, on the same thread.
    await contextA.close();
    await expect(b.getByRole('button', { name: 'Continue here' })).toBeEnabled({ timeout: 20_000 });
    await b.getByRole('button', { name: 'Continue here' }).click();
    await expect(notice).toBeHidden();
    await send(b, 'follow up');
    await expect(b.getByText('reply 2 to: follow up')).toBeVisible({ timeout: 30_000 });
    await expect(b.getByText('reply 1 to: slow question')).toHaveCount(1);
    await contextB.close();
  });

  test('a conversation waiting on an approval can be reopened and answered', async ({ browser }) => {
    // The approval dialog is modal, so the way to leave a paused conversation is to
    // close the window. Come back from a browser with no local state.
    const contextA = await browser.newContext({ baseURL: BASE });
    const a = await contextA.newPage();
    await a.goto('/');
    await send(a, 'this needs approval');
    await expect(a.getByRole('button', { name: 'Approve' })).toBeVisible({ timeout: 30_000 });
    await contextA.close();

    const contextB = await browser.newContext({ baseURL: BASE });
    const b = await contextB.newPage();
    await b.goto('/');
    await historyButton(b).click();
    // (Once the server has noticed the first window is gone, it is free to open.)
    await expect(row(b, 'this needs approval')).toContainText('Waiting for approval', { timeout: 20_000 });
    await expect(row(b, 'this needs approval')).not.toContainText('another window', { timeout: 20_000 });
    await row(b, 'this needs approval').getByRole('button').first().click();

    // The approval is back, and answering it resumes the turn.
    await b.getByRole('button', { name: 'Approve' }).click();
    await expect(b.getByText('reply 1 (approve) to: this needs approval')).toBeVisible({ timeout: 30_000 });
    await contextB.close();
  });

  test('a conversation is deleted for good, with a warning first', async ({ page, request }) => {
    await page.goto('/');
    await send(page, 'delete me please');
    await expect(page.getByText('reply 1 to: delete me please')).toBeVisible({ timeout: 30_000 });
    await newConversation(page, /stays in History/);

    await historyButton(page).click();
    const target = row(page, 'delete me please');
    await expect(target).toBeVisible();
    const before = await (await request.get('/api/conversations')).json();
    const id = before.conversations.find((c: { title: string }) => c.title === 'delete me please').thread_id;

    // Dismissing the warning deletes nothing.
    page.once('dialog', (dialog) => dialog.dismiss());
    await target.hover();
    await target.getByRole('button', { name: /^Delete conversation/ }).click();
    await expect(target).toBeVisible();

    page.once('dialog', async (dialog) => {
      expect(dialog.message()).toContain("for good and can't be recovered");
      await dialog.accept();
    });
    await target.getByRole('button', { name: /^Delete conversation/ }).click();
    await expect(target).toHaveCount(0);
    expect((await request.get(`/api/conversations/${id}`)).status()).toBe(404);

    // Deleting the conversation that is on screen starts a fresh one.
    await page.keyboard.press('Escape');
    await send(page, 'delete the current one');
    await expect(page.getByText('reply 1 to: delete the current one')).toBeVisible({ timeout: 30_000 });
    await historyButton(page).click();
    const current = row(page, 'delete the current one');
    await expect(current).toContainText('Current');
    page.once('dialog', (dialog) => dialog.accept());
    await current.hover();
    await current.getByRole('button', { name: /^Delete conversation/ }).click();
    await expect(current).toHaveCount(0);
    await expect(page.getByText('What can I help you with?')).toBeVisible();
  });
});
