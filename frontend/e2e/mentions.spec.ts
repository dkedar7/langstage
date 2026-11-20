import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { activeMention, applyMention, formatMention, insertMentions } from '../src/mentions';

/**
 * gh #238: `@` mentions of workspace files in the chat input, "Mention in chat" in
 * the file browser, and dropping a file on the chat to upload and mention it.
 */

const here = path.dirname(fileURLToPath(import.meta.url));
// playwright.config.ts starts the server with --workspace e2e/.tmp-workspace.
const workspace = path.resolve(here, '.tmp-workspace');

const uid = () => Math.random().toString(36).slice(2, 8);

function writeFile(rel: string, text = 'x') {
  const p = path.join(workspace, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, text);
}

/* ── the text rules ───────────────────────────────────────────────────────── */

test.describe('mention text', () => {
  test('finds the @word at the caret', () => {
    expect(activeMention('@', 1)).toEqual({ start: 0, end: 1, query: '' });
    expect(activeMention('look at @sal', 12)).toEqual({ start: 8, end: 12, query: 'sal' });
    expect(activeMention('(@data/s', 8)).toEqual({ start: 1, end: 8, query: 'data/s' });
    // The token runs past the caret to the next space.
    expect(activeMention('@salXY rest', 4)).toEqual({ start: 0, end: 6, query: 'sal' });
  });

  test('ignores an email address, a finished word and an inserted mention', () => {
    expect(activeMention('ana@example.org', 15)).toBeNull();
    expect(activeMention('@sales done', 11)).toBeNull();
    expect(activeMention('`data/sales.csv` ', 17)).toBeNull();
    expect(activeMention('no at here', 5)).toBeNull();
  });

  test('formats a path as workspace-relative code', () => {
    expect(formatMention('/data/sales.csv')).toBe('`data/sales.csv`');
    expect(formatMention('reports/q3/sales notes.md')).toBe('`reports/q3/sales notes.md`');
    expect(formatMention('a\\b.txt')).toBe('`a/b.txt`');
    expect(formatMention('odd`name.txt')).toBe('`` odd`name.txt ``');
  });

  test('replaces the @query and leaves the caret after a space', () => {
    const text = 'compare @sal with last year';
    const m = activeMention(text, 12)!;
    const edit = applyMention(text, m, 'data/sales.csv');
    expect(edit.text).toBe('compare `data/sales.csv` with last year');
    expect(edit.caret).toBe('compare `data/sales.csv`'.length);
    const end = applyMention('@sa', activeMention('@sa', 3)!, 'x.md');
    expect(end).toEqual({ text: '`x.md` ', caret: 7 });
  });

  test('inserts dropped paths with spaces around them', () => {
    expect(insertMentions('', 0, 0, ['/a.csv'])).toEqual({ text: '`a.csv` ', caret: 8 });
    expect(insertMentions('see', 3, 3, ['a.csv', 'b.md'])).toEqual({ text: 'see `a.csv` `b.md` ', caret: 19 });
    expect(insertMentions('see  now', 4, 4, ['a.csv']).text).toBe('see `a.csv` now');
    expect(insertMentions('replace ME', 8, 10, ['a.csv']).text).toBe('replace `a.csv` ');
  });
});

/* ── in the app ───────────────────────────────────────────────────────────── */

async function openApp(page: Page) {
  await page.goto('/');
  const input = page.getByPlaceholder('Send a message...');
  await expect(input).toBeVisible();
  return input;
}

