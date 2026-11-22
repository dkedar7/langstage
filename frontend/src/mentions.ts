/**
 * `@` mentions of workspace files in the chat input (gh #238).
 *
 * A mention is plain text: the workspace-relative path in backticks, such as
 * `data/sales.csv`. Nothing changes on the wire, and the agent reads the path like
 * any other. Its working directory is the workspace root, so a relative path
 * resolves there with no agent changes.
 */

/** The `@word` being typed at the caret. `start` is the index of the `@`. */
export interface ActiveMention {
  start: number;
  /** End of the token: the next whitespace after the caret, or the end of the text. */
  end: number;
  /** What's typed between the `@` and the caret. */
  query: string;
}

const MAX_QUERY = 200;

/**
 * The mention the caret is in, or null.
 *
 * The `@` must start the text or follow whitespace or an opening bracket or quote,
 * so `ana@example.org` isn't a mention. The query may hold single spaces, so
 * `@q3 draft` is one query and matches `reports/q3/draft.md` (the server wants every
 * word in the path). It stops at a backtick, so an inserted mention doesn't reopen
 * the picker, and at a line break, a tab or two spaces in a row. The picker itself
 * closes when a word after a space leaves no match (gh #245), so prose typed after
 * an `@word` doesn't keep it open.
 */
export function activeMention(text: string, caret: number): ActiveMention | null {
  let i = caret - 1;
  while (i >= 0) {
    const ch = text[i];
    if (ch === "@") break;
    if (ch === "`" || (/\s/.test(ch) && (ch !== " " || text[i - 1] === " "))) return null;
    i--;
  }
  if (i < 0) return null;
  if (i > 0 && !/[\s([{"']/.test(text[i - 1])) return null;
  const query = text.slice(i + 1, caret);
  // A lone `@` followed by a space ("meet @ 5pm") isn't a mention.
  if (query.length > MAX_QUERY || query.startsWith(" ")) return null;
  let end = caret;
  while (end < text.length && !/\s/.test(text[end])) end++;
  return { start: i, end, query };
}

/** A path as mention text: workspace-relative, forward slashes, in backticks. */
export function formatMention(path: string): string {
  const rel = path.replace(/\\/g, "/").replace(/^\/+/, "");
  // A name with a backtick needs a longer fence, padded so it can't touch the content.
  return rel.includes("`") ? "`` " + rel + " ``" : "`" + rel + "`";
}

export interface Edit {
  text: string;
  caret: number;
}

/** Replace the `@query` token with the chosen path, followed by a space. */
export function applyMention(text: string, mention: ActiveMention, path: string): Edit {
  const before = text.slice(0, mention.start);
  const after = text.slice(mention.end);
  const inserted = formatMention(path) + (/^\s/.test(after) ? "" : " ");
  return { text: before + inserted + after, caret: before.length + inserted.length };
}

/**
 * Insert mentions of `paths` at the selection (a drop, or "Mention in chat"),
 * with a space on either side where the text needs one.
 */
export function insertMentions(text: string, selStart: number, selEnd: number, paths: string[]): Edit {
  if (paths.length === 0) return { text, caret: selEnd };
  const before = text.slice(0, selStart);
  const after = text.slice(selEnd);
  const lead = before && !/\s$/.test(before) ? " " : "";
  const trail = /^\s/.test(after) ? "" : " ";
  const inserted = lead + paths.map(formatMention).join(" ") + trail;
  return { text: before + inserted + after, caret: before.length + inserted.length };
}
