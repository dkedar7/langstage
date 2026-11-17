/**
 * SSE connection + event dispatch hook.
 * Replaces WebSocket with EventSource (Server-Sent Events) for streaming
 * and fetch() for sending messages/interrupts/cancellations.
 *
 * Handles buffered content streaming with requestAnimationFrame batching.
 * Persists session state to localStorage for survival across page refresh.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import type {
  AgentEvent,
  ChatMessage,
  ToolCall,
  TodoItem,
  TokenUsage,
  TurnUsage,
  InterruptEventMsg,
  Decision,
  ConnectionStatus,
  ConversationDetail,
  ViewedConversation,
} from "../types";
import { extractionTargetId, findExtractionTarget } from "../extraction";
import { errorDetail, transcriptToMessages } from "../conversations";

/** How often a conversation shown read-only is re-read while it is busy elsewhere. */
const VIEW_REFRESH_MS = 2500;

const STORAGE_KEY = "langstage-session";

/**
 * Names this window to the server (gh #236). One connection reads a session's
 * event stream at a time; with this id the server can tell this window coming back
 * (a reload, a reconnect after the connection dropped) from a second window, which
 * it refuses.
 * sessionStorage survives a reload and is not shared with other tabs.
 */
const CLIENT_KEY = "langstage-client";

function newClientId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function windowClientId(): string {
  try {
    const saved = sessionStorage.getItem(CLIENT_KEY);
    if (saved && /^[A-Za-z0-9_-]{1,64}$/.test(saved)) return saved;
    const id = newClientId();
    sessionStorage.setItem(CLIENT_KEY, id);
    return id;
  } catch {
    return newClientId(); // no sessionStorage: a reload then counts as a new window
  }
}

const CLIENT_ID = windowClientId();

/** How long to wait before reconnecting a stream that dropped. */
const STREAM_RETRY_MS = 1500;

/** Frames that only a running turn sends. */
const TURN_FRAMES = new Set(["content", "reasoning", "tool_start", "tool_end"]);

interface PersistedState {
  sessionId: string | null;
  messages: ChatMessage[];
  todos: TodoItem[];
  tokenUsage: TokenUsage;
  usageHistory: TurnUsage[];
  turnCounter: number;
}

function loadPersistedState(): PersistedState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PersistedState;
  } catch {
    return null;
  }
}

function savePersistedState(state: PersistedState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // localStorage full or unavailable — silently ignore
  }
}

let messageIdCounter = 0;
function nextId() {
  return `msg-${++messageIdCounter}`;
}

