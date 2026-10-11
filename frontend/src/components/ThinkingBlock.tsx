import { useState } from "react";
import { Brain, ChevronRight, Loader2 } from "lucide-react";

interface ThinkingBlockProps {
  /** The turn's accumulated `reasoning` deltas. */
  reasoning: string;
  /** True while the model is still reasoning (no answer or tool call yet). */
  active?: boolean;
}

/**
 * A reasoning model's chain-of-thought, collapsed by default above the answer it
 * led to, styled like a tool call card (gh #196).
 */
export function ThinkingBlock({ reasoning, active = false }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded border border-[var(--color-border)] bg-[var(--color-surface-2)] overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="flex items-center gap-2 w-full px-3 py-1.5 text-left text-xs hover:bg-[var(--color-surface-3)] transition-colors"
      >
        <ChevronRight
          size={12}
          className={`text-[var(--color-text-muted)] transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
        <Brain size={12} className="text-[var(--color-text-muted)]" />
        <span className="font-medium text-[var(--color-text-secondary)]">Thinking</span>
        <span className="flex-1" />
        {active && (
          <Loader2 size={12} className="animate-spin text-[var(--color-text-muted)]" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-[var(--color-border)] px-3 py-2 max-h-[400px] overflow-y-auto">
          <p className="text-xs italic text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap">
            {reasoning}
          </p>
        </div>
      )}
    </div>
  );
}
