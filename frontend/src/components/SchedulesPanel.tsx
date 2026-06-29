import { useState } from "react";
import { Play, Trash2, Bot, User, AlarmClock } from "lucide-react";
import type { CronJob } from "../types";

interface SchedulesPanelProps {
  jobs: CronJob[];
  onCreate: (name: string, cron: string, prompt: string) => Promise<void>;
  onDelete: (id: string) => void;
  onRun: (id: string) => void;
}

// Natural-language presets so the common cases don't require writing raw cron.
const CRON_PRESETS: { label: string; cron: string }[] = [
  { label: "Every 15 min", cron: "*/15 * * * *" },
  { label: "Hourly", cron: "0 * * * *" },
  { label: "Daily 9am", cron: "0 9 * * *" },
  { label: "Weekdays 9am", cron: "0 9 * * 1-5" },
  { label: "Weekly Mon", cron: "0 9 * * 1" },
];

function fmt(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function statusColor(status: string | null): string {
  if (!status) return "text-[var(--color-text-muted)]";
  if (status === "ok") return "text-emerald-500";
  if (status === "running") return "text-amber-500";
  if (status.startsWith("error")) return "text-red-500";
  return "text-[var(--color-text-muted)]";
}

export function SchedulesPanel({ jobs, onCreate, onDelete, onRun }: SchedulesPanelProps) {
  const [name, setName] = useState("");
  const [cron, setCron] = useState("");
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = name.trim() && cron.trim() && prompt.trim() && !submitting;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await onCreate(name.trim(), cron.trim(), prompt.trim());
      setName("");
      setCron("");
      setPrompt("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const inputCls =
    "w-full px-2.5 py-1.5 text-xs rounded-md bg-[var(--color-card)] border border-[var(--color-border)] text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-primary)] focus:ring-1 focus:ring-[var(--color-primary)]";

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Create form */}
      <form onSubmit={submit} className="p-3 border-b border-[var(--color-border)] space-y-2">
        <div className="text-xs font-semibold text-[var(--color-text-secondary)]">
          New schedule
        </div>
        <input
          className={inputCls}
          placeholder="Name (e.g. Daily standup summary)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className={`${inputCls} font-mono`}
          placeholder="Cron — min hour day month weekday (e.g. 0 9 * * 1-5)"
          value={cron}
          onChange={(e) => setCron(e.target.value)}
        />
        {/* Quick presets — set the cron field without writing raw cron */}
        <div className="flex flex-wrap gap-1">
          {CRON_PRESETS.map((p) => (
            <button
              key={p.cron}
              type="button"
              onClick={() => setCron(p.cron)}
              title={p.cron}
              className={`px-2 py-0.5 text-[11px] rounded-full border transition-colors ${
                cron === p.cron
                  ? "border-[var(--color-primary)] bg-[var(--color-accent-soft)] text-[var(--color-text)]"
                  : "border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-primary)] hover:text-[var(--color-text)]"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <textarea
          className={`${inputCls} resize-none`}
          rows={2}
          placeholder="Prompt to run on schedule"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-[var(--color-text-muted)]">
            e.g. <code>*/15 * * * *</code> · <code>0 9 * * 1-5</code> · in-memory while the app runs
          </span>
          <button
            type="submit"
            disabled={!canSubmit}
            className="px-3 py-1 text-xs font-medium rounded-md bg-[var(--color-primary)] text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {submitting ? "Adding…" : "Add"}
          </button>
        </div>
        {error && <div className="text-[11px] text-red-500">{error}</div>}
      </form>

      {/* Job list */}
      <div className="flex-1 p-2 space-y-2">
        {jobs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-[var(--color-text-muted)] text-xs gap-2">
            <AlarmClock size={20} />
            No scheduled runs yet.
          </div>
        ) : (
          jobs.map((job) => (
            <div
              key={job.id}
              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] shadow-xs p-2.5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium text-[var(--color-text)] truncate">
                      {job.name}
                    </span>
                    <span
                      className="inline-flex items-center gap-0.5 text-[9px] px-1 py-px rounded bg-[var(--color-surface-3)] text-[var(--color-text-muted)]"
                      title={`created by ${job.created_by}`}
                    >
                      {job.created_by === "agent" ? <Bot size={9} /> : <User size={9} />}
                      {job.created_by}
                    </span>
                  </div>
                  <code className="text-[11px] text-[var(--color-text-secondary)]">{job.cron}</code>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => onRun(job.id)}
                    title="Run now"
                    className="p-1 rounded hover:bg-[var(--color-surface-3)] text-[var(--color-text-secondary)]"
                  >
                    <Play size={13} />
                  </button>
                  <button
                    onClick={() => onDelete(job.id)}
                    title="Delete schedule"
                    className="p-1 rounded hover:bg-[var(--color-surface-3)] text-[var(--color-text-secondary)] hover:text-red-500"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
              <p className="mt-1 text-[11px] text-[var(--color-text-muted)] line-clamp-2">{job.prompt}</p>
              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-[var(--color-text-muted)]">
                <span>next: {fmt(job.next_run)}</span>
                <span>last: {fmt(job.last_run)}</span>
                <span>runs: {job.run_count}</span>
                {job.last_status && (
                  <span className={statusColor(job.last_status)}>{job.last_status}</span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
