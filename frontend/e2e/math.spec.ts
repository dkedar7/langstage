/**
 * TeX math in agent text (gh #233).
 *
 * Three layers, all in the repo's one test runner:
 *  1. the delimiter pre-pass as a pure function (no browser);
 *  2. the shared markdown renderer to static HTML, with KaTeX (no browser);
 *  3. the real built app in Chromium: chat (streamed by the stub agent), Canvas,
 *     copy, print, offline, hostile formulas.
 */
import { test, expect, type Locator, type Page } from '@playwright/test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import { markdownPlugins } from '../src/components/Markdown';
import { rehypeMath } from '../src/markdown/mathRender';
import { hasMathCandidate, prepareMath, MAX_TEX_LENGTH } from '../src/markdown/mathSyntax';

/** The issue's keyless reply. */
const REPLY =
  String.raw`The result of \( 17 + 25 \) is \( 42 \). Variance: \[ \sigma^2 = \frac{1}{n}\sum_i (x_i - \bar{x})^2 \] and inline $e^{i\pi}+1=0$.`;

const tex = (src: string, streaming = false) =>
  prepareMath(src, { streaming }).segments.map((s) => s.tex);

/** Render the way the app does. `katex: false` is the app before KaTeX has loaded. */
function html(src: string, { katex = true, streaming = false } = {}): string {
  const p = hasMathCandidate(src) ? prepareMath(src, { streaming }) : null;
  const prepared = p && p.segments.length ? p : null;
  const plugins = markdownPlugins(prepared, katex ? (rehypeMath as never) : null);
  return renderToStaticMarkup(
    createElement(ReactMarkdown, { ...plugins, children: prepared ? prepared.text : src })
  );
}

/** Visible text of rendered HTML: tags dropped, entities decoded. */
const text = (markup: string) =>
  markup
    .replace(/<[^>]+>/g, '')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&');

