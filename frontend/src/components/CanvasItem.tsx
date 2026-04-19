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

  // Sections render as plain headings, not cards.
  if (item.type === "section") {
    const level = Math.min(Math.max(item.level ?? 1, 1), 6);
    const text = typeof item.data === "string" ? item.data : "";
    const sizeClass =
      level === 1
        ? "text-xl font-semibold"
        : level === 2
          ? "text-lg font-semibold"
          : "text-base font-medium";
    const HeadingTag = `h${level}` as keyof React.JSX.IntrinsicElements;
    return (
      <div className="group flex items-baseline justify-between border-b border-[var(--color-border)] pb-1 pt-2">
        <HeadingTag className={`${sizeClass} text-[var(--color-text)]`}>
          {text}
        </HeadingTag>
        <button
          onClick={() => onDelete(item.id)}
          className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-[var(--color-surface-3)] transition"
          aria-label="Delete section"
        >
          <X size={14} className="text-[var(--color-text-secondary)]" />
        </button>
      </div>
    );
  }

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
          {typeof item.source_cell === "number" && (
            <span
              className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-[var(--color-surface-3)] text-[var(--color-text-secondary)] border border-[var(--color-border)]"
              title={
                typeof item.execution_count === "number"
                  ? `Produced by cell ${item.source_cell} (execution #${item.execution_count})`
                  : `Produced by cell ${item.source_cell}`
              }
            >
              cell {item.source_cell}
            </span>
          )}
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
        <AutoResizeIframe
          html={typeof item.data === "string" ? item.data : ""}
          title={item.title}
        />
      );

    case "plotly":
      return <PlotlyIframe data={item.data} title={item.title} />;

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

const IFRAME_RESIZE_SCRIPT = `<script>
function _sendHeight(){
  var h=document.documentElement.scrollHeight;
  window.parent.postMessage({type:'iframe-resize',height:h},'*');
}
window.addEventListener('load',function(){_sendHeight();setTimeout(_sendHeight,200);setTimeout(_sendHeight,1000);});
new MutationObserver(_sendHeight).observe(document.body,{childList:true,subtree:true});
</script>`;

function AutoResizeIframe({ html, title }: { html: string; title: string }) {
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

function PlotlyIframe({ data, title }: { data: unknown; title: string }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(400);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const handleMessage = (e: MessageEvent) => {
      if (e.source === iframe.contentWindow && e.data?.type === "iframe-resize") {
        const h = Math.max(200, Math.min(e.data.height, 600));
        setHeight(h);
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [data]);

  const jsonStr = JSON.stringify(data);

  const srcdoc = `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{margin:0;padding:0;}</style>
</head><body>
<div id="chart" style="width:100%;"></div>
<script>
var spec=${jsonStr};
var d=spec.data||[];
var l=Object.assign({margin:{t:30,r:20,b:40,l:50},autosize:true},spec.layout||{});
Plotly.newPlot('chart',d,l,{responsive:true,displayModeBar:false}).then(function(){
  var h=document.getElementById('chart').offsetHeight;
  window.parent.postMessage({type:'iframe-resize',height:h},'*');
});
</script></body></html>`;

  return (
    <iframe
      ref={iframeRef}
      srcDoc={srcdoc}
      title={title || "Plotly chart"}
      sandbox="allow-scripts allow-same-origin"
      className="w-full rounded border-0"
      style={{ height: `${height}px` }}
    />
  );
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
