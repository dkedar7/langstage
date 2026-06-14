import { useState } from "react";
import {
  Clock,
  Loader2,
  Eye,
  CheckCircle2,
  XCircle,
  Ban,
  RotateCcw,
  X,
  KanbanSquare,
} from "lucide-react";
import type { Task, TaskState } from "../types";

interface TaskBoardProps {
  tasks: Task[];
  onCreate: (prompt: string, title?: string) => Promise<void>;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
}

const COLUMNS: { key: string; label: string; states: TaskState[] }[] = [
  { key: "queued", label: "Queued", states: ["queued"] },
  { key: "ongoing", label: "Ongoing", states: ["ongoing"] },
  { key: "review", label: "Review", states: ["review_needed"] },
  { key: "done", label: "Done", states: ["done", "failed", "cancelled"] },
];

const STATE_META: Record<TaskState, { label: string; cls: string; Icon: typeof Clock }> = {
  queued: { label: "queued", cls: "text-[var(--color-text-muted)]", Icon: Clock },
  ongoing: { label: "running", cls: "text-amber-500", Icon: Loader2 },
  review_needed: { label: "review", cls: "text-violet-500", Icon: Eye },
  done: { label: "done", cls: "text-emerald-500", Icon: CheckCircle2 },
  failed: { label: "failed", cls: "text-red-500", Icon: XCircle },
  cancelled: { label: "cancelled", cls: "text-[var(--color-text-muted)]", Icon: Ban },
};

const CANCELLABLE: TaskState[] = ["queued", "ongoing", "review_needed"];
const RETRYABLE: TaskState[] = ["failed", "cancelled"];

function StateBadge({ state }: { state: TaskState }) {
  const m = STATE_META[state];
  const Icon = m.Icon;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] ${m.cls}`}>
      <Icon size={11} className={state === "ongoing" ? "animate-spin" : ""} />
      {m.label}
    </span>
  );
}

function TaskCard({
  task,
  onCancel,
  onRetry,
}: {
  task: Task;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
}) {
  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface-2)] p-2.5">
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-[var(--color-text)] truncate min-w-0">
          {task.title}
        </span>
        <div className="flex items-center gap-1 shrink-0">
          {CANCELLABLE.includes(task.state) && (
            <button
              onClick={() => onCancel(task.task_id)}
              title="Cancel"
              className="p-0.5 rounded hover:bg-[var(--color-surface-3)] text-[var(--color-text-secondary)] hover:text-red-500"
            >
              <X size={12} />
            </button>
          )}
          {RETRYABLE.includes(task.state) && (
            <button
              onClick={() => onRetry(task.task_id)}
              title="Retry"
              className="p-0.5 rounded hover:bg-[var(--color-surface-3)] text-[var(--color-text-secondary)]"
            >
              <RotateCcw size={12} />
            </button>
          )}
        </div>
      </div>
      <p className="mt-1 text-[11px] text-[var(--color-text-muted)] line-clamp-2">{task.prompt}</p>
      {task.result && (
        <p className="mt-1 text-[10px] text-[var(--color-text-secondary)] line-clamp-3 border-l-2 border-[var(--color-border)] pl-1.5">
          {task.result}
        </p>
      )}
      {task.error && (
        <p className="mt-1 text-[10px] text-red-500 line-clamp-2">{task.error}</p>
      )}
      <div className="mt-1.5">
        <StateBadge state={task.state} />
      </div>
    </div>
  );
}

export function TaskBoard({ tasks, onCreate, onCancel, onRetry }: TaskBoardProps) {
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = prompt.trim() && !submitting;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await onCreate(prompt.trim());
      setPrompt("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const inCol = (states: TaskState[]) => tasks.filter((t) => states.includes(t.state));

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Delegate form */}
      <form onSubmit={submit} className="p-3 border-b border-[var(--color-border)] space-y-2">
        <div className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-muted)]">
          Delegate a task
        </div>
        <div className="flex gap-2">
          <input
            className="flex-1 px-2.5 py-1.5 text-xs rounded-md bg-[var(--color-surface-2)] border border-[var(--color-border)] text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-primary)]"
            placeholder="Describe a task to run in the background…"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <button
            type="submit"
            disabled={!canSubmit}
            className="px-3 py-1 text-xs font-medium rounded-md bg-[var(--color-primary)] text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {submitting ? "…" : "Run"}
          </button>
        </div>
        {error && <div className="text-[11px] text-red-500">{error}</div>}
      </form>

      {/* Board columns */}
      {tasks.length === 0 ? (
        <div className="flex flex-col items-center justify-center flex-1 text-[var(--color-text-muted)] text-xs gap-2">
          <KanbanSquare size={20} />
          No tasks yet — delegate one above.
        </div>
      ) : (
        <div className="flex-1 flex gap-2 p-2 overflow-x-auto">
          {COLUMNS.map((col) => {
            const items = inCol(col.states);
            return (
              <div key={col.key} className="flex flex-col w-44 shrink-0">
                <div className="flex items-center justify-between px-1 pb-1.5 text-[10px] font-medium uppercase tracking-wide text-[var(--color-text-muted)]">
                  <span>{col.label}</span>
                  <span className="tabular-nums">{items.length}</span>
                </div>
                <div className="space-y-2 overflow-y-auto">
                  {items.map((t) => (
                    <TaskCard key={t.task_id} task={t} onCancel={onCancel} onRetry={onRetry} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