test.describe('math delimiters (pre-pass)', () => {
  test('finds \\( \\), \\[ \\] and $$ $$; a single $ is never math', () => {
    const p = prepareMath(REPLY);
    expect(p.segments.map((s) => [s.tex, s.display])).toEqual([
      ['17 + 25', false],
      ['42', false],
      [String.raw`\sigma^2 = \frac{1}{n}\sum_i (x_i - \bar{x})^2`, true]
    ]);
    // The single-dollar formula and everything else is still there, untouched.
    expect(p.text).toContain(String.raw`inline $e^{i\pi}+1=0$.`);
    expect(p.segments[0].source).toBe(String.raw`\( 17 + 25 \)`);

    expect(tex('It costs $5 and $10, or $5-$10 a month.')).toEqual([]);
    expect(tex('$$ E = mc^2 $$')).toEqual(['E = mc^2']);
    expect(tex('Total:\n$$\n\\int_0^1 x\\,dx\n$$\ndone')).toEqual(['\\int_0^1 x\\,dx']);
  });

  test('text without math comes back as the same string', () => {
    for (const src of ['plain text', '$5 and $10', 'a \\* b', 'cost: \\$\\$ each']) {
      expect(prepareMath(src).text).toBe(src);
    }
  });

  test('code is never rewritten: spans, fences, indented blocks, inside lists and quotes', () => {
    const cases = [
      'Use `\\(x\\)` for inline math.',
      'Use ``\\[ a `b` \\]`` here.',
      '```latex\n\\[ x^2 \\]\n$$ y^2 $$\n```',
      '~~~\n\\( x \\)\n~~~',
      'Text\n\n    \\( indented code \\)\n',
      '- item\n\n  ```\n  \\[ x^2 \\]\n  ```',
      '> ```\n> $$ x^2 $$\n> ```',
      '```\nstill streaming \\( x'
    ];
    for (const src of cases) {
      expect(prepareMath(src).segments, src).toEqual([]);
      expect(prepareMath(src, { streaming: true }).segments, src).toEqual([]);
    }
    // Math next to code is still found, and the code is left alone.
    const mixed = prepareMath('`\\(a\\)` then \\(b\\) then `$$c$$`');
    expect(mixed.segments.map((s) => s.tex)).toEqual(['b']);
    expect(mixed.text).toContain('`\\(a\\)` then ');
    expect(mixed.text).toContain(' then `$$c$$`');
  });

  test('escaped dollars and backslashes do not open math', () => {
    expect(tex('\\$\\$ not math \\$\\$')).toEqual([]);
    expect(tex('a \\\\( b \\\\) c')).toEqual([]); // `\\(` is an escaped backslash, then a paren
    expect(tex('price \\$$ x^2 $$')).toEqual([]); // `\$` then a lone `$`
    expect(tex('$$$ three $$$')).toEqual([]);
  });

  test('paths and escaped brackets are not math', () => {
    for (const src of [
      'Open C:\\[temp\\] first.',
      'In C:\\Users\\(old\\)\\file.txt',
      'data\\[1\\] and data\\(2\\)',
      'As shown\\[1\\] and here \\[2\\], or \\[a\\].',
      'A claim \\[citation needed\\] here.',
      'Thai Place ($$) and Chez Acme ($$)',
      'from $$ to $$ per person',
      'range: $$ - $$'
    ]) {
      expect(tex(src), src).toEqual([]);
    }
    // Real display math with the same delimiters still is.
    expect(tex('\\[ 42 \\]')).toEqual(['42']);
    expect(tex('\\[ x \\]')).toEqual(['x']);
    expect(tex('\\[E = mc^2\\]')).toEqual(['E = mc^2']);
    expect(tex('$$x$$')).toEqual(['x']);
  });

  test('nested brackets, nested delimiters and TeX line breaks', () => {
    expect(tex('\\[ \\left[ a + b \\right] \\]')).toEqual(['\\left[ a + b \\right]']);
    expect(tex('\\( f(g(x)) \\)')).toEqual(['f(g(x))']);
    expect(tex('\\[ \\text{where \\(x\\) is real} \\]')).toEqual(['\\text{where \\(x\\) is real}']);
    expect(tex('\\( \\text{a \\(b\\) c} \\)')).toEqual(['\\text{a \\(b\\) c}']);
    expect(tex('\\[ a \\\\[2pt] b \\]')).toEqual(['a \\\\[2pt] b']);
    expect(tex('$$ \\text{costs \\$5} $$')).toEqual(['\\text{costs \\$5}']);
  });

  test('multi-line display math is one formula, whatever its lines start with', () => {
    const src = 'So:\n\\[\nx = a\n+ b\n- c\n\\]\nand then';
    const p = prepareMath(src);
    expect(p.segments.map((s) => s.tex)).toEqual(['x = a\n+ b\n- c']);
    expect(p.text.split('\n')).toHaveLength(3); // the formula is now one inline marker
  });

  test('unclosed delimiters: left alone when final, held as source while streaming', () => {
    const src = 'The variance is \\[ \\sigma^2 = \\frac{1}{n';
    expect(prepareMath(src).segments).toEqual([]);
    expect(prepareMath(src).text).toBe(src);

    const s = prepareMath(src, { streaming: true });
    expect(s.segments).toEqual([
      { source: '\\[ \\sigma^2 = \\frac{1}{n', tex: '', display: true, pending: true }
    ]);
    // A paragraph break ends the search: math never spans one.
    expect(prepareMath('a \\( b\n\nc \\) d', { streaming: true }).segments).toEqual([]);
    expect(prepareMath('a \\( b\n \t\nc \\) d').segments).toEqual([]);
    // A stray closer is nothing.
    expect(tex('a \\) b \\] c')).toEqual([]);
  });

  test('oversized and empty formulas are left as text', () => {
    expect(tex('\\(' + 'x'.repeat(MAX_TEX_LENGTH + 1) + '\\)')).toEqual([]);
    expect(tex('\\(' + 'x'.repeat(100) + '\\)')).toHaveLength(1);
    expect(tex('\\(\\) and \\[ \\] and $$$$ and $$ $$')).toEqual([]);
  });

  test('a marker already in the text cannot collide', () => {
    const src = 'odd \u2063m0\u2063 text and \\(x\\)';
    const p = prepareMath(src);
    expect(p.marker).toBe('\u2063\u2063m');
    expect(text(html(src, { katex: false }))).toBe(src);
  });
});


