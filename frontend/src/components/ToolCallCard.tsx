import { useState, useRef, useEffect } from "react";
import {
  ChevronRight,
  CheckCircle2,
  XCircle,
  Loader2,
  Wrench,
  Terminal,
  FileText,
  Search,
  ListTodo,
  Brain,
  GitBranch,
  Circle,
  Image,
  AlertTriangle,
} from "lucide-react";
import type { ToolCall, TodoItem } from "../types";

interface ToolCallCardProps {
  toolCall: ToolCall;
}

const TOOL_ICONS: Record<string, typeof Wrench> = {
  execute: Terminal,
  execute_cell: Terminal,
  execute_all_cells: Terminal,
  bash: Terminal,
  write_file: FileText,
  edit_file: FileText,
  read_file: FileText,
  create_cell: FileText,
  modify_cell: FileText,
  ls: Search,
  glob: Search,
  grep: Search,
  write_todos: ListTodo,
  think_tool: Brain,
  task: GitBranch,
  display_inline: Image,
};

function normalizeTodos(data: unknown): TodoItem[] {
  const rawList: unknown[] = Array.isArray(data) ? data : [];
  return rawList.map((item) => {
    if (item && typeof item === "object") {
      const obj = item as Record<string, unknown>;
      return {
        content: (obj.content as string) ?? (obj.task as string) ?? "",
        status:
          (obj.status as TodoItem["status"]) ??
          (obj.done === true ? "completed" : "pending"),
      };
    }
    return { content: String(item), status: "pending" as const };
  });
}

