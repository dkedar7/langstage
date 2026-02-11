import { useState, useRef, useEffect, useCallback } from "react";
import { ArrowUp, Square, Loader2, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";
import { MessageBubble } from "./MessageBubble";
import { useSlashCommands } from "../hooks/useSlashCommands";
import { SlashCommandMenu } from "./SlashCommandMenu";

interface ChatPanelProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  welcomeMessage: string;
  agentName: string;
  iconUrl?: string;
  saveWorkflowPrompt?: string;
  runWorkflowPrompt?: string;
  createWorkflowPrompt?: string;
  onSend: (content: string) => void;
  onCancel: () => void;
}

export function ChatPanel({
  messages,
  isStreaming,
  welcomeMessage,
  agentName,
  iconUrl,
  saveWorkflowPrompt,
  runWorkflowPrompt,
  createWorkflowPrompt,
  onSend,
  onCancel,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isNearBottomRef = useRef(true);
  const slashCommands = useSlashCommands({ saveWorkflowPrompt, runWorkflowPrompt, createWorkflowPrompt });

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    // Consider "near bottom" if within 80px of the bottom
    isNearBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);

  useEffect(() => {
    if (isNearBottomRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const sendAndReset = (message: string) => {
    isNearBottomRef.current = true;
    onSend(message);
    setInput("");
    slashCommands.reset();
    if (inputRef.current) inputRef.current.style.height = "auto";
  };

  const handleSubmit = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;
    const expanded = slashCommands.tryExecute(trimmed);
    sendAndReset(expanded ?? trimmed);
  };

  const handleSlashSelect = (index: number) => {
    const { expanded, newInput } = slashCommands.handleSelect(index);
    if (expanded) {
      sendAndReset(expanded);
    } else if (newInput !== null) {
      setInput(newInput);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Slash command menu gets first dibs on navigation keys
    if (slashCommands.handleKeyDown(e)) {
      // Enter/Tab consumed by menu → execute selection
      if (e.key === "Enter" || e.key === "Tab") {
        handleSlashSelect(slashCommands.selectedIndex);
      }
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setInput(val);
    slashCommands.handleInputChange(val);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  return (
    <div className="flex flex-col h-full bg-[var(--color-surface)]">
      {/* Message list */}
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-5 py-6 space-y-5">
          {/* Welcome state */}
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 gap-5">
              {iconUrl ? (
                <img
                  src={iconUrl}
                  alt=""
                  className="w-12 h-12 rounded-xl object-cover shadow-sm"
                />
              ) : (
                <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-primary-dark)] flex items-center justify-center shadow-sm">
                  <Sparkles size={22} className="text-white" />
                </div>
              )}
              {welcomeMessage ? (
                <div className="text-sm text-[var(--color-text-secondary)] markdown-content text-center max-w-md">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {welcomeMessage}
                  </ReactMarkdown>
                </div>
              ) : (
                <div className="text-center">
                  <p className="text-sm font-medium text-[var(--color-text)]">
                    What can I help you with?
                  </p>
                  <p className="text-xs text-[var(--color-text-muted)] mt-1">
                    Ask a question to get started
                  </p>
                </div>
              )}
            </div>
          )}

          {messages.map((msg, i) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              agentName={agentName}
              showLabel={i === 0 || messages[i - 1].role !== msg.role}
            />
          ))}

          {isStreaming && messages.length > 0 && (
            <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
              <span className="flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-primary)] animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-primary)] animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-primary)] animate-bounce" style={{ animationDelay: "300ms" }} />
              </span>
              {agentName} is working...
            </div>
          )}
        </div>
      </div>

      {/* Input area */}
      <div data-print-hide className="border-t border-[var(--color-border)]">
        <div className="max-w-4xl mx-auto px-5 py-3 relative">
          <SlashCommandMenu
            showCommandMenu={slashCommands.showCommandMenu}
            filteredCommands={slashCommands.filteredCommands}
            showWorkflowPicker={slashCommands.showWorkflowPicker}
            filteredWorkflowFiles={slashCommands.filteredWorkflowFiles}
            isLoadingWorkflows={slashCommands.isLoadingWorkflows}
            selectedIndex={slashCommands.selectedIndex}
            onSelect={handleSlashSelect}
            onHover={slashCommands.setSelectedIndex}
          />
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
          <div className="text-center mt-1.5">
            <span className="text-[10px] text-[var(--color-text-muted)]">
              <kbd className="px-1 py-0.5 rounded bg-[var(--color-surface-3)] text-[9px] font-mono">Enter</kbd> to send, <kbd className="px-1 py-0.5 rounded bg-[var(--color-surface-3)] text-[9px] font-mono">Shift+Enter</kbd> for new line, <kbd className="px-1 py-0.5 rounded bg-[var(--color-surface-3)] text-[9px] font-mono">/</kbd> for commands
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