export function useAgentStream() {
  // Restore persisted state on first render
  const persisted = useRef(loadPersistedState());
  const initial = persisted.current;

  const [messages, setMessages] = useState<ChatMessage[]>(
    initial?.messages ?? []
  );
  const [isStreaming, setIsStreaming] = useState(false);
  const [interrupt, setInterrupt] = useState<InterruptEventMsg | null>(null);
  const [todos, setTodos] = useState<TodoItem[]>(initial?.todos ?? []);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");
  const [tokenUsage, setTokenUsage] = useState<TokenUsage>(
    initial?.tokenUsage ?? { input: 0, output: 0, total: 0 }
  );
  const [usageHistory, setUsageHistory] = useState<TurnUsage[]>(
    initial?.usageHistory ?? []
  );
  const turnCounterRef = useRef(initial?.turnCounter ?? 0);
  const [fileChanges, setFileChanges] = useState<
    { event: string; path: string }[]
  >([]);

  // Session ID for backend thread continuity
  const sessionIdRef = useRef<string | null>(initial?.sessionId ?? null);
  // The same id as state, for the History menu to mark the current conversation.
  const [sessionId, setSessionId] = useState<string | null>(initial?.sessionId ?? null);
  // A past conversation shown read-only because it is busy elsewhere (gh #232).
  const [viewing, setViewing] = useState<ViewedConversation | null>(null);
  const viewingRef = useRef<ViewedConversation | null>(null);
  viewingRef.current = viewing;

  // Reconnect key — changing this re-runs the SSE useEffect
  const [reconnectKey, setReconnectKey] = useState(0);

  const eventSourceRef = useRef<EventSource | null>(null);
  const contentBufferRef = useRef("");
  const reasoningBufferRef = useRef("");
  const rafRef = useRef<number | null>(null);
  // The most recent tool_end, for pairing the extraction frame that follows it.
  const lastEndedToolRef = useRef<{ id: string; name: string } | null>(null);

  // Sync messageIdCounter to avoid collisions with restored messages
  if (initial?.messages?.length) {
    const maxId = initial.messages.reduce((max, m) => {
      const num = parseInt(m.id.replace("msg-", ""), 10);
      return isNaN(num) ? max : Math.max(max, num);
    }, 0);
    if (maxId > messageIdCounter) messageIdCounter = maxId;
  }

  // --- Debounced localStorage persistence ---
  const persistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isStreamingRef = useRef(false);
  isStreamingRef.current = isStreaming;

  useEffect(() => {
    // Don't persist while streaming — wait until stream completes
    if (isStreaming) return;
    // A read-only copy of another conversation is not this window's to save. The
    // saved state is shared by every tab of the browser, and the window that has the
    // conversation open still needs its own there for a reload (gh #236).
    if (viewing) return;

    if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
    persistTimerRef.current = setTimeout(() => {
      savePersistedState({
        sessionId: sessionIdRef.current,
        messages,
        todos,
        tokenUsage,
        usageHistory,
        turnCounter: turnCounterRef.current,
      });
    }, 500);

    return () => {
      if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
    };
  }, [messages, todos, tokenUsage, usageHistory, isStreaming, viewing]);

  const flushContentBuffer = useCallback(() => {
    const buffered = contentBufferRef.current;
    if (!buffered) return;
    contentBufferRef.current = "";

    setMessages((prev) => {
      const last = prev[prev.length - 1];
      // Append to existing assistant message only if it's a pure-content
      // message (no tool calls). Once a message has tool calls, new content
      // starts a fresh message so the timeline stays interleaved.
      if (
        last &&
        last.role === "assistant" &&
        last.isStreaming &&
        last.toolCalls.length === 0
      ) {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...last,
          content: last.content + buffered,
        };
        return updated;
      }
      // New assistant message
      const now = Date.now();
      return [
        ...prev,
        {
          id: nextId(),
          role: "assistant",
          content: buffered,
          toolCalls: [],
          isStreaming: true,
          timestamp: now,
          startedAt: now,
        },
      ];
    });
  }, []);

  // Reasoning deltas are batched like content. They open the turn's message (or
  // fill one that has no answer yet), so the "Thinking" block renders above the
  // answer that follows; reasoning after answer text or a tool call starts a new
  // message for the same reason (gh #196).
  const flushReasoningBuffer = useCallback(() => {
    const buffered = reasoningBufferRef.current;
    if (!buffered) return;
    reasoningBufferRef.current = "";

    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (
        last &&
        last.role === "assistant" &&
        last.isStreaming &&
        last.toolCalls.length === 0 &&
        !last.content
      ) {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...last,
          reasoning: (last.reasoning ?? "") + buffered,
        };
        return updated;
      }
      const now = Date.now();
      return [
        ...prev,
        {
          id: nextId(),
          role: "assistant",
          content: "",
          reasoning: buffered,
          toolCalls: [],
          isStreaming: true,
          timestamp: now,
          startedAt: now,
        },
      ];
    });
  }, []);

  // Flush whichever stream buffer is pending. Only one is ever non-empty: a frame
  // of the other kind flushes it first, which keeps reasoning and answer in order.
  const flushBuffers = useCallback(() => {
    flushReasoningBuffer();
    flushContentBuffer();
  }, [flushReasoningBuffer, flushContentBuffer]);

  // POST one user message to the session's thread.
  const postChat = useCallback((content: string, cwd?: string) => {
    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionIdRef.current, content, cwd }),
    })
      .then(async (res) => {
        if (res.ok) return;
        // Refused (e.g. the session is gone): say so instead of spinning forever.
        const reason = await errorDetail(res);
        setIsStreaming(false);
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: "assistant",
            content: `Error: the message was not sent (${reason})`,
            toolCalls: [],
            timestamp: Date.now(),
          },
        ]);
      })
      .catch((err) => {
        console.error("Failed to send message:", err);
        setIsStreaming(false);
      });
  }, []);

  // A message sent before the stream has announced its session (right after page
  // load, after New, or just after reopening a conversation) waits here until it
  // has. It used to be dropped without a word, or posted to a session the server
  // did not have yet.
  const pendingSendRef = useRef<{ content: string; cwd?: string } | null>(null);
  const streamReadyRef = useRef(false);

  // Whether a turn is in progress on this window's stream: one it started, or one
  // it found running after a reload. `isStreaming` says the same a render later;
  // frames arrive faster than that.
  const turnActiveRef = useRef(false);
  // The stream was re-attached while a turn was running (a reload, or a reconnect
  // after the connection dropped): frames written to the old connection may never
  // have been shown, so the transcript is re-read when the turn ends (gh #236).
  const resyncRef = useRef(false);
  // What to do when the server ends or refuses this window's stream; set below,
  // once the session helpers it needs exist. False when there is nothing to do
  // but try again.
  const onStreamLostRef = useRef<(why: "refused" | "superseded") => boolean>(() => false);
  const refusedRetriesRef = useRef(0);

  const resyncTranscript = useCallback(async () => {
    const id = sessionIdRef.current;
    if (!id) return;
    try {
      const res = await fetch(`/api/conversations/${encodeURIComponent(id)}`);
      if (!res.ok) return; // e.g. a checkpointer History can't read: keep what we have
      const detail: ConversationDetail = await res.json();
      // Only if nothing has moved on while this was in flight.
      if (sessionIdRef.current !== id || viewingRef.current || turnActiveRef.current) return;
      setMessages(transcriptToMessages(detail));
      turnCounterRef.current = detail.messages.filter((m) => m.role === "user").length;
      if (detail.interrupt) setInterrupt(detail.interrupt);
    } catch {
      // Offline: the partial transcript stays.
    }
  }, []);

  const dispatch = useCallback(
    (event: AgentEvent) => {
      switch (event.type) {
        case "session_init": {
          sessionIdRef.current = event.session_id;
          setSessionId(event.session_id);
          streamReadyRef.current = true;
          refusedRetriesRef.current = 0;
          const pending = pendingSendRef.current;
          if (pending) {
            pendingSendRef.current = null;
            postChat(pending.content, pending.cwd);
          }
          break;
        }

        case "tool_start":
          // Flush content before tool events
          if (contentBufferRef.current) flushContentBuffer();

          setMessages((prev) => {
            // A resumed turn re-announces the call it paused in (same id): keep the
            // one card, so its result completes it instead of leaving a spinner.
            if (prev.some((m) => m.toolCalls.some((t) => t.id === event.id))) return prev;
            const last = prev[prev.length - 1];
            const tc: ToolCall = {
              id: event.id,
              name: event.name,
              args: event.args as Record<string, unknown>,
              status: "running",
            };

            if (last && last.role === "assistant") {
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...last,
                toolCalls: [...last.toolCalls, tc],
              };
              return updated;
            }
            const now = Date.now();
            return [
              ...prev,
              {
                id: nextId(),
                role: "assistant",
                content: "",
                toolCalls: [tc],
                isStreaming: true,
                timestamp: now,
                startedAt: now,
              },
            ];
          });
          break;

        case "tool_end":
          // Remembered so the extraction frame that follows can find its call.
          lastEndedToolRef.current = { id: event.id, name: event.name };
          setMessages((prev) => {
            const updated = [...prev];
            for (let i = updated.length - 1; i >= 0; i--) {
              const msg = updated[i];
              const tcIdx = msg.toolCalls.findIndex((tc) => tc.id === event.id);
              if (tcIdx >= 0) {
                const newTcs = [...msg.toolCalls];
                newTcs[tcIdx] = {
                  ...newTcs[tcIdx],
                  status: event.status,
                  result: event.result,
                  errorMessage: event.error_message,
                  durationMs: event.duration_ms,
                };
                updated[i] = { ...msg, toolCalls: newTcs };
                break;
              }
            }
            return updated;
          });
          break;

        case "extraction": {
          // Attach to the tool call it was extracted from, by id. Core emits the
          // frame AFTER that call's tool_end, so the call is usually no longer
          // "running" here (see findExtractionTarget).
          const targetId = extractionTargetId(
            event.id,
            event.tool_name,
            lastEndedToolRef.current
          );
          setMessages((prev) => {
            const hit = findExtractionTarget(prev, event.tool_name, targetId);
            if (!hit) return prev;
            const [i, j] = hit;
            const updated = [...prev];
            const newTcs = [...updated[i].toolCalls];
            newTcs[j] = {
              ...newTcs[j],
              extraction: {
                extracted_type: event.extracted_type,
                data: event.data,
              },
            };
            updated[i] = { ...updated[i], toolCalls: newTcs };
            return updated;
          });

          // Also update persistent todos state
          if (event.extracted_type === "todos") {
            const raw = event.data;
            const rawList: unknown[] = Array.isArray(raw)
              ? raw
              : (raw && typeof raw === "object" && "todos" in (raw as Record<string, unknown>))
                ? ((raw as Record<string, unknown>).todos as unknown[]) ?? []
                : [];
            const items: TodoItem[] = rawList.map((item) => {
              if (item && typeof item === "object") {
                const obj = item as Record<string, unknown>;
                return {
                  content: (obj.content as string) ?? (obj.task as string) ?? "",
                  status:
                    (obj.status as TodoItem["status"]) ??
                    (obj.done === true ? "completed" : obj.done === false ? "pending" : "pending"),
                };
              }
              return { content: String(item), status: "pending" as const };
            });
            setTodos(items);
          }
          break;
        }

        case "interrupt":
          turnActiveRef.current = false;
          setIsStreaming(false);
          setInterrupt(event as InterruptEventMsg);
          break;

        case "complete": {
          turnActiveRef.current = false;
          setIsStreaming(false);
          if (resyncRef.current) {
            resyncRef.current = false;
            void resyncTranscript();
          }
          const now = Date.now();
          setMessages((prev) => {
            if (prev.length === 0) return prev;
            // Mark all streaming messages as done and compute duration
            let changed = false;
            const updated = prev.map((msg) => {
              if (msg.isStreaming) {
                changed = true;
                return {
                  ...msg,
                  isStreaming: false,
                  durationMs: msg.startedAt ? now - msg.startedAt : undefined,
                };
              }
              return msg;
            });
            return changed ? updated : prev;
          });
          break;
        }

        case "error":
          turnActiveRef.current = false;
          resyncRef.current = false;
          setIsStreaming(false);
          setMessages((prev) => [
            ...prev,
            {
              id: nextId(),
              role: "assistant",
              content: `Error: ${event.error}`,
              toolCalls: [],
              timestamp: Date.now(),
            },
          ]);
          break;

        case "usage":
          setTokenUsage((prev) => ({
            input: prev.input + event.input_tokens,
            output: prev.output + event.output_tokens,
            total: prev.total + event.total_tokens,
          }));
          setUsageHistory((prev) => {
            if (prev.length === 0) return prev;
            const updated = [...prev];
            const last = updated[updated.length - 1];
            updated[updated.length - 1] = {
              ...last,
              input: last.input + event.input_tokens,
              output: last.output + event.output_tokens,
              total: last.total + event.total_tokens,
            };
            return updated;
          });
          break;

        case "cancelled": {
          turnActiveRef.current = false;
          resyncRef.current = false;
          setIsStreaming(false);
          const now = Date.now();
          // Mark all streaming messages as done with duration
          setMessages((prev) => {
            const updated = prev.map((msg) =>
              msg.isStreaming
                ? { ...msg, isStreaming: false, durationMs: msg.startedAt ? now - msg.startedAt : undefined }
                : msg
            );
            // Append termination notice
            return [
              ...updated,
              {
                id: nextId(),
                role: "system" as const,
                content: "Task terminated",
                toolCalls: [],
                timestamp: Date.now(),
              },
            ];
          });
          break;
        }

        case "file_changed":
          setFileChanges((prev) => [
            ...prev,
            { event: event.event, path: event.path },
          ]);
          break;

        case "user_message":
          // Injected message from REST endpoint — display as a user bubble
          setMessages((prev) => [
            ...prev,
            {
              id: nextId(),
              role: "user",
              content: event.content,
              toolCalls: [],
              timestamp: Date.now(),
            },
          ]);
          turnCounterRef.current += 1;
          setUsageHistory((prev) => [
            ...prev,
            { turn: turnCounterRef.current, input: 0, output: 0, total: 0 },
          ]);
          turnActiveRef.current = true;
          setIsStreaming(true);
          break;
      }
    },
    [flushContentBuffer, postChat, resyncTranscript]
  );

  // --- SSE Connection ---
  useEffect(() => {
    const params = new URLSearchParams({ client: CLIENT_ID });
    if (sessionIdRef.current) params.set("session_id", sessionIdRef.current);
    const es = new EventSource(`/api/stream?${params}`);

    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    es.onopen = () => setConnectionStatus("connected");
    es.onerror = () => {
      setConnectionStatus("disconnected");
      // A refusal (the server answered, but not with a stream) is not retried by
      // EventSource: another window is reading this session's stream (gh #236).
      const refused = es.readyState === EventSource.CLOSED;
      // Reconnect by hand instead of letting EventSource retry. Its retry reuses the
      // URL it was created with, and a page that started fresh was created without a
      // session id: the server then gave it a brand-new session, the rest of a
      // running turn never arrived, and later messages went to an empty thread.
      es.close();
      // Until the stream is back, a message waits for it instead of being posted to
      // a session the server may no longer have (after a restart).
      streamReadyRef.current = false;
      if (refused && onStreamLostRef.current("refused")) return;
      // A frame written to the connection that dropped is gone, so re-read the
      // transcript when the turn ends.
      if (turnActiveRef.current) resyncRef.current = true;
      retryTimer = setTimeout(() => setReconnectKey((k) => k + 1), STREAM_RETRY_MS);
    };

    const scheduleFlush = () => {
      if (!rafRef.current) {
        rafRef.current = requestAnimationFrame(() => {
          flushBuffers();
          rafRef.current = null;
        });
      }
    };

    es.onmessage = (e) => {
      const event: AgentEvent = JSON.parse(e.data);

      if (event.type === "superseded") {
        // Another connection reads this session now. Close for good: reconnecting
        // would take the stream straight back.
        es.close();
        onStreamLostRef.current("superseded");
        return;
      }
      if (TURN_FRAMES.has(event.type) && !turnActiveRef.current) {
        // A turn this window did not start: the page was reloaded while it ran.
        // Show it as running, and re-read the transcript when it ends, because the
        // frames before the reload went to the old page.
        turnActiveRef.current = true;
        resyncRef.current = true;
        setIsStreaming(true);
      }

      if (event.type === "content") {
        if (reasoningBufferRef.current) flushReasoningBuffer();
        contentBufferRef.current += event.content;
        scheduleFlush();
      } else if (event.type === "reasoning") {
        if (contentBufferRef.current) flushContentBuffer();
        reasoningBufferRef.current += event.content ?? "";
        scheduleFlush();
      } else {
        flushBuffers();
        dispatch(event);
      }
    };

    eventSourceRef.current = es;
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      // Clear the handle too, or a reconnect's scheduleFlush would see it still
      // set and never schedule again.
      rafRef.current = null;
      if (retryTimer) clearTimeout(retryTimer);
      es.close();
    };
  }, [dispatch, flushBuffers, flushContentBuffer, flushReasoningBuffer, reconnectKey]);

  // A reloaded page shows what it last saved, and it saves only between turns (and
  // half a second after one ends). The server may know more: the message that was
  // being answered when the page was reloaded, the reply that arrived just before,
  // an approval the turn is waiting on. Once, on load, catch up with it (gh #236).
  useEffect(() => {
    const id = initial?.sessionId;
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/conversations/${encodeURIComponent(id)}`);
        if (!res.ok) return; // nothing saved yet, or History can't read this checkpointer
        const detail: ConversationDetail = await res.json();
        // Not if the window has moved on, or the conversation turned out to be open
        // in another window (it is then shown read-only instead).
        if (cancelled || sessionIdRef.current !== id || viewingRef.current) return;
        if (turnActiveRef.current) {
          // A turn is already arriving: leave the screen alone until it ends.
          resyncRef.current = true;
          return;
        }
        const turns = (list: { role: string }[]) => list.filter((m) => m.role === "user").length;
        if (turns(detail.messages) > turns(initial?.messages ?? [])) {
          setMessages(transcriptToMessages(detail));
          turnCounterRef.current = turns(detail.messages);
        }
        if (detail.running) {
          // The turn the page was reloaded in is still going: show it as running
          // (with Stop), and re-read the transcript when it ends.
          turnActiveRef.current = true;
          resyncRef.current = true;
          setIsStreaming(true);
        } else if (detail.interrupt) {
          setInterrupt(detail.interrupt);
        }
      } catch {
        // Offline: what was saved in the browser stays.
      }
    })();
    return () => {
      cancelled = true;
    };
    // Once, for the session restored on load.
  }, []);

  // --- Actions via fetch POST ---
  const sendMessage = useCallback(
    (content: string, meta?: { cwd?: string }) => {
      if (viewingRef.current || pendingSendRef.current) return;

      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "user", content, toolCalls: [], timestamp: Date.now() },
      ]);
      turnCounterRef.current += 1;
      const turn = turnCounterRef.current;
      setUsageHistory((prev) => [
        ...prev,
        { turn, input: 0, output: 0, total: 0 },
      ]);
      turnActiveRef.current = true;
      setIsStreaming(true);

      if (streamReadyRef.current) postChat(content, meta?.cwd);
      else pendingSendRef.current = { content, cwd: meta?.cwd };
    },
    [postChat]
  );

  const respondToInterrupt = useCallback(
    (decisions: Decision[]) => {
      if (!sessionIdRef.current) return;

      let pending: InterruptEventMsg | null = null;
      setInterrupt((prev) => {
        pending = prev;
        return null;
      });
      turnActiveRef.current = true;
      setIsStreaming(true);

      fetch("/api/chat/interrupt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionIdRef.current,
          decisions,
        }),
      })
        .then(async (res) => {
          if (res.ok) return;
          // Refused before anything was sent (core #227): the approval is still
          // pending, so bring it back with the reason.
          const body = await res.json().catch(() => null);
          turnActiveRef.current = false;
          setIsStreaming(false);
          setInterrupt(pending);
          setMessages((prev) => [
            ...prev,
            {
              id: nextId(),
              role: "assistant",
              content: `Error: ${body?.detail ?? `answer refused (${res.status})`}`,
              toolCalls: [],
              timestamp: Date.now(),
            },
          ]);
        })
        .catch((err) => {
          console.error("Failed to send interrupt response:", err);
          setIsStreaming(false);
        });
    },
    []
  );

  const cancelStream = useCallback(() => {
    if (!sessionIdRef.current) return;

    // Flush any buffered content before cancelling
    flushBuffers();

    fetch("/api/chat/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionIdRef.current,
      }),
    }).catch((err) => {
      console.error("Failed to cancel stream:", err);
    });
    // isStreaming will be set to false when the "cancelled" event arrives via SSE
  }, [flushBuffers]);

  // Leave the current session and connect a different one: `nextSessionId` to
  // continue an existing thread, or null for a fresh one. The old session is idle
  // here (New and History are both disabled while a turn streams), so dropping it
  // only frees its server-side state; its thread stays in the checkpointer.
  //
  // `keepOld` is for a session another window has: that window is still using the
  // server-side session and the saved state, so neither is touched (gh #236).
  const switchSession = useCallback((nextSessionId: string | null, keepOld = false) => {
    const oldSessionId = sessionIdRef.current;
    if (!keepOld && oldSessionId && oldSessionId !== nextSessionId) {
      fetch(`/api/session/${encodeURIComponent(oldSessionId)}`, {
        method: "DELETE",
      }).catch(() => {});
    }

    // Close current EventSource
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    // Clear persisted state
    if (!keepOld) localStorage.removeItem(STORAGE_KEY);

    // Reset all state
    sessionIdRef.current = nextSessionId;
    setSessionId(nextSessionId);
    setMessages([]);
    setTodos([]);
    setTokenUsage({ input: 0, output: 0, total: 0 });
    setUsageHistory([]);
    turnCounterRef.current = 0;
    setIsStreaming(false);
    setInterrupt(null);
    setFileChanges([]);
    setViewing(null);
    pendingSendRef.current = null;
    streamReadyRef.current = false;
    turnActiveRef.current = false;
    resyncRef.current = false;
    contentBufferRef.current = "";
    reasoningBufferRef.current = "";
    lastEndedToolRef.current = null;

    // Reconnect: with the given session id, or a fresh session
    setReconnectKey((k) => k + 1);
  }, []);

  const resetSession = useCallback(() => switchSession(null), [switchSession]);

  // Reopen a past conversation (gh #232). The server hands it over only when it is
  // free; while a turn is running in it or another window is attached, it is shown
  // read-only instead, so two windows never share (and split) one event stream.
  // Resolves to null, or to the reason it could not be opened.
  //
  // With `takeover` ("Continue here" in a read-only window) a window that merely has
  // the conversation open is told to let go; a running turn is still a refusal.
  const openConversation = useCallback(
    async (threadId: string, takeover = false): Promise<string | null> => {
      if (isStreamingRef.current) return "Stop the current turn first.";
      const path = `/api/conversations/${encodeURIComponent(threadId)}`;
      try {
        let res = await fetch(`${path}/open${takeover ? "?takeover=true" : ""}`, { method: "POST" });
        const busy = res.status === 409;
        if (busy) res = await fetch(path);
        if (!res.ok) return await errorDetail(res);
        const detail: ConversationDetail = await res.json();
        if (isStreamingRef.current) return "Stop the current turn first.";

        if (busy) {
          switchSession(null);
          setMessages(transcriptToMessages(detail));
          setViewing({
            threadId,
            title: detail.title,
            running: detail.running,
            connected: detail.connected,
          });
          return null;
        }

        switchSession(threadId);
        setMessages(transcriptToMessages(detail));
        // The saved state has no timings or token counts; count turns from it.
        turnCounterRef.current = detail.messages.filter((m) => m.role === "user").length;
        // An approval the conversation was waiting on can be answered again.
        setInterrupt(detail.interrupt ?? null);
        return null;
      } catch {
        return "Could not reach the server.";
      }
    },
    [switchSession]
  );

  const continueViewed = useCallback(async (): Promise<string | null> => {
    const current = viewingRef.current;
    return current ? openConversation(current.threadId, true) : null;
  }, [openConversation]);

  // This window's stream was refused, or ended because another connection took it:
  // the conversation is open in another window (gh #236). Show it read-only here,
  // the way History does for a busy conversation, and leave the other window's
  // session and saved state alone.
  const viewElsewhere = useCallback(
    async (threadId: string) => {
      let detail: ConversationDetail | null = null;
      try {
        const res = await fetch(`/api/conversations/${encodeURIComponent(threadId)}`);
        if (res.ok) detail = await res.json();
        // No transcript to show (nothing saved yet, or History can't read this
        // checkpointer): start a fresh conversation instead. Anything else is a
        // server problem: keep trying to connect.
        else if (res.status !== 404 && res.status !== 501) throw new Error("unavailable");
      } catch {
        if (sessionIdRef.current === threadId && !viewingRef.current) {
          setTimeout(() => setReconnectKey((k) => k + 1), STREAM_RETRY_MS);
        }
        return;
      }
      if (sessionIdRef.current !== threadId || viewingRef.current) return; // moved on meanwhile
      switchSession(null, true);
      if (!detail) return;
      setMessages(transcriptToMessages(detail));
      setViewing({
        threadId,
        title: detail.title,
        running: detail.running,
        connected: detail.connected,
      });
    },
    [switchSession]
  );

  onStreamLostRef.current = (why) => {
    const threadId = sessionIdRef.current;
    // Not a conversation another window could have (a fresh session, or the idle
    // one behind a read-only view): an ordinary failure, to be retried.
    if (!threadId || viewingRef.current) return false;
    if (why === "refused" && refusedRetriesRef.current < 1) {
      // Once more first: without sessionStorage a reload looks like a second
      // window until the server has seen the old page's connection close.
      refusedRetriesRef.current += 1;
      setTimeout(() => setReconnectKey((k) => k + 1), 500);
      return true;
    }
    refusedRetriesRef.current = 0;
    void viewElsewhere(threadId);
    return true;
  };

  // Keep a read-only conversation current while it is busy elsewhere.
  const viewedThreadId = viewing && !viewing.gone ? viewing.threadId : null;
  useEffect(() => {
    if (!viewedThreadId) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const res = await fetch(`/api/conversations/${encodeURIComponent(viewedThreadId)}`);
        if (cancelled || viewingRef.current?.threadId !== viewedThreadId) return;
        if (res.status === 404) {
          setViewing((v) => (v && v.threadId === viewedThreadId ? { ...v, gone: true } : v));
          return;
        }
        if (!res.ok) return;
        const detail: ConversationDetail = await res.json();
        if (cancelled || viewingRef.current?.threadId !== viewedThreadId) return;
        setMessages(transcriptToMessages(detail));
        setViewing((v) =>
          v && v.threadId === viewedThreadId
            ? { ...v, title: detail.title, running: detail.running, connected: detail.connected }
            : v
        );
      } catch {
        // Offline for a moment: the next tick tries again.
      }
    };
    const timer = setInterval(refresh, VIEW_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [viewedThreadId]);

  return {
    messages,
    isStreaming,
    interrupt,
    todos,
    tokenUsage,
    usageHistory,
    connectionStatus,
    fileChanges,
    sendMessage,
    respondToInterrupt,
    cancelStream,
    resetSession,
    sessionId,
    viewing,
    openConversation,
    continueViewed,
  };
}
