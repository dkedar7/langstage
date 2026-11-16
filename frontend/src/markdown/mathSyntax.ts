/**
 * Finds TeX math in an agent's markdown (gh #233).
 *
 * Models write math as `\( … \)`, `\[ … \]` and `$$ … $$`. CommonMark reads `\(`
 * and `\[` as backslash escapes, so the formula used to show as plain text with its
 * delimiters rewritten to `(` and `[`. This pre-pass lifts each formula out of the
 * markdown before it is parsed and leaves a marker in its place; `mathPlugins.ts`
 * turns the marker back into either rendered math or the exact source.
 *
 * What it will not touch:
 *  - anything the markdown parser itself reads as code (spans, fenced and indented
 *    blocks), raw HTML and link definitions. The ranges come from a real parse, not
 *    a regex guess;
 *  - a single `$`: "$5 and $10" is money, never math;
 *  - text that only looks like a delimiter: `\[1\]` and `\[citation needed\]`
 *    (markdown-escaped brackets from converted web pages), `C:\[temp\]` and
 *    `C:\Users\(old\)` (paths), "($$) and ($$)" (price tiers).
 *
 * Pure and DOM-free so it can be unit-tested in Node.
 */
import { fromMarkdown } from "mdast-util-from-markdown";

export interface MathSegment {
  /** What the agent wrote, delimiters included. */
  source: string;
  /** The TeX between the delimiters. */
  tex: string;
  /** Display (block) math: `\[ … \]` and `$$ … $$`. */
  display: boolean;
  /** An opener whose closer hasn't arrived yet (a reply still streaming). Shown as source. */
  pending: boolean;
}

export interface PreparedMath {
  /** The markdown with each formula replaced by `marker + index + MARKER_END`. */
  text: string;
  segments: MathSegment[];
  marker: string;
}

/** Ends a marker. U+2063 (invisible separator) is not markdown syntax, whitespace or punctuation. */
export const MARKER_END = "\u2063";

/** A formula longer than this is left as text: nobody writes one, and KaTeX shouldn't be handed it. */
export const MAX_TEX_LENGTH = 10_000;

