import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";
import { ToolCallCard } from "./ToolCallCard";

interface MessageBubbleProps {
  message: ChatMessage;
  agentName?: string;
  showLabel?: boolean;
}

function formatTime(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const mins = Math.floor(ms / 60_000);
  const secs = Math.round((ms % 60_000) / 1000);
  return `${mins}m ${secs}s`;
}

function useElapsed(startedAt?: number, isStreaming?: boolean): number | null {
  const [elapsed, setElapsed] = useState<number | null>(null);
  useEffect(() => {
    if (!startedAt || !isStreaming) {
      setElapsed(null);
      return;
    }
    const tick = () => setElapsed(Date.now() - startedAt);
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt, isStreaming]);
  return elapsed;
}

export function MessageBubble({ message, agentName = "Agent", showLabel = true }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isAssistant = message.role === "assistant";
  const label = isUser ? "You" : agentName;

  // Live elapsed timer while streaming, final duration after complete
  const liveElapsed = useElapsed(message.startedAt, message.isStreaming);
  const displayDuration = message.durationMs ?? liveElapsed;

  // System messages render as small, light inline text (no border, no label)
  if (isSystem) {
    return (
      <div className="py-1">
        <p className="text-xs italic text-[var(--color-text-muted)]">
          {message.content}
        </p>
      </div>
    );
  }

  return (
    <div
      className={`group border-l-2 pl-3 ${
        isUser
          ? "border-[var(--color-text-muted)]"
          : "border-[var(--color-primary)]"
      }`}
    >
      {/* Label row */}
      {showLabel && (
        <div className="flex items-center gap-2 mb-1">
          <span
            className={`text-[11px] font-semibold tracking-wider uppercase ${
              isUser
                ? "text-[var(--color-text-secondary)]"
                : "text-[var(--color-primary)]"
            }`}
          >
            {label}
          </span>
          {message.timestamp && (
            <span className="text-[10px] text-[var(--color-text-muted)] tabular-nums opacity-0 group-hover:opacity-100 transition-opacity">
              {formatTime(message.timestamp)}
            </span>
          )}
          {isAssistant && displayDuration != null && (
            <span className="text-[10px] text-[var(--color-text-muted)] tabular-nums">
              {formatDuration(displayDuration)}
            </span>
          )}
        </div>
      )}

      {/* Content */}
      {message.content && (
        <div className="text-sm text-[var(--color-text)] leading-relaxed">
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
      )}

      {/* Tool calls */}
      {message.toolCalls.length > 0 && (
        <div className={`space-y-1.5 ${message.content ? "mt-2" : ""}`}>
          {message.toolCalls.map((tc) => (
            <ToolCallCard key={tc.id} toolCall={tc} />
          ))}
        </div>
      )}
    </div>
  );
}
