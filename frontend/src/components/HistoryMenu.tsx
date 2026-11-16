import { useState, useRef, useEffect, useCallback } from "react";
import { History, Loader2, Trash2 } from "lucide-react";
import type { ConversationList, ConversationSummary } from "../types";
import { errorDetail, relativeTime } from "../conversations";

const PAGE = 50;
/** How often the open list re-reads while the server is still indexing. */
const INDEXING_REFRESH_MS = 1500;

interface HistoryMenuProps {
  /** The session this window is attached to (marked "Current" in the list). */
  currentSessionId: string | null;
  /** The conversation shown read-only, if any (also marked). */
  viewingThreadId: string | null;
  /** A turn is streaming in this window: switching would abandon it. */
  isStreaming: boolean;
  /** Resolves to null, or to the reason the conversation could not be opened. */
  onOpen: (threadId: string) => Promise<string | null>;
  /** The current conversation was deleted: start a fresh one. */
  onCurrentDeleted: () => void;
  /** Tells the parent whether History exists, so New can word its prompt. */
  onAvailability?: (state: { available: boolean; durable: boolean }) => void;
}

/**
 * History: past conversations, read from the server's checkpointer (gh #232).
 * Renders nothing when the checkpointer can't list threads.
 */
export function HistoryMenu({
  currentSessionId,
  viewingThreadId,
  isStreaming,
  onOpen,
  onCurrentDeleted,
  onAvailability,
}: HistoryMenuProps) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ConversationList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [limit, setLimit] = useState(PAGE);
  const [busyId, setBusyId] = useState<string | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const limitRef = useRef(limit);
  limitRef.current = limit;

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        const res = await fetch(`/api/conversations?limit=${limitRef.current}`);
        if (!res.ok) throw new Error(await errorDetail(res));
        const body: ConversationList = await res.json();
        setData(body);
        setError(null);
        onAvailability?.({ available: body.available, durable: body.durable });
      } catch (err) {
        // A background refresh that fails keeps the list that is on screen.
        if (!quiet) setError(err instanceof Error ? err.message : "Could not load conversations.");
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [onAvailability]
  );

  // Learn once whether History exists at all (the button hides when it doesn't).
  useEffect(() => {
    load(true);
  }, [load]);

  // Fresh list each time it opens, and when "Show more" raises the limit.
  useEffect(() => {
    if (open) load();
  }, [open, limit, load]);

  // While the server is still reading a large database, the list fills in.
  useEffect(() => {
    if (!open || !data?.indexing) return;
    const timer = setInterval(() => load(true), INDEXING_REFRESH_MS);
    return () => clearInterval(timer);
  }, [open, data?.indexing, load]);

  // Close on click outside or Escape
  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) setOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  if (data && !data.available) return null;

  const handleOpen = async (conversation: ConversationSummary) => {
    setNotice(null);
    setBusyId(conversation.thread_id);
    const problem = await onOpen(conversation.thread_id);
    setBusyId(null);
    if (problem) {
      setNotice(`Couldn't open it: ${problem}`);
      load(true);
    } else {
      setOpen(false);
    }
  };

  const handleDelete = async (conversation: ConversationSummary) => {
    if (
      !window.confirm(
        `Delete "${conversation.title}"? It is removed from the server for good and can't be recovered.`
      )
    ) {
      return;
    }
    setNotice(null);
    setBusyId(conversation.thread_id);
    try {
      const res = await fetch(`/api/conversations/${encodeURIComponent(conversation.thread_id)}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 404) {
        setNotice(`Couldn't delete it: ${await errorDetail(res)}`);
      } else if (conversation.thread_id === currentSessionId) {
        onCurrentDeleted();
      }
    } catch {
      setNotice("Couldn't delete it: could not reach the server.");
    }
    setBusyId(null);
    load(true);
  };

  const conversations = data?.conversations ?? [];

  return (
    <div className="relative" ref={popoverRef}>
      <button
        onClick={() => {
          setNotice(null);
          setOpen((v) => !v);
        }}
        aria-expanded={open}
        className="flex items-center gap-1 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors cursor-pointer"
        title="Past conversations"
      >
        <History size={10} />
        History
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Past conversations"
          className="absolute right-0 top-full mt-2 w-[360px] max-w-[90vw] rounded-lg shadow-md border border-[var(--color-border)] bg-[var(--color-card)] z-50 text-left"
        >
          <div className="flex items-center justify-between px-4 pt-3 pb-2">
            <span className="text-xs font-medium text-[var(--color-text)]">Past conversations</span>
            {(loading || data?.indexing) && (
              <span className="flex items-center gap-1 text-[10px] text-[var(--color-text-muted)]">
                <Loader2 size={10} className="animate-spin" />
                {data?.indexing ? "Reading older conversations…" : "Loading…"}
              </span>
            )}
          </div>

          {isStreaming && (
            <p className="px-4 pb-2 text-[11px] text-[var(--color-text-muted)]">
              Stop the current turn to switch conversations.
            </p>
          )}
          {notice && (
            <p role="alert" className="px-4 pb-2 text-[11px] text-[var(--color-error)]">
              {notice}
            </p>
          )}

          {error ? (
            <div className="px-4 pb-4 text-xs text-[var(--color-text-secondary)]">
              <p role="alert">Couldn't load conversations: {error}</p>
              <button
                onClick={() => load()}
                className="mt-2 px-2 py-1 rounded border border-[var(--color-border)] hover:bg-[var(--color-surface-3)] cursor-pointer"
              >
                Try again
              </button>
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-4 pb-4 text-xs text-[var(--color-text-muted)]">
              {!data || loading || data.indexing
                ? "Looking for conversations…"
                : "No conversations yet. Once you send a message, it is kept here."}
            </p>
          ) : (
            <ul className="max-h-[60vh] overflow-y-auto pb-1">
              {conversations.map((c) => {
                const isCurrent = c.thread_id === currentSessionId;
                const isViewed = c.thread_id === viewingThreadId;
                const status = isCurrent
                  ? "Current"
                  : isViewed
                    ? "Viewing"
                    : c.running
                      ? "Running"
                      : c.connected
                        ? "Open in another window"
                        : c.paused
                          ? "Waiting for approval"
                          : null;
                return (
                  <li
                    key={c.thread_id}
                    className={`group/row flex items-stretch ${
                      isCurrent || isViewed ? "bg-[var(--color-accent-soft)]" : "hover:bg-[var(--color-surface-3)]"
                    }`}
                  >
                    <button
                      onClick={() => handleOpen(c)}
                      disabled={isCurrent || isStreaming || busyId !== null}
                      aria-current={isCurrent ? "true" : undefined}
                      className="flex-1 min-w-0 text-left pl-4 pr-2 py-2 cursor-pointer disabled:cursor-default"
                    >
                      <span className="block text-xs text-[var(--color-text)] truncate">{c.title}</span>
                      <span className="block text-[10px] text-[var(--color-text-muted)] mt-0.5">
                        {[
                          relativeTime(c.updated_at),
                          `${c.message_count} ${c.message_count === 1 ? "message" : "messages"}`,
                          status,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </button>
                    {data?.can_delete && (
                      <button
                        onClick={() => handleDelete(c)}
                        disabled={c.running || busyId !== null || (isCurrent && isStreaming)}
                        className="px-3 text-[var(--color-text-muted)] hover:text-[var(--color-error)] opacity-0 group-hover/row:opacity-100 focus:opacity-100 transition-opacity cursor-pointer disabled:cursor-not-allowed disabled:hover:text-[var(--color-text-muted)]"
                        title={c.running ? "A turn is running in this conversation" : "Delete conversation"}
                        aria-label={`Delete conversation: ${c.title}`}
                      >
                        {busyId === c.thread_id ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <Trash2 size={12} />
                        )}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {data && data.total > conversations.length && !error && (
            <button
              onClick={() => setLimit((n) => Math.min(n + PAGE, 200))}
              disabled={limit >= 200}
              className="w-full px-4 py-2 text-[11px] text-[var(--color-text-secondary)] border-t border-[var(--color-border)] hover:bg-[var(--color-surface-3)] cursor-pointer disabled:cursor-default disabled:hover:bg-transparent"
            >
              {limit >= 200
                ? `Showing the newest ${conversations.length} of ${data.total}`
                : `Show more (${data.total - conversations.length} older)`}
            </button>
          )}
          {data && !data.durable && !error && (
            <p className="px-4 py-2 text-[10px] text-[var(--color-text-muted)] border-t border-[var(--color-border)]">
              Kept until the server stops: this agent's checkpointer is in memory.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