/** Every real tag in rendered HTML (text is entity-escaped, so `<` in text never matches). */
const tags = (markup: string) =>
  [...markup.matchAll(/<([a-zA-Z][\w:-]*)((?:\s[^<>]*)?)>/g)].map((m) => ({
    name: m[1].toLowerCase(),
    attrs: m[2]
  }));

test.describe('markdown renderer (static)', () => {
  test('renders the three delimiters with KaTeX, inline and display', () => {
    const out = html(REPLY);
    expect(out.match(/class="katex"/g)).toHaveLength(3);
    expect(out.match(/class="katex-display"/g)).toHaveLength(1);
    expect(out).toContain(
      String.raw`<annotation encoding="application/x-tex">\sigma^2 = \frac{1}{n}\sum_i (x_i - \bar{x})^2</annotation>`
    );
    // Single-dollar text is not math and not mangled.
    expect(text(out)).toContain(String.raw`inline $e^{i\pi}+1=0$.`);
    // Each formula carries its source for copy.
    expect(out).toContain(String.raw`<span class="math-src" aria-hidden="true">\( 17 + 25 \)</span>`);
    expect(out).not.toContain('data-math-index');
  });

  test('before KaTeX loads, the reader sees the exact source', () => {
    const out = html(REPLY, { katex: false });
    expect(text(out)).toBe(REPLY);
    expect(out).not.toContain('katex');
    expect(out.match(/class="math-wrap[^"]* math-raw"/g)).toHaveLength(3);
  });

  test('delimiters that are not math keep their backslashes (the old ( and [ rewrite is gone)', () => {
    for (const src of [
      'Open C:\\[temp\\] first.',
      'As shown\\[1\\] and \\[citation needed\\].',
      'a stray \\) and \\] and \\( and \\[',
      'unclosed \\( x + y'
    ]) {
      expect(text(html(src)), src).toBe(src);
      expect(text(html(src, { katex: false })), src).toBe(src);
    }
    // Other markdown escapes still work as markdown.
    expect(text(html('2 \\* 3 \\_ 4 \\# 5'))).toBe('2 * 3 _ 4 # 5');
  });

  test('prices, code spans and fences are untouched', () => {
    expect(text(html('It costs $5 and $10.'))).toBe('It costs $5 and $10.');
    const out = html('Write `\\(x\\)` or:\n\n```\n\\[ y \\]\n$$ z $$\n```\n\nfor \\(x\\).');
    expect(out).toContain('<code>\\(x\\)</code>');
    expect(out).toContain('\\[ y \\]\n$$ z $$\n</code></pre>');
    expect(out.match(/class="katex"/g)).toHaveLength(1);
  });

  test('math works inside emphasis, lists, quotes, headings, links and table cells', () => {
    const src = [
      '# Heading \\(h\\)',
      '',
      '**bold \\(b\\)** and *\\(i\\)* and [link \\(l\\)](https://example.org)',
      '',
      '- item \\(a\\)',
      '  \\[ x = 1 \\]',
      '',
      '> quoted \\[ q^2 \\]',
      '',
      '| n | value |',
      '|---|---|',
      '| 1 | \\( |x| \\) |'
    ].join('\n');
    const out = html(src);
    expect(out.match(/class="katex"/g)).toHaveLength(8);
    expect(out).toMatch(/<h1>Heading <span class="math-wrap">/);
    expect(out).toMatch(/<strong>bold <span class="math-wrap">/);
    expect(out).toMatch(/<em><span class="math-wrap">/);
    expect(out).toMatch(/<a href="https:\/\/example.org">link <span class="math-wrap">/);
    expect(out).toMatch(/<li>item <span class="math-wrap">/);
    expect(out).toMatch(/<blockquote>\s*<p>quoted <span class="math-wrap math-wrap-display">/);
    // A formula with `|` stays in its table cell.
    expect(out.match(/<td>/g)).toHaveLength(2);
    expect(out).toContain('<annotation encoding="application/x-tex">|x|</annotation>');
  });

  test('ordinary formulas of every shape are typeset, none is refused', () => {
    // Guards the safety checks against false alarms (KaTeX's stretchy SVGs are 400em wide).
    const formulas = [
      String.raw`\frac{1}{\sqrt{2\pi\sigma^2}} e^{-\frac{(x-\mu)^2}{2\sigma^2}}`,
      String.raw`\sqrt[3]{x^2 + y^2} + \sqrt{\frac{a}{b}}`,
      String.raw`\overbrace{a + b + c}^{n} + \underbrace{x + y}_{m}`,
      String.raw`A \xrightarrow{f} B \xleftarrow[g]{h} C \Longrightarrow D`,
      String.raw`\widehat{xyz} + \widetilde{abc} + \overline{AB} + \vec{v} + \overrightarrow{AB}`,
      String.raw`\int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}`,
      String.raw`\sum_{k=0}^{n} \binom{n}{k} x^k y^{n-k} = (x+y)^n`,
      String.raw`\lim_{n\to\infty} \left(1 + \frac{1}{n}\right)^n = e`,
      String.raw`f(x) = \begin{cases} x^2 & x \ge 0 \\ -x & x < 0 \end{cases}`,
      String.raw`\begin{aligned} a &= b + c \\ &= d + e \end{aligned}`,
      String.raw`\begin{bmatrix} 1 & 2 & 3 \\ 4 & 5 & 6 \\ 7 & 8 & 9 \end{bmatrix}^{-1}`,
      String.raw`\mathbb{R}^n,\ \mathcal{L},\ \mathfrak{g},\ \mathbf{x},\ \mathrm{d}x,\ \mathsf{T},\ \mathtt{code}`,
      String.raw`\nabla \cdot \vec{E} = \frac{\rho}{\varepsilon_0} \quad \text{(Gauss's law)}`,
      String.raw`\boxed{E = mc^2} \qquad \color{blue}{x} + \textcolor{red}{y}`,
      String.raw`\left\lfloor \frac{n}{2} \right\rfloor + \left\| \mathbf{v} \right\|_2 + \Biggl( x \Biggr)`,
      String.raw`P(A \mid B) = \frac{P(B \mid A)\,P(A)}{P(B)} \approx 0.42 \times 10^{-3}`,
      String.raw`\hat{\beta} = (X^\top X)^{-1} X^\top y, \quad \bar{x} = \tfrac{1}{n}\textstyle\sum_i x_i`,
      String.raw`\text{速度} = \frac{\text{距離}}{\text{時間}}`,
      String.raw`x \\[2ex] y \hspace{2em} z \rule{1em}{0.4pt} \kern 3pt \quad \!\!`
    ];
    for (const f of formulas) {
      for (const src of [`\\( ${f} \\)`, `\\[ ${f} \\]`]) {
        const out = html(src);
        expect(out.match(/class="katex"/g) ?? [], src).toHaveLength(1);
        expect(out, src).not.toContain('math-raw');
      }
    }
  });

  test('a formula KaTeX cannot render falls back to its source, and the rest still renders', () => {
    const src = 'Bad: \\( \\frac{1}{ \\) and \\[ \\notacommand{x} \\] but good: \\( x^2 \\).';
    const out = html(src);
    expect(out.match(/class="katex"/g)).toHaveLength(1);
    expect(out).not.toContain('katex-error');
    expect(out).not.toContain('#cc0000');
    expect(out).toMatch(
      /<span class="math-wrap math-raw" title="[^"]+">\\\( \\frac\{1\}\{ \\\)<\/span>/
    );
    expect(out).toMatch(
      /<span class="math-wrap math-wrap-display math-raw" title="[^"]+">\\\[ \\notacommand\{x\} \\\]<\/span>/
    );
  });

  test('while streaming, half a formula is held as source text, then renders', () => {
    const full = 'Variance: \\[ \\sigma_i^2 = a*b*c \\{x\\} \\] done';
    const closed = full.indexOf('\\]') + 2;
    for (let cut = 1; cut < full.length; cut++) {
      const part = full.slice(0, cut);
      const out = html(part, { streaming: true });
      // Nothing is typeset until the closer arrives.
      expect(out.includes('class="katex'), part).toBe(cut >= closed);
      // No emphasis from a*b*c and no `\{` → `{`: the source is shown as written.
      // (Markdown drops a paragraph's trailing space, so compare trimmed.)
      if (cut < closed) expect(text(out).trimEnd(), part).toBe(part.trimEnd());
    }
    expect(html(full, { streaming: true })).toContain('class="katex-display"');
  });

  test('untrusted TeX cannot make links, images, attributes or markup', () => {
    const hostile = [
      String.raw`\( \href{javascript:alert(1)}{click} \)`,
      String.raw`\( \href{https://example.org/x}{click} \)`,
      String.raw`\( \url{https://example.org/x} \)`,
      String.raw`\( \includegraphics[width=1em]{https://example.org/p.png} \)`,
      String.raw`\( \htmlClass{fixed inset-0}{x} \htmlId{root}{y} \)`,
      String.raw`\( \htmlStyle{position:fixed;inset:0}{x} \htmlData{a=b}{y} \)`,
      String.raw`\( \text{<img src=x onerror=alert(1)><script>alert(1)</script>} \)`,
      String.raw`\[ x < y \text{</span><a href="https://example.org">a</a>} \]`,
      String.raw`\( \unicode{x3c}script\unicode{x3e} \)`,
      String.raw`\( \char"3c img src=x \char"3e \)`
    ];
    const allowedAttrs = /^(class|style|aria-hidden|title|xmlns|encoding|mathvariant|stretchy|fence|separator|lspace|rspace|accent|minsize|maxsize|width|height|viewBox|preserveAspectRatio|d|columnalign|columnspacing|rowspacing|displaystyle|scriptlevel|mathcolor|mathbackground|voffset|linethickness|rowalign|form|movablelimits|largeop|symmetric)$/i;
    for (const katex of [true, false]) {
      for (const src of hostile) {
        const out = html(src, { katex });
        for (const tag of tags(out)) {
          expect(tag.name, src).not.toMatch(
            /^(a|img|script|iframe|object|embed|form|link|style|base|meta|input|button|video|audio|foreignobject|use|image)$/
          );
          for (const attr of tag.attrs.matchAll(/\s([\w:-]+)="[^"]*"/g)) {
            expect(attr[1], `${src} → <${tag.name}${tag.attrs}>`).toMatch(allowedAttrs);
          }
          expect(tag.attrs, src).not.toMatch(/position\s*:|inset|url\(|expression|javascript:/i);
          expect(tag.attrs, src).not.toMatch(/class="[^"]*\b(fixed|inset-0)\b/);
        }
      }
    }
    // The trusted-only commands are refused outright: the reader sees the source.
    for (const src of hostile.slice(0, 6)) {
      expect(text(html(src)), src).toBe(src);
      expect(html(src), src).not.toContain('class="katex"');
    }
  });

  test('oversized boxes are capped and runaway formulas fail fast', () => {
    // Sizes an agent writes are capped at maxSize (40em). Look at the typeset part
    // only: the hidden source and the MathML annotation repeat the TeX as text.
    const typesetPart = (markup: string) =>
      markup.replace(/<annotation.*?<\/annotation>/gs, '').replace(/<span class="math-src".*?<\/span>/gs, '');
    for (const src of [
      String.raw`\( \rule{9999em}{9999em} \)`,
      String.raw`\( \kern{9999em} x \hspace{9999em} \mkern9999mu \)`,
      String.raw`\( x \\[9999em] y \)`
    ]) {
      const out = typesetPart(html(src));
      expect(out, src).toContain('class="katex"');
      for (const m of out.matchAll(/(-?[\d.]+)em/g)) {
        expect(Math.abs(Number(m[1])), `${src}: ${m[0]}`).toBeLessThanOrEqual(40);
      }
    }
    // What maxSize misses is caught on the way out: no box beyond 200em, or the
    // formula is shown as source instead.
    for (const src of [
      String.raw`\( \raisebox{9999em}{x} \)`,
      String.raw`\( \raisebox{-9999em}{x} \)`,
      String.raw`\[ a \raisebox{300em}{x} b \]`
    ]) {
      const out = html(src);
      expect(out, src).not.toContain('class="katex"');
      expect(text(out), src).toBe(src);
    }
    // A big but honest formula is fine.
    const rows = Array.from({ length: 40 }, (_, i) => `a_{${i}} & b_{${i}}`).join(String.raw` \\ `);
    expect(html(String.raw`\[ \begin{pmatrix} ${rows} \end{pmatrix} \]`)).toContain('class="katex"');

    const started = Date.now();
    const bombs = [
      // A macro that multiplies itself: stopped by maxExpand.
      String.raw`\( \def\a{\a\a}\a \)`,
      String.raw`\( \newcommand{\b}{\b\b\b}\b \)`,
      // Deep nesting: KaTeX gives up or overflows the stack; either way it's caught.
      '\\( ' + '{'.repeat(4000) + 'x' + '}'.repeat(4000) + ' \\)',
      '\\( ' + '\\frac{1}{'.repeat(900) + 'x' + '}'.repeat(900) + ' \\)',
      '\\( ' + '\\sqrt{'.repeat(1200) + 'x' + '}'.repeat(1200) + ' \\)',
      // Long but flat.
      '\\( ' + 'x^2 + '.repeat(1500) + 'y \\)'
    ];
    for (const src of bombs) {
      const out = html(src);
      // Either typeset or shown as source, never an exception and never empty.
      expect(out.includes('class="katex"') || out.includes('math-raw'), src.slice(0, 40)).toBe(true);
    }
    expect(html(bombs[0])).toContain('math-raw');
    expect(Date.now() - started).toBeLessThan(20_000);

    // A macro defined in one formula does not leak into the next.
    const leak = html(String.raw`\( \gdef\leak{LEAKED} \leak \) then \( \leak \)`);
    expect(leak.match(/class="katex"/g) ?? []).toHaveLength(1);
    expect(leak.match(/math-raw/g) ?? []).toHaveLength(1);
  });
});

