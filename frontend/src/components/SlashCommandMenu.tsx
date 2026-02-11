import { useRef, useEffect } from "react";
import { FileText, Terminal, Loader2 } from "lucide-react";
import type { SlashCommandDefinition } from "../hooks/useSlashCommands";

interface SlashCommandMenuProps {
  showCommandMenu: boolean;
  filteredCommands: SlashCommandDefinition[];
  showWorkflowPicker: boolean;
  filteredWorkflowFiles: string[];
  isLoadingWorkflows: boolean;
  selectedIndex: number;
  onSelect: (index: number) => void;
  onHover: (index: number) => void;
}

export function SlashCommandMenu({
  showCommandMenu,
  filteredCommands,
  showWorkflowPicker,
  filteredWorkflowFiles,
  isLoadingWorkflows,
  selectedIndex,
  onSelect,
  onHover,
}: SlashCommandMenuProps) {
  const selectedRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  if (!showCommandMenu && !showWorkflowPicker) return null;

  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 z-10">
      <div className="bg-[var(--color-surface-2)] border border-[var(--color-border)] rounded-lg shadow-lg overflow-hidden max-h-[200px] overflow-y-auto">
        {showCommandMenu && (
          <div className="py-1">
            {filteredCommands.map((cmd, i) => (
              <button
                key={cmd.name}
                ref={i === selectedIndex ? selectedRef : undefined}
                onClick={() => onSelect(i)}
                onMouseEnter={() => onHover(i)}
                className={`w-full text-left px-3 py-2 flex items-start gap-2.5 transition-colors ${
                  i === selectedIndex
                    ? "bg-[var(--color-surface-3)]"
                    : "hover:bg-[var(--color-surface-3)]"
                }`}
              >
                <Terminal
                  size={14}
                  className="text-[var(--color-text-muted)] mt-0.5 flex-shrink-0"
                />
                <div>
                  <div className="text-sm font-medium text-[var(--color-text)]">
                    {cmd.label}
                  </div>
                  <div className="text-xs text-[var(--color-text-muted)]">
                    {cmd.description}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {showWorkflowPicker && (
          <div className="py-1">
            <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              Workflows
            </div>
            {isLoadingWorkflows ? (
              <div className="flex items-center gap-2 px-3 py-2 text-xs text-[var(--color-text-muted)]">
                <Loader2 size={12} className="animate-spin" />
                Loading workflows...
              </div>
            ) : filteredWorkflowFiles.length === 0 ? (
              <div className="px-3 py-2 text-xs text-[var(--color-text-muted)] italic">
                No workflows found. Use /save-workflow to create one.
              </div>
            ) : (
              filteredWorkflowFiles.map((file, i) => (
                <button
                  key={file}
                  ref={i === selectedIndex ? selectedRef : undefined}
                  onClick={() => onSelect(i)}
                  onMouseEnter={() => onHover(i)}
                  className={`w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors ${
                    i === selectedIndex
                      ? "bg-[var(--color-surface-3)]"
                      : "hover:bg-[var(--color-surface-3)]"
                  }`}
                >
                  <FileText
                    size={14}
                    className="text-[var(--color-text-secondary)] flex-shrink-0"
                  />
                  <span className="text-sm text-[var(--color-text)] truncate">
                    {file}
                  </span>
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
