/**
 * The markdown-side plugins behind math rendering (gh #233). See `mathSyntax.ts` for
 * how formulas are found; this file puts them back into the tree as placeholders
 * that show the agent's source. `mathRender.ts` then typesets them.
 *
 * Everything here is small and dependency-free so it lives in the main bundle. KaTeX
 * (script, stylesheet, fonts) is a separate chunk that `Markdown.tsx` loads the first
 * time a message contains math.
 */
import { MARKER_END, type MathSegment, type PreparedMath } from "./mathSyntax";

/* ── `\(`, `\)`, `\[`, `\]` keep their backslash ─────────────────────────────── */

type Code = number | null;
type State = (code: Code) => State | undefined;
interface Effects {
  enter(type: string): void;
  exit(type: string): void;
  consume(code: Code): void;
}

const BACKSLASH = 92;

function tokenizeLiteralDelimiter(effects: Effects, ok: State, nok: State): State {
  const after: State = (code) => {
    if (code === 40 || code === 41 || code === 91 || code === 93) {
      effects.consume(code);
      effects.exit("data");
      return ok;
    }
    return nok(code);
  };
  return (code) => {
    effects.enter("data");
    effects.consume(code);
    return after;
  };
}

const literalDelimiters = {
  text: { [BACKSLASH]: { name: "mathDelimiterLiteral", tokenize: tokenizeLiteralDelimiter } },
};

interface ProcessorLike {
  data(): Record<string, unknown>;
}

/**
 * Markdown would read `\(` as an escaped paren and print `(`. A math delimiter that
 * isn't rendered as math (an unmatched `\[`, a path like `C:\[temp\]`) must still
 * show what the agent wrote, so these four sequences are taken literally. Code is
 * unaffected: escapes never applied there.
 */
export function remarkLiteralMathDelimiters(this: ProcessorLike) {
  const data = this.data();
  const list = (data.micromarkExtensions ?? (data.micromarkExtensions = [])) as unknown[];
  list.push(literalDelimiters);
}

/* ── markers → placeholders ──────────────────────────────────────────────────── */

interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
  data?: Record<string, unknown>;
}

export interface MathSegmentsOptions {
  prepared: PreparedMath;
  /** KaTeX is loaded: mark the placeholders for it. Otherwise they stay as source. */
  render: boolean;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * A `<span class="math-wrap">` holding the formula's source. With `data-math-index`
 * it is waiting for `rehypeMath`; without (KaTeX not loaded, or the formula is still
 * streaming in) the source is what the reader sees.
 */
function placeholder(segment: MathSegment, index: number, render: boolean): MdNode {
  const typeset = render && !segment.pending;
  const className = ["math-wrap"];
  if (segment.display) className.push("math-wrap-display");
  if (!typeset) className.push("math-raw");
  return {
    type: "mathSegment",
    data: {
      hName: "span",
      hProperties: typeset ? { className, dataMathIndex: index } : { className },
      hChildren: [{ type: "text", value: segment.source }],
    },
  };
}

/** Replace each marker `prepareMath` left in the text with its formula's placeholder. */
export function remarkMathSegments(options: MathSegmentsOptions) {
  const { prepared, render } = options;
  const pattern = new RegExp(escapeRegExp(prepared.marker) + "(\\d+)" + MARKER_END, "g");
  const visit = (node: MdNode) => {
    if (!node.children) return;
    const next: MdNode[] = [];
    for (const child of node.children) {
      if (child.type !== "text" || typeof child.value !== "string") {
        visit(child);
        next.push(child);
        continue;
      }
      const value = child.value;
      let last = 0;
      for (const m of value.matchAll(pattern)) {
        const segment = prepared.segments[Number(m[1])];
        if (!segment) continue;
        if (m.index > last) next.push({ type: "text", value: value.slice(last, m.index) });
        next.push(placeholder(segment, Number(m[1]), render));
        last = m.index + m[0].length;
      }
      if (last === 0) next.push(child);
      else if (last < value.length) next.push({ type: "text", value: value.slice(last) });
    }
    node.children = next;
  };
  return (tree: MdNode) => visit(tree);
}