/* ── the real app ─────────────────────────────────────────────────────────── */

const sse = (frames: object[]) =>
  'retry: 3600000\n\n' + frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join('');

/** Open the app with `content` already streamed in as one assistant reply. */
async function openWithReply(page: Page, content: string) {
  await page.route('**/api/stream*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: sse([
        { type: 'session_init', session_id: 'e2e-math' },
        { type: 'content', content, role: 'assistant', node: 'agent' },
        { type: 'complete', outcome: 'complete' }
      ])
    })
  );
  await page.goto('/');
  return page.locator('.markdown-content').last();
}

/**
 * How the display formula's fraction is laid out: the numerator sits above the
 * denominator with a visible rule between them. Flattened KaTeX boxes fail this.
 */
const fractionLayout = (formula: Locator) =>
  formula.evaluate((el) => {
    const parts = [...el.querySelectorAll('.mfrac .vlist > span > .mord')].map((n) =>
      n.getBoundingClientRect()
    );
    const line = el.querySelector('.mfrac .frac-line')!.getBoundingClientRect();
    const ys = parts.map((r) => r.top + r.height / 2);
    return {
      stacked: Math.max(...ys) - Math.min(...ys),
      ruleWidth: line.width,
      ruleBetween: line.top > Math.min(...ys) && line.top < Math.max(...ys)
    };
  });

