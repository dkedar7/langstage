import { useEffect, useRef, useState, useCallback } from "react";
import { X, Loader2, Send, Check, Ban } from "lucide-react";
import type { ChatMessage, Task, ToolCall, Decision } from "../types";
import { MessageBubble } from "./MessageBubble";

interface TaskDetailModalProps {
  taskId: string;
  onClose: () => void;
}

const TERMINAL = new Set(["done", "failed", "cancelled"]);

/** Reduce a task's raw event transcript into chat messages (a compact version
 *  of the live chat reducer) so we can render it with the same MessageBubble. */
function reduceEvents(events: Record<string, unknown>[]): ChatMessage[] {
  const msgs: ChatMessage[] = [];
  let counter = 0;
  const pushAssistant = (): ChatMessage => {
    const m: ChatMessage = { id: `a${counter++}`, role: "assistant", content: "", toolCalls: [] };
    msgs.push(m);
    return m;
  };
  const lastAssistant = (): ChatMessage | null => {
    const m = msgs[msgs.length - 1];
    return m && m.role === "assistant" ? m : null;
  };

  for (const e of events) {
    const type = e.type as string;
    if (type === "content") {
      let m = lastAssistant();
      if (!m || m.toolCalls.length > 0) m = pushAssistant(); // new bubble after tools
      m.content += (e.content as string) || "";
    } else if (type === "tool_start") {
      const m = lastAssistant() || pushAssistant();
      const tc: ToolCall = {
        id: e.id as string,
        name: e.name as string,
        args: (e.args as Record<string, unknown>) || {},
        status: "running",
      };
      m.toolCalls.push(tc);
    } else if (type === "tool_end") {
      for (let i = msgs.length - 1; i >= 0; i--) {
        const tc = msgs[i].toolCalls.find((t) => t.id === e.id);
        if (tc) {
          tc.status = (e.status as ToolCall["status"]) || "success";
          tc.result = e.result as string | undefined;
          tc.errorMessage = (e.error_message as string | null) ?? null;
          tc.durationMs = (e.duration_ms as number | null) ?? null;
          break;
        }
      }
    } else if (type === "extraction") {
      const m = lastAssistant();
      if (m && m.toolCalls.length) {
        m.toolCalls[m.toolCalls.length - 1].extraction = {
          extracted_type: e.extracted_type as string,
          data: e.data,
        };
      }
    }
  }
  return msgs.filter((m) => m.content.trim() || m.toolCalls.length);
}

export function TaskDetailModal({ taskId, onClose }: TaskDetailModalProps) {
  const [task, setTask] = useState<Task | null>(null);
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [followup, setFollowup] = useState("");
  const [busy, setBusy] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [t, ev] = await Promise.all([
        fetch(`/api/tasks/${taskId}`).then((r) => (r.ok ? r.json() : null)),
        fetch(`/api/tasks/${taskId}/events`).then((r) => (r.ok ? r.json() : [])),
      ]);
      setTask(t);
      setEvents(ev);
    } catch (err) {
      console.error("Failed to load task detail:", err);
    }
  }, [taskId]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 1500);
    return () => clearInterval(id);
  }, [refresh]);

  // Autoscroll as new events stream in.
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [events.length]);

  const post = async (path: string, body: unknown) => {
    setBusy(true);
    try {
      await fetch(`/api/tasks/${taskId}/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const respond = (decisions: Decision[]) => post("resume", { decisions });
  const sendFollowup = async () => {
    if (!followup.trim()) return;
    const msg = followup.trim();
    setFollowup("");
    await post("message", { message: msg });
  };

  const messages = reduceEvents(events);
  const isReview = task?.state === "review_needed";
  const isTerminal = task ? TERMINAL.has(task.state) : false;
  const actionRequests =
    (task?.interrupt?.action_requests as Array<Record<string, unknown>>) || [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-[min(720px,92vw)] h-[min(80vh,720px)] flex flex-col rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 h-12 border-b border-[var(--color-border)] shrink-0">
          <div className="min-w-0">
            <div className="text-sm font-medium text-[var(--color-text)] truncate">
              {task?.title || "Task"}
            </div>
            <div className="text-[11px] text-[var(--color-text-muted)] flex items-center gap-1.5">
              {task && !isTerminal && <Loader2 size={11} className="animate-spin" />}
              {task?.state || "loading…"}
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-[var(--color-surface-3)] text-[var(--color-text-secondary)]">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div ref={bodyRef} className="flex-1 overflow-y-auto p-4 space-y-3">
          {task?.prompt && (
            <MessageBubble
              message={{ id: "prompt", role: "user", content: task.prompt, toolCalls: [] }}
              showLabel={false}
            />
          )}
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} agentName="Task agent" />
          ))}
          {task?.error && <div className="text-xs text-red-500">{task.error}</div>}
          {messages.length === 0 && !task?.error && (
            <div className="text-xs text-[var(--color-text-muted)]">
              {isTerminal ? "No stream output." : "Waiting for the agent…"}
            </div>
          )}
        </div>

        {/* Review gate */}
        {isReview && (
          <div className="px-4 py-3 border-t border-[var(--color-border)] bg-[var(--color-surface-2)] shrink-0">
            <div className="text-[11px] text-[var(--color-text-muted)] mb-2">
              This task is paused for your approval.
            </div>
            <div className="flex gap-2">
              <button
                disabled={busy}
                onClick={() => respond(actionRequests.map(() => ({ type: "approve" })))}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-emerald-600 text-white disabled:opacity-40 hover:opacity-90"
              >
                <Check size={13} /> Approve
              </button>
              <button
                disabled={busy}
                onClick={() => respond(actionRequests.map(() => ({ type: "reject" })))}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-red-600 text-white disabled:opacity-40 hover:opacity-90"
              >
                <Ban size={13} /> Reject
              </button>
            </div>
          </div>
        )}

        {/* Follow-up (talk back to a finished task) */}
        {isTerminal && task?.state !== "cancelled" && (
          <div className="px-4 py-3 border-t border-[var(--color-border)] shrink-0">
            <div className="flex gap-2">
              <input
                className="flex-1 px-2.5 py-1.5 text-xs rounded-md bg-[var(--color-surface-2)] border border-[var(--color-border)] text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-primary)]"
                placeholder="Send a follow-up to this task…"
                value={followup}
                onChange={(e) => setFollowup(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendFollowup()}
                disabled={busy}
              />
              <button
                onClick={sendFollowup}
                disabled={busy || !followup.trim()}
                className="px-2.5 py-1.5 rounded-md bg-[var(--color-primary)] text-white disabled:opacity-40 hover:opacity-90"
              >
                <Send size={13} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
