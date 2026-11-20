import { useEffect, useRef } from "react";
import { FileText, Folder, Loader2 } from "lucide-react";
import type { FileSearchHit } from "../types";

interface MentionMenuProps {
  open: boolean;
  query: string;
  results: FileSearchHit[];
  loading: boolean;
  selectedIndex: number;
  onPick: (index: number) => void;
  onHover: (index: number) => void;
}

/** The `@` file picker above the chat input (gh #238). */
export function MentionMenu({ open, query, results, loading, selectedIndex, onPick, onHover }: MentionMenuProps) {
  const selectedRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  if (!open) return null;

  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 z-10" data-testid="mention-menu">
      <div className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-lg shadow-md overflow-hidden max-h-[240px] overflow-y-auto py-1">
        <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Workspace files
        </div>
        {results.length === 0 ? (
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-[var(--color-text-muted)]">
            {loading ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                Searching…
              </>
            ) : (
              <span className="italic">{query ? `No file matches "${query}"` : "The workspace is empty"}</span>
            )}
          </div>
        ) : (
          <div role="listbox" aria-label="Workspace files">
            {results.map((hit, i) => {
              const slash = hit.path.lastIndexOf("/");
              const dir = slash >= 0 ? hit.path.slice(0, slash + 1) : "";
              const Icon = hit.is_dir ? Folder : FileText;
              return (
                <button
                  key={hit.path}
                  role="option"
                  aria-selected={i === selectedIndex}
                  ref={i === selectedIndex ? selectedRef : undefined}
                  // Keep focus (and the caret) in the textarea.
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => onPick(i)}
                  onMouseEnter={() => onHover(i)}
                  title={hit.path}
                  className={`w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors ${
                    i === selectedIndex ? "bg-[var(--color-surface-3)]" : "hover:bg-[var(--color-surface-3)]"
                  }`}
                >
                  <Icon size={14} className="text-[var(--color-text-secondary)] flex-shrink-0" />
                  <span className="text-sm text-[var(--color-text)] truncate">
                    {dir && <span className="text-[var(--color-text-muted)]">{dir}</span>}
                    {hit.name}
                    {hit.is_dir ? "/" : ""}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