test.describe('math in the app', () => {
  test('chat: a streamed reply renders math, prices and code stay as written, nothing is fetched off-machine', async ({
    page,
    baseURL
  }) => {
    const requests: string[] = [];
    page.on('request', (r) => requests.push(r.url()));
    const mathAssets = () => requests.filter((u) => /mathKit|KaTeX_/.test(u));

    await page.goto('/');
    const input = page.getByPlaceholder('Send a message...');
    await expect(input).toBeVisible();
    // No math on screen: KaTeX's stylesheet and fonts have not been downloaded.
    expect(mathAssets()).toEqual([]);

    // The stub agent echoes this back token by token, so the formulas arrive in pieces.
    const message =
      String.raw`The result of \( 17 + 25 \) is \( 42 \). Variance: \[ \sigma^2 = \frac{1}{n}\sum_i (x_i - \bar{x})^2 \] It costs $5 and $10, see ` +
      '`\\(x\\)`' +
      ' END';
    // The app drops a message sent before its session has started, so send until
    // the user bubble shows (it is added the moment a send is accepted).
    await expect(async () => {
      await input.fill(message);
      await input.press('Enter');
      await expect(page.locator('p.whitespace-pre-wrap').first()).toBeVisible({ timeout: 1_000 });
    }).toPass({ timeout: 20_000 });

    const reply = page.locator('.markdown-content').filter({ hasText: 'stub reply:' });
    await expect(reply).toContainText('END', { timeout: 30_000 });
    await expect(reply.locator('.katex')).toHaveCount(3);
    await expect(reply.locator('.katex-display')).toHaveCount(1);
    await expect(reply.locator('.math-raw')).toHaveCount(0);
    // Not math, and not mangled.
    await expect(reply).toContainText('It costs $5 and $10, see');
    await expect(reply.locator('code').filter({ hasText: '\\(x\\)' })).toHaveCount(1);
    // The fraction is really laid out: numerator above denominator.
    const fraction = await fractionLayout(reply.locator('.katex-display'));
    expect(fraction.stacked).toBeGreaterThan(8);
    expect(fraction.ruleWidth).toBeGreaterThan(4);
    expect(fraction.ruleBetween).toBe(true);

    // KaTeX came from this server (bundled in the wheel), with its fonts.
    await expect.poll(() => mathAssets().some((u) => /mathKit-[\w-]+\.css/.test(u))).toBe(true);
    await expect.poll(() => mathAssets().some((u) => /KaTeX_Main-Regular-[\w-]+\.woff2/.test(u))).toBe(true);
    expect(await page.evaluate(() => document.fonts.check('16px KaTeX_Main'))).toBe(true);
    for (const url of requests) {
      expect(url.startsWith(baseURL!) || url.startsWith('data:') || url.startsWith('blob:'), url).toBe(true);
    }
  });

  test('canvas: markdown items render math', async ({ page }) => {
    await page.route('**/api/canvas/items', (route) =>
      route.request().method() === 'GET'
        ? route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify([
              { id: 'math-1', type: 'markdown', title: 'Model fit', data: REPLY + ' Budget: $5 and $10.' }
            ])
          })
        : route.continue()
    );
    // The stub agent has no canvas tools, so the tab is off by default.
    await page.route('**/api/config', async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), show_canvas: true } });
    });
    await page.goto('/');
    await page.getByRole('button', { name: /Canvas/ }).click();
    const item = page.locator('.markdown-content').filter({ hasText: 'Budget' });
    await expect(item.locator('.katex')).toHaveCount(3);
    await expect(item.locator('.katex-display')).toHaveCount(1);
    await expect(item).toContainText('Budget: $5 and $10.');
    await expect(item).toContainText(String.raw`inline $e^{i\pi}+1=0$.`);
  });

  test.describe('copy', () => {
    test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

    test('copying a reply gives the TeX source, not glyphs', async ({ page }) => {
      const reply = await openWithReply(page, REPLY);
      await expect(reply.locator('.katex')).toHaveCount(3);
      await reply.evaluate((el) => {
        const range = document.createRange();
        range.selectNodeContents(el);
        const selection = window.getSelection()!;
        selection.removeAllRanges();
        selection.addRange(range);
      });
      await page.keyboard.press('ControlOrMeta+C');
      const copied = await page.evaluate(() => navigator.clipboard.readText());
      expect(copied.replace(/\s+/g, ' ').trim()).toBe(REPLY);
    });
  });

  test('print and dark mode: formulas keep their layout and follow the text color', async ({ page }) => {
    const reply = await openWithReply(page, REPLY);
    await expect(reply.locator('.katex')).toHaveCount(3);
    const styles = () =>
      reply.evaluate((el) => ({
        source: getComputedStyle(el.querySelector('.math-src')!).display,
        sameColor: getComputedStyle(el.querySelector('.katex')!).color === getComputedStyle(el).color
      }));
    const formula = reply.locator('.katex-display');

    const screen = await fractionLayout(formula);
    expect(screen.stacked).toBeGreaterThan(8);
    expect(screen.ruleBetween).toBe(true);
    expect((await styles()).sameColor).toBe(true);

    // The print stylesheet flattens the app's layout; KaTeX's own boxes must survive it.
    await page.emulateMedia({ media: 'print' });
    const print = await fractionLayout(formula);
    expect(print.ruleBetween).toBe(true);
    expect(Math.abs(print.stacked - screen.stacked)).toBeLessThan(2);
    expect(Math.abs(print.ruleWidth - screen.ruleWidth)).toBeLessThan(2);
    // The copy-only source text stays out of the printout.
    expect((await styles()).source).toBe('none');

    await page.emulateMedia({ media: 'screen', colorScheme: 'dark' });
    expect((await styles()).sameColor).toBe(true);
  });

  test('if KaTeX cannot be loaded, the reply shows the exact source', async ({ page }) => {
    await page.route(/\/assets\/mathKit-[\w-]+\.js/, (route) => route.abort());
    const reply = await openWithReply(page, REPLY);
    await expect(reply.locator('.math-raw')).toHaveCount(3);
    await expect(reply.locator('.katex')).toHaveCount(0);
    expect(((await reply.textContent()) ?? '').trim()).toBe(REPLY);
  });

  test('hostile formulas cannot navigate, inject or cover the page', async ({ page }) => {
    let dialogs = 0;
    page.on('dialog', (d) => {
      dialogs++;
      void d.dismiss();
    });
    const content = [
      String.raw`\( \href{javascript:alert(1)}{click me} \)`,
      String.raw`\( \htmlStyle{position:fixed;inset:0;background:red}{cover} \)`,
      String.raw`\( \includegraphics{https://example.org/p.png} \)`,
      String.raw`\( \text{<img src=x onerror=alert(1)>} \)`,
      String.raw`\( \rule{9999em}{9999em} \)`,
      String.raw`\( \def\a{\a\a}\a \)`,
      '\\( ' + '\\sqrt{'.repeat(1200) + 'x' + '}'.repeat(1200) + ' \\)',
      String.raw`fine: \( x^2 \) OK`
    ].join('\n\n');
    const requests: string[] = [];
    page.on('request', (r) => requests.push(r.url()));

    const started = Date.now();
    const reply = await openWithReply(page, content);
    await expect(reply).toContainText('OK');
    await expect(reply.locator('.katex').last()).toBeVisible();
    expect(Date.now() - started).toBeLessThan(15_000);

    await expect(reply.locator('a, img, script, iframe, [onerror], [href], [src]')).toHaveCount(0);
    expect(requests.filter((u) => u.includes('example.org'))).toEqual([]);
    expect(dialogs).toBe(0);
    expect(new URL(page.url()).pathname).toBe('/');
    // Nothing is fixed over the page: the composer is still the thing under its own center.
    const input = page.getByPlaceholder('Send a message...');
    await input.click({ trial: true, timeout: 5_000 });
    const fixed = await reply.evaluate((el) =>
      [...el.querySelectorAll('*')].filter((n) => getComputedStyle(n).position === 'fixed').length
    );
    expect(fixed).toBe(0);
  });
});
