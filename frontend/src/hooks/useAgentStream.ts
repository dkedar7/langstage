/**
 * WebSocket connection + event dispatch hook.
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
} from "../types";

const STORAGE_KEY = "cowork-dash-session";

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

  // Reconnect key — changing this re-runs the WebSocket useEffect
  const [reconnectKey, setReconnectKey] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const contentBufferRef = useRef("");
  const rafRef = useRef<number | null>(null);

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
  }, [messages, todos, tokenUsage, usageHistory, isStreaming]);

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

  const dispatch = useCallback(
    (event: AgentEvent) => {
      switch (event.type) {
        case "session_init":
          sessionIdRef.current = event.session_id;
          break;

        case "tool_start":
          // Flush content before tool events
          if (contentBufferRef.current) flushContentBuffer();

          setMessages((prev) => {
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
          // Attach extraction to the most recent running tool call with matching name
          setMessages((prev) => {
            const updated = [...prev];
            for (let i = updated.length - 1; i >= 0; i--) {
              const msg = updated[i];
              const tcIdx = msg.toolCalls.findIndex(
                (tc) => tc.name === event.tool_name && tc.status === "running"
              );
              if (tcIdx >= 0) {
                const newTcs = [...msg.toolCalls];
                newTcs[tcIdx] = {
                  ...newTcs[tcIdx],
                  extraction: {
                    extracted_type: event.extracted_type,
                    data: event.data,
                  },
                };
                updated[i] = { ...msg, toolCalls: newTcs };
                return updated;
              }
            }
            return prev;
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
          setIsStreaming(false);
          setInterrupt(event as InterruptEventMsg);
          break;

        case "complete": {
          setIsStreaming(false);
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
      }
    },
    [flushContentBuffer]
  );

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    let url = `${protocol}//${window.location.host}/ws/chat`;
    if (sessionIdRef.current) {
      url += `?session_id=${encodeURIComponent(sessionIdRef.current)}`;
    }
    const ws = new WebSocket(url);

    ws.onopen = () => setConnectionStatus("connected");
    ws.onclose = () => setConnectionStatus("disconnected");
    ws.onerror = () => setConnectionStatus("error");

    ws.onmessage = (e) => {
      const event: AgentEvent = JSON.parse(e.data);

      if (event.type === "content") {
        contentBufferRef.current += event.content;
        if (!rafRef.current) {
          rafRef.current = requestAnimationFrame(() => {
            flushContentBuffer();
            rafRef.current = null;
          });
        }
      } else {
        if (contentBufferRef.current) flushContentBuffer();
        dispatch(event);
      }
    };

    wsRef.current = ws;
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      ws.close();
    };
  }, [dispatch, flushContentBuffer, reconnectKey]);

  const sendMessage = useCallback(
    (content: string, meta?: { cwd?: string }) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

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
      wsRef.current.send(
        JSON.stringify({ type: "message", content, cwd: meta?.cwd })
      );
      setIsStreaming(true);
    },
    []
  );

  const respondToInterrupt = useCallback(
    (decisions: Decision[]) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

      wsRef.current.send(
        JSON.stringify({ type: "interrupt_response", decisions })
      );
      setInterrupt(null);
      setIsStreaming(true);
    },
    []
  );

  const cancelStream = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    // Flush any buffered content before cancelling
    if (contentBufferRef.current) flushContentBuffer();
    wsRef.current.send(JSON.stringify({ type: "cancel" }));
    // isStreaming will be set to false when the "cancelled" event arrives
  }, [flushContentBuffer]);

  const resetSession = useCallback(() => {
    // Clean up backend session
    const oldSessionId = sessionIdRef.current;
    if (oldSessionId) {
      fetch(`/api/session/${encodeURIComponent(oldSessionId)}`, {
        method: "DELETE",
      }).catch(() => {});
    }

    // Close current WebSocket
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    // Clear persisted state
    localStorage.removeItem(STORAGE_KEY);

    // Reset all state
    sessionIdRef.current = null;
    setMessages([]);
    setTodos([]);
    setTokenUsage({ input: 0, output: 0, total: 0 });
    setUsageHistory([]);
    turnCounterRef.current = 0;
    setIsStreaming(false);
    setInterrupt(null);
    setFileChanges([]);
    contentBufferRef.current = "";

    // Reconnect with a fresh session
    setReconnectKey((k) => k + 1);
  }, []);

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
  };
}
