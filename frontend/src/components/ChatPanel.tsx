import { useState, useRef, useEffect, useCallback } from "react";
import { ArrowUp, Eye, Square, Loader2, Sparkles, Upload } from "lucide-react";
import { Markdown } from "./Markdown";
import type { ChatMessage, MentionRequest, ViewedConversation } from "../types";
import { MessageBubble } from "./MessageBubble";
import { useSlashCommands } from "../hooks/useSlashCommands";
import { SlashCommandMenu } from "./SlashCommandMenu";
import { MentionMenu } from "./MentionMenu";
import { useFileMentions } from "../hooks/useFileMentions";
import { applyMention, insertMentions } from "../mentions";

// Generic starter prompts shown on the empty/welcome state — applicable to most
// bring-your-own agents, to defuse the blank-canvas problem. (UI modernization)
const STARTER_PROMPTS = [
  "What can you do?",
  "Summarize the files in my workspace",
  "Help me plan a task step by step",
  "Write a short code example",
];

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
  /** A past conversation shown read-only because it is busy elsewhere (gh #232). */
  viewing?: ViewedConversation | null;
  onContinueViewed?: () => Promise<string | null>;
  onLeaveViewed?: () => void;
  /** `@` mentions and drop-to-upload use the workspace files (off when the Files tab is hidden). gh #238 */
  filesEnabled?: boolean;
  /** Upload a dropped file into the Files tab's folder; resolves to the path written. */
  onUploadFile?: (file: File) => Promise<string>;
  /** "Mention in chat" from the file browser. */
  mentionRequest?: MentionRequest | null;
}

/** True when a drag carries files from the desktop (not text or a link). */
function draggingFiles(e: React.DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes("Files");
}

