import { useState, useRef, useEffect } from "react";
import { ArrowUp, Square, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";
import { MessageBubble } from "./MessageBubble";

interface ChatPanelProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  welcomeMessage: string;
  onSend: (content: string) => void;
  onCancel: () => void;
}

export function ChatPanel({
  messages,
  isStreaming,
  welcomeMessage,
  onSend,
  onCancel,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setInput("");
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  return (
    <div className="flex flex-col h-full bg-[var(--color-surface)]">
      {/* Message list */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-5 py-6 space-y-5">
          {/* Welcome message */}
          {messages.length === 0 && welcomeMessage && (
            <div className="py-12">
              <div className="text-sm text-[var(--color-text-secondary)] markdown-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {welcomeMessage}
                </ReactMarkdown>
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              showLabel={i === 0 || messages[i - 1].role !== msg.role}
            />
          ))}

          {isStreaming && (
            <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
              <Loader2 size={12} className="animate-spin" />
              Agent is working...
            </div>
          )}
        </div>
      </div>

      {/* Input area */}
      <div className="border-t border-[var(--color-border)]">
        <div className="max-w-2xl mx-auto px-5 py-3">
          <div className="flex items-end gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 focus-within:border-[var(--color-text-muted)] transition-colors">
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Send a message..."
              rows={1}
              className="flex-1 resize-none bg-transparent text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none leading-relaxed"
            />
            {isStreaming ? (
              <button
                onClick={onCancel}
                className="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-md bg-[var(--color-text)] text-[var(--color-surface)] hover:opacity-80 transition-opacity"
                title="Stop"
              >
                <Square size={12} fill="currentColor" />
              </button>
            ) : (
              <button
                onClick={handleSubmit}
                disabled={!input.trim()}
                className="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-md bg-[var(--color-text)] text-[var(--color-surface)] disabled:opacity-20 disabled:cursor-not-allowed hover:opacity-80 transition-opacity"
                title="Send"
              >
                <ArrowUp size={14} strokeWidth={2.5} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
