import { useState } from "react";
import {
  Check,
  X,
  Pencil,
} from "lucide-react";
import type { InterruptEventMsg, Decision } from "../types";

interface InterruptDialogProps {
  interrupt: InterruptEventMsg;
  onRespond: (decisions: Decision[]) => void;
}

export function InterruptDialog({ interrupt, onRespond }: InterruptDialogProps) {
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editedArgs, setEditedArgs] = useState("");
  const allowed = new Set(interrupt.allowed_decisions);
  const hasActions = interrupt.action_requests.length > 0;

  const handleApproveAll = () => {
    if (hasActions) {
      onRespond(interrupt.action_requests.map(() => ({ type: "approve" })));
    } else {
      // Fallback: send a single approve decision
      onRespond([{ type: "approve" }]);
    }
  };

  const handleRejectAll = () => {
    if (hasActions) {
      onRespond(interrupt.action_requests.map(() => ({ type: "reject" })));
    } else {
      onRespond([{ type: "reject" }]);
    }
  };

  const handleEditSubmit = (idx: number) => {
    try {
      const parsed = JSON.parse(editedArgs);
      const action = interrupt.action_requests[idx];
      const decisions: Decision[] = interrupt.action_requests.map((_, i) =>
        i === idx
          ? { type: "edit" as const, edited_action: { name: action.tool, args: parsed } }
          : { type: "approve" as const }
      );
      onRespond(decisions);
    } catch {
      // Invalid JSON -- keep dialog open
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4 backdrop-blur-sm">
      <div className="bg-[var(--color-surface)] rounded-lg shadow-xl border border-[var(--color-border)] max-w-lg w-full max-h-[80vh] overflow-y-auto">
        {/* Header */}
        <div className="px-5 py-4 border-b border-[var(--color-border)]">
          <h3 className="text-sm font-semibold text-[var(--color-text)]">
            Action Requires Approval
          </h3>
          <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
            {hasActions
              ? `The agent wants to perform the following action${interrupt.action_requests.length > 1 ? "s" : ""}`
              : "The agent needs your approval to continue"}
          </p>
        </div>

        {/* Actions */}
        <div className="px-5 py-4 space-y-3">
          {hasActions ? (
            interrupt.action_requests.map((action, idx) => (
              <div
                key={idx}
                className="border border-[var(--color-border)] rounded p-3"
              >
                <div className="mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-secondary)]">
                    {action.tool}
                  </span>
                </div>
                {action.description && (
                  <p className="text-xs text-[var(--color-text-secondary)] mb-2 leading-relaxed whitespace-pre-wrap">
                    {action.description}
                  </p>
                )}
                <pre className="bg-[var(--color-surface-3)] rounded p-2 text-xs overflow-x-auto whitespace-pre-wrap break-all text-[var(--color-text)]">
                  {JSON.stringify(action.args, null, 2)}
                </pre>

                {editingIdx === idx && (
                  <div className="mt-2">
                    <textarea
                      value={editedArgs}
                      onChange={(e) => setEditedArgs(e.target.value)}
                      className="w-full h-24 p-2 text-xs font-mono bg-[var(--color-surface-3)] border border-[var(--color-border)] rounded resize-none focus:outline-none focus:border-[var(--color-text-muted)] text-[var(--color-text)]"
                      placeholder="Edit args JSON..."
                    />
                    <div className="flex gap-2 mt-1">
                      <button
                        onClick={() => handleEditSubmit(idx)}
                        className="px-3 py-1 text-xs font-medium bg-[var(--color-text)] text-[var(--color-surface)] rounded hover:opacity-80 transition-opacity"
                      >
                        Submit
                      </button>
                      <button
                        onClick={() => setEditingIdx(null)}
                        className="px-3 py-1 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-[var(--color-text-muted)] italic">
                The agent needs your approval to continue.
              </p>
              <pre className="bg-[var(--color-surface-3)] rounded p-2 text-xs overflow-x-auto whitespace-pre-wrap break-all text-[var(--color-text-muted)]">
                {JSON.stringify(interrupt, null, 2)}
              </pre>
            </div>
          )}
        </div>

        {/* Buttons */}
        <div className="px-5 py-3 border-t border-[var(--color-border)] flex justify-end gap-2">
          {allowed.has("edit") && hasActions && (
            <button
              onClick={() => {
                setEditingIdx(0);
                setEditedArgs(
                  JSON.stringify(interrupt.action_requests[0]?.args ?? {}, null, 2)
                );
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[var(--color-text-secondary)] hover:text-[var(--color-text)] border border-[var(--color-border)] rounded hover:bg-[var(--color-surface-3)] transition-colors"
            >
              <Pencil size={12} />
              Edit
            </button>
          )}
          {allowed.has("reject") && (
            <button
              onClick={handleRejectAll}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[var(--color-error)] border border-[var(--color-error)]/30 rounded hover:bg-[var(--color-error)] hover:text-white transition-colors"
            >
              <X size={12} />
              Reject
            </button>
          )}
          {allowed.has("approve") && (
            <button
              onClick={handleApproveAll}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-[var(--color-text)] text-[var(--color-surface)] rounded hover:opacity-80 transition-opacity"
            >
              <Check size={12} />
              Approve
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