/** Why a conversation is read-only, and what the reader can do about it. */
function viewingStatus(viewing: ViewedConversation): string {
  if (viewing.gone) return "This conversation was deleted.";
  if (viewing.running) return "A turn is running in this conversation. This copy refreshes as it goes.";
  if (viewing.connected)
    return "This conversation is open in another window. This copy refreshes as it changes; Continue here moves it to this window.";
  return "This conversation is free now.";
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
  viewing = null,
  onContinueViewed,
  onLeaveViewed,
  filesEnabled = false,
  onUploadFile,
  mentionRequest = null,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [continuing, setContinuing] = useState(false);
  const [continueProblem, setContinueProblem] = useState<string | null>(null);
  // A running turn can't be moved to another window whole. A window that merely has
  // the conversation open can be told to let go (gh #236).
  const viewedRunning = !!viewing && viewing.running;

  const handleContinue = async () => {
    if (!onContinueViewed) return;
    setContinuing(true);
    setContinueProblem(await onContinueViewed());
    setContinuing(false);
  };

  // A new read-only conversation starts with a clean slate.
  useEffect(() => {
    setContinueProblem(null);
  }, [viewing?.threadId]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isNearBottomRef = useRef(true);
  const slashCommands = useSlashCommands({ saveWorkflowPrompt, runWorkflowPrompt, createWorkflowPrompt });
  const canMention = filesEnabled && !viewing;
  const canDrop = canMention && !!onUploadFile;
  const mentions = useFileMentions(canMention);
  // The textarea's last selection, so a drop or "Mention in chat" inserts where the
  // caret was even after focus moved to the file browser.
  const selectionRef = useRef({ start: 0, end: 0 });
  const [dragOver, setDragOver] = useState(false);
  const dragDepth = useRef(0);
  const [uploadNote, setUploadNote] = useState<{ text: string; error: boolean } | null>(null);

  const resize = (el: HTMLTextAreaElement | null) => {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  /** Focus the textarea with the caret at `caret`, once React has rendered the text. */
  const focusAt = (caret: number) => {
    selectionRef.current = { start: caret, end: caret };
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(caret, caret);
      resize(el);
    });
  };

  /** Insert mentions of `paths` at the remembered selection. */
  const insertPaths = (paths: string[]) => {
    if (!paths.length) return;
    setInput((current) => {
      const start = Math.min(selectionRef.current.start, current.length);
      const end = Math.min(selectionRef.current.end, current.length);
      const edit = insertMentions(current, start, end, paths);
      focusAt(edit.caret);
      return edit.text;
    });
  };

  // "Mention in chat" from the file browser.
  useEffect(() => {
    if (mentionRequest && canMention) insertPaths(mentionRequest.paths);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mentionRequest?.seq]);

  const pickMention = (index: number) => {
    const hit = mentions.results[index];
    const m = mentions.mention;
    if (!hit || !m) return;
    const edit = applyMention(input, m, hit.path);
    mentions.close();
    setInput(edit.text);
    focusAt(edit.caret);
  };

  const trackSelection = (el: HTMLTextAreaElement) => {
    selectionRef.current = { start: el.selectionStart, end: el.selectionEnd };
    mentions.update(el.value, el.selectionStart);
  };

  const handleDragEnter = (e: React.DragEvent) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    dragDepth.current += 1;
    setDragOver(true);
  };
  const handleDragOver = (e: React.DragEvent) => {
    if (!draggingFiles(e)) return;
    // Always prevent the default, so a file dropped here never replaces the page.
    e.preventDefault();
    e.dataTransfer.dropEffect = canDrop ? "copy" : "none";
  };
  const handleDragLeave = (e: React.DragEvent) => {
    if (!draggingFiles(e)) return;
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragOver(false);
  };
  const handleDrop = async (e: React.DragEvent) => {
    if (!draggingFiles(e)) return;
    e.preventDefault();
    dragDepth.current = 0;
    setDragOver(false);
    if (!canDrop || !onUploadFile) {
      setUploadNote({
        text: viewing
          ? "This conversation is read-only here, so nothing was uploaded."
          : "Uploading isn't available: the Files tab is turned off.",
        error: true,
      });
      return;
    }
    const items = Array.from(e.dataTransfer.items ?? []);
    const dropped = Array.from(e.dataTransfer.files ?? []);
    const files = dropped.filter((_, i) => !items[i]?.webkitGetAsEntry?.()?.isDirectory);
    const skippedFolders = dropped.length - files.length;
    if (!files.length) {
      setUploadNote({ text: "Folders can't be dropped; drop the files inside them.", error: true });
      return;
    }
    setUploadNote({
      text: files.length === 1 ? `Uploading ${files[0].name}…` : `Uploading ${files.length} files…`,
      error: false,
    });
    const written: string[] = [];
    const failed: string[] = [];
    for (const file of files) {
      try {
        written.push(await onUploadFile(file));
      } catch (err) {
        failed.push(`${file.name} (${err instanceof Error ? err.message : String(err)})`);
      }
    }
    insertPaths(written);
    const problems: string[] = [];
    if (failed.length) problems.push(`Couldn't upload ${failed.join(", ")}.`);
    if (skippedFolders) problems.push("Folders were skipped.");
    setUploadNote(problems.length ? { text: problems.join(" "), error: true } : null);
  };

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
    setUploadNote(null);
    slashCommands.reset();
    mentions.close();
    if (inputRef.current) inputRef.current.style.height = "auto";
  };

  const handleSubmit = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming || viewing) return;
    const expanded = slashCommands.tryExecute(trimmed);
    sendAndReset(expanded ?? trimmed);
  };

  const handleStarter = (text: string) => {
    if (isStreaming) return;
    isNearBottomRef.current = true;
    onSend(text);
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
    // The @ file picker, when open, gets the navigation keys first.
    const mentionKey = mentions.handleKeyDown(e);
    if (mentionKey === "pick") {
      pickMention(mentions.selectedIndex);
      return;
    }
    if (mentionKey) return;
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
    trackSelection(e.target);
    resize(e.target);
  };

  return (
    <div
      className="flex flex-col h-full bg-[var(--color-surface)] relative"
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      data-testid="chat-panel"
    >
      {dragOver && (
        <div
          data-print-hide
          data-testid="drop-overlay"
          className="pointer-events-none absolute inset-2 z-20 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-[var(--color-primary)] bg-[var(--color-accent-soft)] text-sm text-[var(--color-text)]"
        >
          <Upload size={20} />
          {canDrop
            ? "Drop to upload to the workspace and mention it"
            : viewing
              ? "This conversation is read-only here"
              : "Uploading isn't available here"}
        </div>
      )}
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
                  <Markdown>{welcomeMessage}</Markdown>
                </div>
              ) : (
                <div className="text-center">
                  <p className="text-base font-semibold text-[var(--color-text)]">
                    What can I help you with?
                  </p>
                  <p className="text-sm text-[var(--color-text-muted)] mt-1">
                    Pick a starting point or ask anything below.
                  </p>
                </div>
              )}

              {/* Starter prompts — one-click ways in, to skip the blank canvas */}
              <div className="flex flex-wrap items-center justify-center gap-2 max-w-md">
                {STARTER_PROMPTS.map((p) => (
                  <button
                    key={p}
                    onClick={() => handleStarter(p)}
                    disabled={isStreaming}
                    className="px-3 py-1.5 text-xs text-[var(--color-text-secondary)] rounded-full border border-[var(--color-border)] bg-[var(--color-card)] hover:border-[var(--color-primary)] hover:text-[var(--color-text)] hover:bg-[var(--color-accent-soft)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              agentName={agentName}
              iconUrl={iconUrl}
              showLabel={i === 0 || messages[i - 1].role !== msg.role}
            />
          ))}

          {isStreaming && messages.length > 0 && (
            <div className="flex gap-3 text-xs text-[var(--color-text-muted)]">
              <div className="flex-shrink-0 w-7" />
              <span className="flex items-center gap-2">
                <span className="flex gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-primary)] animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-primary)] animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-primary)] animate-bounce" style={{ animationDelay: "300ms" }} />
                </span>
                {agentName} is working…
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Read-only notice: the conversation is busy in another window */}
      {viewing && (
        <div
          data-print-hide
          role="status"
          className="border-t border-[var(--color-border)] bg-[var(--color-accent-soft)]"
        >
          <div className="max-w-4xl mx-auto px-5 py-2 flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
            <Eye size={14} className="flex-shrink-0" />
            <span className="flex-1 min-w-0">
              <span className="font-medium text-[var(--color-text)]">Read-only.</span>{" "}
              {viewingStatus(viewing)}
              {continueProblem && (
                <span className="text-[var(--color-error)]"> Couldn't continue: {continueProblem}</span>
              )}
            </span>
            {!viewing.gone && (
              <button
                onClick={handleContinue}
                disabled={viewedRunning || continuing}
                title={
                  viewedRunning
                    ? "Available when the turn has finished"
                    : viewing.connected
                      ? "Continue this conversation in this window; the other window becomes read-only"
                      : "Continue this conversation in this window"
                }
                className="flex-shrink-0 px-2.5 py-1 rounded-md bg-[var(--color-text)] text-[var(--color-surface)] hover:opacity-80 transition-opacity disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
              >
                Continue here
              </button>
            )}
            <button
              onClick={onLeaveViewed}
              className="flex-shrink-0 px-2.5 py-1 rounded-md border border-[var(--color-border)] hover:bg-[var(--color-surface-3)] cursor-pointer"
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* Input area */}
      <div data-print-hide className="border-t border-[var(--color-border)]">
        <div className="max-w-4xl mx-auto px-5 py-3 relative">
          <MentionMenu
            open={mentions.open}
            query={mentions.mention?.query ?? ""}
            results={mentions.results}
            loading={mentions.loading}
            selectedIndex={mentions.selectedIndex}
            onPick={pickMention}
            onHover={mentions.setSelectedIndex}
          />
          {uploadNote && (
            <div
              role="status"
              data-testid="upload-note"
              className={`mb-1.5 text-xs ${uploadNote.error ? "text-[var(--color-error)]" : "text-[var(--color-text-muted)]"}`}
            >
              {uploadNote.text}
            </div>
          )}
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
          <div className="flex items-end gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] shadow-xs px-3 py-2 transition-colors focus-within:border-[var(--color-primary)] focus-within:ring-1 focus-within:ring-[var(--color-primary)]">
            <textarea
              ref={inputRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              onSelect={(e) => trackSelection(e.currentTarget)}
              onBlur={() => mentions.close()}
              placeholder={viewing ? "Read-only: continue the conversation here to reply" : "Send a message..."}
              disabled={!!viewing}
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
          <div className={`text-center mt-1.5 transition-opacity ${input ? "opacity-0" : "opacity-100"}`}>
            <span className="text-[10px] text-[var(--color-text-muted)]">
              <kbd className="px-1 py-0.5 rounded bg-[var(--color-surface-3)] text-[9px] font-mono">Enter</kbd> to send, <kbd className="px-1 py-0.5 rounded bg-[var(--color-surface-3)] text-[9px] font-mono">Shift+Enter</kbd> for new line, <kbd className="px-1 py-0.5 rounded bg-[var(--color-surface-3)] text-[9px] font-mono">/</kbd> for commands
              {canMention && (
                <>
                  , <kbd className="px-1 py-0.5 rounded bg-[var(--color-surface-3)] text-[9px] font-mono">@</kbd> to mention a file
                </>
              )}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
