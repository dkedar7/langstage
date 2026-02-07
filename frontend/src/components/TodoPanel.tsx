import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import type { TodoItem } from "../types";

interface TodoPanelProps {
  todos: TodoItem[];
}

export function TodoPanel({ todos }: TodoPanelProps) {
  if (todos.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-[var(--color-text-muted)]">
        No tasks yet
      </div>
    );
  }

  const completed = todos.filter((t) => t.status === "completed").length;
  const total = todos.length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="flex flex-col h-full">
      {/* Progress header */}
      <div className="px-4 py-2.5 border-b border-[var(--color-border)]">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-muted)]">
            Progress
          </span>
          <span className="text-[11px] tabular-nums text-[var(--color-text-muted)]">
            {completed}/{total} ({pct}%)
          </span>
        </div>
        <div className="h-1 rounded-full bg-[var(--color-surface-3)]">
          <div
            className="h-full rounded-full bg-[var(--color-primary)] transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-1">
        {todos.map((todo, i) => (
          <div key={i} className="flex items-start gap-2.5 py-1">
            {todo.status === "completed" ? (
              <CheckCircle2
                size={14}
                className="text-[var(--color-success)] flex-shrink-0 mt-0.5"
              />
            ) : todo.status === "in_progress" ? (
              <Loader2
                size={14}
                className="text-[var(--color-primary)] animate-spin flex-shrink-0 mt-0.5"
              />
            ) : (
              <Circle
                size={14}
                className="text-[var(--color-text-muted)] flex-shrink-0 mt-0.5"
              />
            )}
            <span
              className={`text-sm leading-snug ${
                todo.status === "completed"
                  ? "text-[var(--color-text-muted)] line-through"
                  : todo.status === "in_progress"
                    ? "text-[var(--color-text)]"
                    : "text-[var(--color-text-secondary)]"
              }`}
            >
              {todo.content}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
