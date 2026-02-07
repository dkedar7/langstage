import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";
import { ToolCallCard } from "./ToolCallCard";

interface MessageBubbleProps {
  message: ChatMessage;
  showLabel?: boolean;
}

export function MessageBubble({ message, showLabel = true }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const label = isUser ? "YOU" : "AGENT";

  return (
    <div className="group">
      {/* Label — hidden for consecutive messages from the same role */}
      {showLabel && (
        <div className="mb-1">
          <span
            className={`text-[11px] font-semibold tracking-wider uppercase ${
              isUser
                ? "text-[var(--color-text-secondary)]"
                : "text-[var(--color-primary)]"
            }`}
          >
            {label}
          </span>
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
