import { useState, useEffect, useRef } from "react";
import { X, ChevronDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { CanvasItem as CanvasItemType } from "../types";

interface CanvasItemProps {
  item: CanvasItemType;
  onDelete: (id: string) => void;
}

export function CanvasItemCard({ item, onDelete }: CanvasItemProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="border border-[var(--color-border)] rounded-lg overflow-hidden bg-[var(--color-surface)]">
      {/* Header — click to toggle */}
      <div
        className="flex items-center justify-between px-3 py-2 bg-[var(--color-surface-2)] border-b border-[var(--color-border)] cursor-pointer select-none"
        onClick={() => setCollapsed((c) => !c)}
      >
        <div className="flex items-center gap-2">
          <ChevronDown
            size={14}
            className={`text-[var(--color-text-muted)] transition-transform duration-150 ${
              collapsed ? "-rotate-90" : ""
            }`}
          />
          <span className="text-xs font-medium uppercase text-[var(--color-text-muted)]">
            {item.type}
          </span>
          <span className="text-sm font-medium text-[var(--color-text)]">
            {item.title}
          </span>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete(item.id);
          }}
          className="p-1 rounded hover:bg-[var(--color-surface-3)] transition-colors"
        >
          <X size={14} className="text-[var(--color-text-secondary)]" />
        </button>
      </div>

      {/* Content — collapsible */}
      {!collapsed && (
        <div className="p-3">
          <CanvasContent item={item} />
        </div>
      )}
    </div>
  );
}

function CanvasContent({ item }: { item: CanvasItemType }) {
  switch (item.type) {
    case "markdown":
      return (
        <div className="markdown-content text-sm">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {typeof item.data === "string" ? item.data : JSON.stringify(item.data)}
          </ReactMarkdown>
        </div>
      );

    case "dataframe":
      return <DataFrameTable data={item.data} />;

    case "mermaid":
      return <MermaidDiagram code={String(item.data)} />;

    case "image":
    case "matplotlib":
      return <CanvasImage item={item} />;

    case "html":
      return (
        <iframe
          srcDoc={typeof item.data === "string" ? item.data : ""}
          title={item.title}
          className="w-full border-0 rounded"
          style={{ minHeight: 200 }}
          sandbox="allow-scripts"
        />
      );

    default:
      return (
        <pre className="text-xs bg-[var(--color-surface-3)] rounded p-3 overflow-x-auto">
          {typeof item.data === "string"
            ? item.data
            : JSON.stringify(item.data, null, 2)}
        </pre>
      );
  }
}

function CanvasImage({ item }: { item: CanvasItemType }) {
  const dataStr = typeof item.data === "string" ? item.data : "";
  // If data looks like base64 (no slashes, long string), build a data URL
  const src = dataStr.startsWith("data:")
    ? dataStr
    : dataStr.length > 100 && !dataStr.includes("/")
      ? `data:image/png;base64,${dataStr}`
      : item.file
        ? `/api/canvas/assets/${item.file}`
        : dataStr;

  return (
    <img src={src} alt={item.title} className="max-w-full rounded" />
  );
}

function DataFrameTable({ data }: { data: unknown }) {
  if (!Array.isArray(data) || data.length === 0) {
    return (
      <pre className="text-xs">{JSON.stringify(data, null, 2)}</pre>
    );
  }

  const headers = Object.keys(data[0] as Record<string, unknown>);

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {headers.map((h) => (
              <th
                key={h}
                className="px-3 py-1.5 text-left text-xs font-semibold bg-[var(--color-surface-3)] border border-[var(--color-border)]"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(data as Record<string, unknown>[]).map((row, i) => (
            <tr key={i}>
              {headers.map((h) => (
                <td
                  key={h}
                  className="px-3 py-1 border border-[var(--color-border)] text-[var(--color-text)]"
                >
                  {String(row[h] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MermaidDiagram({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "default" });
        if (cancelled || !ref.current) return;
        const { svg } = await mermaid.render(
          `mermaid-${Date.now()}`,
          code
        );
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
        }
      } catch (err) {
        console.error("Mermaid render error:", err);
        if (ref.current) {
          ref.current.textContent = code;
        }
      }
    })();
    return () => { cancelled = true; };
  }, [code]);

  return <div ref={ref} className="overflow-x-auto" />;
}