test.describe('@ mentions in the chat', () => {
  test('type @, pick a file, and send its path to the agent', async ({ page }) => {
    const id = uid();
    writeFile(`m238-${id}/sales_${id}.csv`, 'month,total\n');
    writeFile(`m238-${id}/notes_${id}.md`);
    const input = await openApp(page);

    await input.click();
    await input.pressSequentially(`compare @sales_${id}`);
    const menu = page.getByTestId('mention-menu');
    await expect(menu.getByRole('option')).toHaveCount(1);
    await expect(menu.getByRole('option').first()).toContainText(`m238-${id}/sales_${id}.csv`);

    await input.press('Enter'); // picks, doesn't send
    await expect(menu).toHaveCount(0);
    await expect(input).toHaveValue(`compare \`m238-${id}/sales_${id}.csv\` `);

    await input.pressSequentially('please');
    await input.press('Enter');
    // The user's bubble shows the text as typed, and the echo agent repeats the
    // message it got: the path arrives as written, in backticks (code in the reply).
    await expect(page.getByText(`compare \`m238-${id}/sales_${id}.csv\` please`)).toBeVisible();
    await expect(page.getByText(/stub reply:/)).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('code', { hasText: `m238-${id}/sales_${id}.csv` })).toHaveCount(1);
  });

  test('arrow keys choose, Escape closes, and an email address opens nothing', async ({ page }) => {
    const id = uid();
    writeFile(`m238-${id}/alpha_${id}.txt`);
    writeFile(`m238-${id}/alpha_${id}_more.txt`);
    const input = await openApp(page);

    await input.click();
    await input.pressSequentially(`@alpha_${id}`);
    const options = page.getByTestId('mention-menu').getByRole('option');
    await expect(options).toHaveCount(2);
    await input.press('ArrowDown');
    await expect(options.nth(1)).toHaveAttribute('aria-selected', 'true');
    await input.press('Tab');
    await expect(input).toHaveValue(`\`m238-${id}/alpha_${id}_more.txt\` `);

    await input.pressSequentially(`@alpha_${id}`);
    await expect(options).toHaveCount(2);
    await input.press('Escape');
    await expect(page.getByTestId('mention-menu')).toHaveCount(0);

    await input.fill('');
    await input.pressSequentially('write to ana@example.org');
    await page.waitForTimeout(300);
    await expect(page.getByTestId('mention-menu')).toHaveCount(0);
  });

  test('hidden folders are never offered', async ({ page }) => {
    const id = uid();
    writeFile(`.langstage/secret_${id}.db`);
    writeFile(`node_modules/pkg_${id}/secret_${id}.js`);
    writeFile(`m238-${id}/secret_${id}.txt`);
    const input = await openApp(page);
    await input.click();
    await input.pressSequentially(`@secret_${id}`);
    const options = page.getByTestId('mention-menu').getByRole('option');
    await expect(options).toHaveCount(1);
    await expect(options.first()).toContainText(`m238-${id}/secret_${id}.txt`);
  });
});

test.describe('Mention in chat from the file browser', () => {
  test('inserts the file path at the caret', async ({ page }) => {
    const id = uid();
    writeFile(`fb238-${id}.md`);
    const input = await openApp(page);
    await input.fill('summarize ');

    await page.getByRole('button', { name: 'Files', exact: true }).click();
    const row = page.getByRole('button', { name: new RegExp(`^fb238-${id}\.md`) });
    await row.hover();
    await page.getByRole('button', { name: `Mention fb238-${id}.md in chat` }).click();
    await expect(input).toHaveValue(`summarize \`fb238-${id}.md\` `);
    await expect(input).toBeFocused();
  });

  test('the right-click menu offers it too', async ({ page }) => {
    const id = uid();
    writeFile(`fb238-dir-${id}/inner.txt`);
    const input = await openApp(page);
    await page.getByRole('button', { name: 'Files', exact: true }).click();
    await page.getByRole('button', { name: `fb238-dir-${id}` }).click({ button: 'right' });
    await page.getByRole('button', { name: 'Mention in chat' }).click();
    await expect(input).toHaveValue(`\`fb238-dir-${id}\` `);
  });
});

/* ── drop a file on the chat ──────────────────────────────────────────────── */

async function dropFile(page: Page, name: string, text: string) {
  const dt = await page.evaluateHandle(
    ([n, t]) => {
      const data = new DataTransfer();
      data.items.add(new File([t], n, { type: 'text/plain' }));
      return data;
    },
    [name, text]
  );
  const panel = page.getByTestId('chat-panel');
  await panel.dispatchEvent('dragenter', { dataTransfer: dt });
  await panel.dispatchEvent('dragover', { dataTransfer: dt });
  await expect(page.getByTestId('drop-overlay')).toBeVisible();
  await panel.dispatchEvent('drop', { dataTransfer: dt });
}

test.describe('drop a file on the chat', () => {
  test('uploads it to the workspace and mentions it, without sending', async ({ page }) => {
    const id = uid();
    const input = await openApp(page);
    await input.fill('look at');
    await dropFile(page, `drop238-${id}.txt`, 'dropped body');

    await expect(input).toHaveValue(`look at \`drop238-${id}.txt\` `);
    await expect(page.getByTestId('drop-overlay')).toHaveCount(0);
    expect(fs.readFileSync(path.join(workspace, `drop238-${id}.txt`), 'utf8')).toBe('dropped body');
    // Nothing was sent: no reply arrives.
    await page.waitForTimeout(500);
    await expect(page.getByText(/stub reply:/)).toHaveCount(0);
  });

  test('never replaces an existing file of the same name', async ({ page }) => {
    const id = uid();
    writeFile(`dup238-${id}.txt`, 'original');
    const input = await openApp(page);
    await dropFile(page, `dup238-${id}.txt`, 'new copy');

    await expect(input).toHaveValue(`\`dup238-${id} (1).txt\` `);
    expect(fs.readFileSync(path.join(workspace, `dup238-${id}.txt`), 'utf8')).toBe('original');
    expect(fs.readFileSync(path.join(workspace, `dup238-${id} (1).txt`), 'utf8')).toBe('new copy');
  });
});