const CANDIDATE = /\\[([]|\$\$/;

/** Cheap check: could this text contain math at all? */
export function hasMathCandidate(src: string): boolean {
  return CANDIDATE.test(src);
}

type Range = [number, number];

interface MdNode {
  type: string;
  children?: MdNode[];
  position?: { start: { offset?: number }; end: { offset?: number } };
}

/** Where the parser sees code, raw HTML or a link definition: math syntax there is literal. */
function protectedRanges(src: string): Range[] {
  const out: Range[] = [];
  const walk = (node: MdNode) => {
    if (
      node.type === "code" ||
      node.type === "inlineCode" ||
      node.type === "html" ||
      node.type === "definition"
    ) {
      const start = node.position?.start.offset;
      const end = node.position?.end.offset;
      if (start !== undefined && end !== undefined) out.push([start, end]);
      return;
    }
    for (const child of node.children ?? []) walk(child);
  };
  walk(fromMarkdown(src) as MdNode);
  return out.sort((a, b) => a[0] - b[0]);
}

const ALNUM = /[A-Za-z0-9]/;
const LETTER = /[A-Za-z]/;

/**
 * `\(` and `\[` open math unless they sit inside a path: straight after a letter or
 * digit (`C:\Users\(old\)`, `data\[1\]`) or after a drive letter (`C:\[temp\]`).
 */
function openerAllowed(src: string, at: number): boolean {
  const prev = src[at - 1];
  if (prev === undefined) return true;
  if (ALNUM.test(prev)) return false;
  if (prev === ":" && LETTER.test(src[at - 2] ?? "") && !ALNUM.test(src[at - 3] ?? " ")) {
    return false;
  }
  return true;
}

/** Is the line break at `at` followed by a blank line? Math never spans a paragraph break. */
function blankLineAfter(src: string, at: number): boolean {
  let j = at + 1;
  while (src[j] === " " || src[j] === "\t" || src[j] === "\r") j++;
  return src[j] === "\n";
}

type Match = { end: number; tex: string } | "pending" | null;

/** From a `\(` or `\[` at `open`, find its closer. `limit` is where protected text starts. */
function matchBackslash(src: string, open: number, kind: "(" | "[", limit: number): Match {
  const close = kind === "(" ? ")" : "]";
  let depth = 0;
  let j = open + 2;
  while (j < limit) {
    const c = src[j];
    if (c === "\\") {
      const d = src[j + 1];
      if (d === close) {
        if (depth === 0) return { end: j + 2, tex: src.slice(open + 2, j) };
        depth--;
      } else if (d === kind) {
        depth++; // \text{ … \( x \) … } nests
      } else if (d === "\n") {
        j++;
        continue;
      }
      j += 2; // any other command or escape, `\\` included
      continue;
    }
    if (c === "\n" && blankLineAfter(src, j)) return null;
    j++;
  }
  return limit >= src.length ? "pending" : null;
}

/** From a `$$` at `open`, find the closing `$$` (a run of exactly two). */
function matchDollars(src: string, open: number, limit: number): Match {
  let j = open + 2;
  while (j < limit) {
    const c = src[j];
    if (c === "\\") {
      j += src[j + 1] === "\n" ? 1 : 2;
      continue;
    }
    if (c === "$") {
      let k = j;
      while (src[k] === "$") k++;
      if (k - j === 2) return { end: k, tex: src.slice(open + 2, j) };
      j = k; // `$` or `$$$`: part of the formula
      continue;
    }
    if (c === "\n" && blankLineAfter(src, j)) return null;
    j++;
  }
  return limit >= src.length ? "pending" : null;
}

const MATH_SIGN = /[\\^_=+*<>{}|0-9]/;

/** Does the text between a matched pair of delimiters read as a formula? */
function plausible(tex: string, kind: "(" | "[" | "$"): boolean {
  const t = tex.trim();
  if (!t || tex.length > MAX_TEX_LENGTH) return false;
  if (kind === "(") return true; // `\(x\)`, `\(mg\)`: inline math is whatever is inside
  // Display delimiters also turn up around plain words: `\[citation needed\]`,
  // `C:\[temp\]`, "($$) and ($$)". Require something to typeset, and not just words.
  if (!/[A-Za-z0-9\\]/.test(t)) return false;
  if (/[A-Za-z]{2,}/.test(t) && !MATH_SIGN.test(t)) return false;
  // `\[1\]`, `\[a\]`: a footnote or citation mark with escaped brackets.
  if (kind === "[" && t === tex && /^(\d{1,4}|[A-Za-z])$/.test(t)) return false;
  return true;
}

export interface PrepareOptions {
  /**
   * The text is still arriving. An opener with no closer yet is held back as source
   * text (so half a formula isn't read as markdown) until the closer shows up.
   */
  streaming?: boolean;
}

/** Lift the formulas out of `src`. Text with no math comes back unchanged. */
export function prepareMath(src: string, options: PrepareOptions = {}): PreparedMath {
  const segments: MathSegment[] = [];
  if (!hasMathCandidate(src)) return { text: src, segments, marker: "" };

  let marker = "\u2063m";
  while (src.includes(marker)) marker = "\u2063" + marker;

  const ranges = protectedRanges(src);
  const n = src.length;
  let out = "";
  let last = 0;
  let i = 0;
  let r = 0;

  const take = (open: number, kind: "(" | "[" | "$", limit: number): number | null => {
    const m = kind === "$" ? matchDollars(src, open, limit) : matchBackslash(src, open, kind, limit);
    if (m === null) return null;
    let end: number;
    let segment: MathSegment;
    if (m === "pending") {
      if (!options.streaming) return null;
      end = n;
      segment = { source: src.slice(open), tex: "", display: kind !== "(", pending: true };
    } else {
      if (!plausible(m.tex, kind)) return null;
      end = m.end;
      segment = {
        source: src.slice(open, m.end),
        tex: m.tex.trim(),
        display: kind !== "(",
        pending: false,
      };
    }
    out += src.slice(last, open) + marker + segments.length + MARKER_END;
    segments.push(segment);
    last = end;
    return end;
  };

  while (i < n) {
    while (r < ranges.length && ranges[r][1] <= i) r++;
    if (r < ranges.length && ranges[r][0] <= i) {
      i = ranges[r][1];
      continue;
    }
    const limit = r < ranges.length ? ranges[r][0] : n;
    const c = src[i];
    if (c === "\\") {
      const next = src[i + 1];
      if ((next === "(" || next === "[") && openerAllowed(src, i)) {
        const end = take(i, next, limit);
        if (end !== null) {
          i = end;
          continue;
        }
      }
      i += 2; // an escape: `\$`, `\\`, or a delimiter that didn't open math
      continue;
    }
    if (c === "$") {
      let k = i;
      while (src[k] === "$") k++;
      if (k - i === 2) {
        const end = take(i, "$", limit);
        if (end !== null) {
          i = end;
          continue;
        }
      }
      i = k;
      continue;
    }
    i++;
  }

  if (!segments.length) return { text: src, segments, marker: "" };
  out += src.slice(last);
  return { text: out, segments, marker };
}
