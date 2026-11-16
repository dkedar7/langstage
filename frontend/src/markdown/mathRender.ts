/**
 * Typesets the formulas with KaTeX (gh #233). The rehype half of math rendering; it
 * reaches the browser only inside the lazy `mathKit` chunk.
 */
import katex from "katex";
import { fromHtmlIsomorphic } from "hast-util-from-html-isomorphic";
import type { PreparedMath } from "./mathSyntax";

/**
 * KaTeX settings for agent-written math. The text is untrusted, so:
 *  - no trusted commands: `\href`, `\url`, `\includegraphics`, `\htmlClass`, `\htmlId`,
 *    `\htmlStyle` and `\htmlData` are refused (see `typeset`). Nothing an agent
 *    writes becomes a link, an image or an attribute;
 *  - `maxSize`: a `\rule{9999em}{9999em}` can't paint over the page;
 *  - `maxExpand`: a self-expanding macro stops instead of hanging the tab;
 *  - `strict: "ignore"`: non-TeX text (CJK, emoji) renders without console noise.
 * No `macros` object is shared, so a `\gdef` in one formula can't reach the next.
 */
export const KATEX_OPTIONS = {
  maxSize: 40,
  maxExpand: 500,
  strict: "ignore",
} as const;

interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

type Typeset = { html: string } | { error: string };

/** No box in a formula may be placed or sized beyond this many em. */
const MAX_EM = 200;

/**
 * `maxSize` caps most lengths an agent can write, but not all (`\raisebox{9999em}{x}`
 * still shifts its box by 9999em and makes the reply that tall). KaTeX writes every
 * length in em, so check what it produced. Real formulas stay far below the limit:
 * a 50-row matrix is about 60em tall.
 */
function oversized(html: string): boolean {
  const typeset = html
    // The MathML annotation repeats the TeX source as text; it sizes nothing.
    .replace(/<annotation[^>]*>[^<]*<\/annotation>/g, "")
    // KaTeX's own stretchy SVGs (\sqrt, \overbrace, arrows) are always 400em wide
    // and clipped by their box. An agent can't set that width.
    .replace(/<svg[^>]*>/g, "");
  for (const m of typeset.matchAll(/(-?\d+(?:\.\d+)?)em\b/g)) {
    if (Math.abs(Number(m[1])) > MAX_EM) return true;
  }
  return false;
}

// A reply re-renders on every streamed token; its finished formulas don't change.
const cache = new Map<string, Typeset>();
const CACHE_LIMIT = 400;

/**
 * KaTeX's HTML for one formula, or why there isn't any. All-or-nothing: KaTeX's own
 * soft failures (an unknown command in red, a refused `\href` printed as text) count
 * as failure, so the reader gets either real math or exactly what the agent wrote.
 */
function typeset(tex: string, display: boolean): Typeset {
  const key = (display ? "d" : "i") + tex;
  const hit = cache.get(key);
  if (hit) return hit;
  let result: Typeset;
  let refused = false;
  try {
    const html = katex.renderToString(tex, {
      ...KATEX_OPTIONS,
      displayMode: display,
      throwOnError: true,
      trust: () => {
        refused = true;
        return false;
      },
    });
    if (refused) result = { error: "This TeX command is not available here." };
    else if (oversized(html)) result = { error: "This formula is too large to display." };
    else result = { html };
  } catch (err) {
    // A ParseError, or a RangeError from absurdly deep nesting.
    result = { error: err instanceof Error ? err.message : String(err) };
  }
  if (cache.size >= CACHE_LIMIT) cache.clear();
  cache.set(key, result);
  return result;
}

/**
 * Replace each formula placeholder (`remarkMathSegments` marks them with
 * `data-math-index`) with KaTeX's output.
 *
 *  - Rendered: the typeset formula, plus its source as visually hidden text. The
 *    glyphs are `user-select: none`, so selecting and copying a reply yields
 *    `\( x^2 \)`, not a scramble of glyphs and MathML.
 *  - Not renderable: the placeholder keeps the agent's source, delimiters included,
 *    with the reason as a tooltip.
 */
export function rehypeMath(options: { prepared: PreparedMath }) {
  const { segments } = options.prepared;
  const visit = (node: HastNode) => {
    const index = node.properties?.dataMathIndex;
    if (node.type === "element" && typeof index === "number") {
      const properties = node.properties!;
      delete properties.dataMathIndex;
      const segment = segments[index];
      if (!segment) return;
      const result = typeset(segment.tex, segment.display);
      if ("error" in result) {
        properties.className = [...(properties.className as string[]), "math-raw"];
        properties.title = result.error;
        return;
      }
      node.children = [
        ...(fromHtmlIsomorphic(result.html, { fragment: true }).children as HastNode[]),
        {
          type: "element",
          tagName: "span",
          properties: { className: ["math-src"], ariaHidden: "true" },
          children: [{ type: "text", value: segment.source }],
        },
      ];
      return;
    }
    for (const child of node.children ?? []) visit(child);
  };
  return (tree: HastNode) => visit(tree);
}