function firstArgPreview(args: Record<string, unknown>): string | null {
  const keys = Object.keys(args);
  if (keys.length === 0) return null;
  const val = args[keys[0]];
  if (val == null) return null;
  const str = typeof val === "string" ? val : JSON.stringify(val);
  return str.length > 100 ? str.slice(0, 100) + "…" : str;
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);
  const Icon = TOOL_ICONS[toolCall.name] || Wrench;
  const extraction = toolCall.extraction;

  const statusIndicator =
    toolCall.status === "running" ? (
      <Loader2 size={12} className="animate-spin text-[var(--color-text-muted)]" />
    ) : toolCall.status === "success" ? (
      <CheckCircle2 size={12} className="text-[var(--color-success)]" />
    ) : (
      <XCircle size={12} className="text-[var(--color-error)]" />
    );

  const durationLabel =
    toolCall.durationMs != null
      ? toolCall.durationMs < 1000
        ? `${Math.round(toolCall.durationMs)}ms`
        : `${(toolCall.durationMs / 1000).toFixed(1)}s`
      : null;

  return (
    <div className="rounded border border-[var(--color-border)] bg-[var(--color-surface-2)] overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full px-3 py-1.5 text-left text-xs hover:bg-[var(--color-surface-3)] transition-colors"
      >
        <ChevronRight
          size={12}
          className={`text-[var(--color-text-muted)] transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
        <Icon size={12} className="text-[var(--color-text-muted)]" />
        <span className="font-medium text-[var(--color-text-secondary)]">
          {toolCall.name}
        </span>
        {firstArgPreview(toolCall.args) && (
          <code className="text-[11px] text-[var(--color-text-muted)] truncate max-w-[300px]">
            ({firstArgPreview(toolCall.args)})
          </code>
        )}
        <span className="flex-1" />
        {durationLabel && (
          <span className="text-[11px] tabular-nums text-[var(--color-text-muted)]">
            {durationLabel}
          </span>
        )}
        {statusIndicator}
      </button>

      {/* Inline extraction -- always visible */}
      {extraction?.extracted_type === "reflection" && (
        <div className="border-t border-[var(--color-border)] px-3 py-2">
          <p className="text-xs italic text-[var(--color-text-secondary)] leading-relaxed">
            {String(extraction.data)}
          </p>
        </div>
      )}

      {extraction?.extracted_type === "todos" && (
        <div className="border-t border-[var(--color-border)] px-3 py-2">
          <InlineTodoList todos={normalizeTodos(extraction.data)} />
        </div>
      )}

      {extraction?.extracted_type === "display_inline" && (
        <div className="border-t border-[var(--color-border)]">
          <InlineDisplay data={extraction.data as Record<string, unknown>} />
        </div>
      )}

      {expanded && (
        <div className="border-t border-[var(--color-border)] px-3 py-2 space-y-2">
          {Object.keys(toolCall.args).length > 0 && (
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-muted)] mb-1">
                Arguments
              </div>
              <pre className="bg-[var(--color-surface-3)] rounded p-2 text-xs overflow-x-auto whitespace-pre-wrap break-all text-[var(--color-text)]">
                {JSON.stringify(toolCall.args, null, 2)}
              </pre>
            </div>
          )}

          {toolCall.result != null && (
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-text-muted)] mb-1">
                Result
              </div>
              <pre
                className={`rounded p-2 text-xs overflow-auto max-h-[400px] whitespace-pre-wrap break-all ${
                  toolCall.name === "execute" || toolCall.name === "bash" || toolCall.name === "execute_cell"
                    ? "bg-[#111827] text-emerald-400"
                    : "bg-[var(--color-surface-3)] text-[var(--color-text)]"
                }`}
              >
                {typeof toolCall.result === "string"
                  ? toolCall.result
                  : JSON.stringify(toolCall.result, null, 2)}
              </pre>
            </div>
          )}

          {toolCall.errorMessage && (
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-error)] mb-1">
                Error
              </div>
              <pre className="bg-red-50 dark:bg-red-950/30 text-[var(--color-error)] rounded p-2 text-xs overflow-x-auto whitespace-pre-wrap">
                {toolCall.errorMessage}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function InlineDisplay({ data }: { data: Record<string, unknown> }) {
  const displayType = data.display_type as string;
  const title = data.title as string | null;
  const content = data.data;
  const status = data.status as string;
  const error = data.error as string | null;

  if (status === "error") {
    return (
      <div className="px-3 py-2 space-y-1">
        {title && (
          <div className="text-[11px] font-medium text-[var(--color-text-muted)]">
            {title}
          </div>
        )}
        <div className="flex items-start gap-2 text-xs text-[var(--color-error)]">
          <AlertTriangle size={12} className="flex-shrink-0 mt-0.5" />
          <span>{error || String(content)}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="px-3 py-2 space-y-1.5">
      {title && (
        <div className="text-[11px] font-medium text-[var(--color-text-muted)]">
          {title}
        </div>
      )}

      {displayType === "image" && (
        <img
          src={
            typeof content === "string" && content.startsWith("data:")
              ? content
              : `data:image/png;base64,${content}`
          }
          alt={title || "Inline display"}
          className="max-w-full rounded"
        />
      )}

      {displayType === "html" && (
        <HtmlIframe html={String(content)} title={title} />
      )}

      {displayType === "plotly" && (
        <pre className="bg-[var(--color-surface-3)] rounded p-2 text-xs overflow-x-auto whitespace-pre-wrap text-[var(--color-text)]">
          {JSON.stringify(content, null, 2)}
        </pre>
      )}

      {(displayType === "dataframe" || displayType === "csv") &&
        !!content &&
        typeof content === "object" &&
        "columns" in (content as Record<string, unknown>) && (
          <div className="overflow-x-auto max-h-[300px] overflow-y-auto">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr>
                  {(
                    (content as Record<string, unknown>).columns as string[]
                  ).map((col) => (
                    <th
                      key={col}
                      className="border border-[var(--color-border)] bg-[var(--color-surface-3)] px-2 py-1 text-left font-medium text-[var(--color-text-secondary)]"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(
                  (content as Record<string, unknown>).data as unknown[][]
                ).map((row, i) => (
                  <tr key={i}>
                    {(row as unknown[]).map((cell, j) => (
                      <td
                        key={j}
                        className="border border-[var(--color-border)] px-2 py-1 text-[var(--color-text)]"
                      >
                        {String(cell ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

      {displayType === "pdf" && typeof content === "string" && (
        <iframe
          src={`data:application/pdf;base64,${content}`}
          title={title || "PDF preview"}
          className="w-full h-[500px] rounded border border-[var(--color-border)]"
        />
      )}

      {displayType === "json" && (
        <pre className="bg-[var(--color-surface-3)] rounded p-2 text-xs overflow-x-auto whitespace-pre-wrap break-all text-[var(--color-text)]">
          {typeof content === "string"
            ? content
            : JSON.stringify(content, null, 2)}
        </pre>
      )}

      {displayType === "text" && (
        <pre className="text-xs whitespace-pre-wrap text-[var(--color-text)] leading-relaxed">
          {String(content)}
        </pre>
      )}
    </div>
  );
}

const IFRAME_RESIZE_SCRIPT = `<script>
function _sendHeight(){
  var h=document.documentElement.scrollHeight;
  window.parent.postMessage({type:'iframe-resize',height:h},'*');
}
window.addEventListener('load',function(){_sendHeight();setTimeout(_sendHeight,200);setTimeout(_sendHeight,1000);});
new MutationObserver(_sendHeight).observe(document.body,{childList:true,subtree:true});
</script>`;

function HtmlIframe({ html, title }: { html: string; title: string | null }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(200);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const handleMessage = (e: MessageEvent) => {
      if (e.source === iframe.contentWindow && e.data?.type === "iframe-resize") {
        const h = Math.max(60, Math.min(e.data.height, 600));
        setHeight(h);
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [html]);

  const srcdoc = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  body { margin: 0; padding: 8px; font-family: system-ui, sans-serif; font-size: 13px; }
  img, table, svg { max-width: 100%; }
</style></head><body>${html}${IFRAME_RESIZE_SCRIPT}</body></html>`;

  return (
    <iframe
      ref={iframeRef}
      srcDoc={srcdoc}
      title={title || "HTML preview"}
      sandbox="allow-scripts allow-same-origin"
      className="w-full rounded border-0"
      style={{ height: `${height}px` }}
    />
  );
}

function InlineTodoList({ todos }: { todos: TodoItem[] }) {
  const completed = todos.filter((t) => t.status === "completed").length;
  const total = todos.length;

  return (
    <div className="space-y-1">
      <div className="text-[11px] text-[var(--color-text-muted)]">
        {completed}/{total} completed
      </div>
      {todos.map((todo, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          {todo.status === "completed" ? (
            <CheckCircle2 size={11} className="text-[var(--color-success)] flex-shrink-0" />
          ) : todo.status === "in_progress" ? (
            <Circle size={11} className="text-[var(--color-primary)] fill-[var(--color-primary)] flex-shrink-0" />
          ) : (
            <Circle size={11} className="text-[var(--color-text-muted)] flex-shrink-0" />
          )}
          <span
            className={
              todo.status === "completed"
                ? "text-[var(--color-text-muted)] line-through"
                : "text-[var(--color-text-secondary)]"
            }
          >
            {todo.content}
          </span>
        </div>
      ))}
    </div>
  );
}
