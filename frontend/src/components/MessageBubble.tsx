import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Sparkles, User } from "lucide-react";
import type { ChatMessage } from "../types";
import { ToolCallCard } from "./ToolCallCard";

interface MessageBubbleProps {
  message: ChatMessage;
  agentName?: string;
  iconUrl?: string;
  showLabel?: boolean;
}

function formatTime(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDuration(ms: number): string {
  const v = Math.max(0, ms); // never render a negative duration (clock skew on instant turns)
  if (v < 1000) return `${Math.round(v)}ms`;
  if (v < 60_000) return `${(v / 1000).toFixed(1)}s`;
  const mins = Math.floor(v / 60_000);
  const secs = Math.round((v % 60_000) / 1000);
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

export function MessageBubble({ message, agentName = "Agent", iconUrl, showLabel = true }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isAssistant = message.role === "assistant";
  const label = isUser ? "You" : agentName;

  // Live elapsed timer while streaming, final duration after complete
  const liveElapsed = useElapsed(message.startedAt, message.isStreaming);
  const displayDuration = message.durationMs ?? liveElapsed;
  // Only show a duration once there's a real, positive measurement — an instant
  // turn can report 0 / a sub-ms negative from clock skew, which used to render
  // as "-1ms". (gh: UI modernization)
  const showDuration = isAssistant && displayDuration != null && displayDuration >= 1;

  // System messages render as small, light centered inline text (no avatar/label)
  if (isSystem) {
    return (
      <div className="py-1 text-center">
        <p className="text-xs italic text-[var(--color-text-muted)]">
          {message.content}
        </p>
      </div>
    );
  }

  return (
    <div className="group flex gap-3">
      {/* Avatar column — a spacer keeps grouped continuation turns aligned */}
      <div className="flex-shrink-0 w-7">
        {showLabel &&
          (isUser ? (
            <div className="w-7 h-7 rounded-lg bg-[var(--color-surface-3)] flex items-center justify-center">
              <User size={14} className="text-[var(--color-text-secondary)]" />
            </div>
          ) : iconUrl ? (
            <img src={iconUrl} alt="" className="w-7 h-7 rounded-lg object-cover" />
          ) : (
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-primary-dark)] flex items-center justify-center">
              <Sparkles size={14} className="text-white" />
            </div>
          ))}
      </div>

      {/* Body */}
      <div className="flex-1 min-w-0">
        {showLabel && (
          <div className="flex items-baseline gap-2 mb-1 h-7">
            <span className="text-[13px] font-semibold text-[var(--color-text)] leading-7">
              {label}
            </span>
            {message.timestamp && (
              <span className="text-[10px] text-[var(--color-text-muted)] tabular-nums opacity-0 group-hover:opacity-100 transition-opacity">
                {formatTime(message.timestamp)}
              </span>
            )}
            {showDuration && (
              <span className="text-[10px] text-[var(--color-text-muted)] tabular-nums">
                {formatDuration(displayDuration!)}
              </span>
            )}
          </div>
        )}

        {/* Content */}
        {message.content && (
          <div className="text-[15px] text-[var(--color-text)] leading-relaxed">
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
    </div>
  );
}
