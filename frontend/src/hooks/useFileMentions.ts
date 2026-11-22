import { useCallback, useEffect, useRef, useState } from "react";
import { activeMention, type ActiveMention } from "../mentions";
import type { FileSearchHit } from "../types";

const DEBOUNCE_MS = 120;
const LIMIT = 20;

/**
 * State for the chat's `@` file picker (gh #238): which mention the caret is in,
 * and the workspace paths that match it, from `GET /api/files/search`.
 */
export function useFileMentions(enabled: boolean) {
  const [mention, setMention] = useState<ActiveMention | null>(null);
  const [results, setResults] = useState<FileSearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const seq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastQuery = useRef<string | null>(null);
  // The picker stays closed for this `@` while the query extends `query`: after
  // Escape (query "") until the caret leaves the mention, and after a word past a
  // space found nothing (gh #245), since typing on can only narrow the match.
  const dismissed = useRef<{ start: number; query: string } | null>(null);

  const close = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    seq.current++;
    lastQuery.current = null;
    setMention(null);
    setResults([]);
    setLoading(false);
    setSelectedIndex(0);
  }, []);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const search = useCallback((query: string, start: number) => {
    if (timer.current) clearTimeout(timer.current);
    const mine = ++seq.current;
    setLoading(true);
    timer.current = setTimeout(async () => {
      try {
        const res = await fetch(`/api/files/search?q=${encodeURIComponent(query)}&limit=${LIMIT}`);
        const data = res.ok ? await res.json() : { results: [] };
        if (mine !== seq.current) return; // a newer keystroke owns the list
        const hits: FileSearchHit[] = data.results ?? [];
        if (!hits.length && query.includes(" ")) {
          // `@sales and then...`: the words after the space are prose, not a path.
          dismissed.current = { start, query };
          close();
          return;
        }
        setResults(hits);
        setSelectedIndex(0);
      } catch {
        if (mine === seq.current) setResults([]);
      } finally {
        if (mine === seq.current) setLoading(false);
      }
    }, DEBOUNCE_MS);
  }, [close]);

  /** Call on every edit and caret move. */
  const update = useCallback(
    (text: string, caret: number) => {
      if (!enabled) return;
      const m = activeMention(text, caret);
      if (!m) {
        dismissed.current = null;
        if (lastQuery.current !== null) close();
        return;
      }
      const d = dismissed.current;
      if (d && d.start === m.start && m.query.startsWith(d.query)) return;
      dismissed.current = null;
      setMention(m);
      if (m.query !== lastQuery.current) {
        lastQuery.current = m.query;
        search(m.query, m.start);
      }
    },
    [enabled, close, search],
  );

  const dismiss = useCallback(() => {
    if (mention) dismissed.current = { start: mention.start, query: "" };
    close();
  }, [mention, close]);

  /**
   * Arrow keys move, Escape closes, Enter and Tab pick. Returns "pick" when the
   * caller should insert `results[selectedIndex]`, true when the key was used, and
   * false when the key is the caller's (the picker is closed, or it has nothing to
   * pick, so Enter still sends).
   */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent): "pick" | boolean => {
      if (!mention) return false;
      const count = results.length;
      switch (e.key) {
        case "ArrowDown":
          if (!count) return false;
          e.preventDefault();
          setSelectedIndex((i) => (i + 1) % count);
          return true;
        case "ArrowUp":
          if (!count) return false;
          e.preventDefault();
          setSelectedIndex((i) => (i - 1 + count) % count);
          return true;
        case "Escape":
          e.preventDefault();
          dismiss();
          return true;
        case "Enter":
        case "Tab":
          if (!count || e.shiftKey) return false;
          e.preventDefault();
          return "pick";
        default:
          return false;
      }
    },
    [mention, results.length, dismiss],
  );

  return {
    open: mention !== null,
    mention,
    results,
    loading,
    selectedIndex,
    setSelectedIndex,
    update,
    close,
    handleKeyDown,
  };
}
