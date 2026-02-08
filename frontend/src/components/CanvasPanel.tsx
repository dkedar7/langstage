import { Trash2, Download, Layers } from "lucide-react";
import type { CanvasItem } from "../types";
import { CanvasItemCard } from "./CanvasItem";

interface CanvasPanelProps {
  items: CanvasItem[];
  onDelete: (id: string) => void;
  onClearAll: () => void;
  onExport: () => Promise<string>;
}

export function CanvasPanel({
  items,
  onDelete,
  onClearAll,
  onExport,
}: CanvasPanelProps) {
  const handleExport = async () => {
    const md = await onExport();
    if (!md) return;
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "canvas.md";
    a.click();
    URL.revokeObjectURL(url);
  };

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 px-6">
        <div className="w-10 h-10 rounded-lg bg-[var(--color-surface-3)] flex items-center justify-center">
          <Layers size={20} className="text-[var(--color-text-muted)]" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-[var(--color-text-secondary)]">No canvas items</p>
          <p className="text-xs text-[var(--color-text-muted)] mt-1">
            Charts, tables, and visualizations will be collected here
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--color-border)]">
        <span className="text-xs font-medium text-[var(--color-text-secondary)]">
          {items.length} item{items.length !== 1 ? "s" : ""}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={handleExport}
            className="p-1 rounded hover:bg-[var(--color-surface-3)] transition-colors"
            title="Export as Markdown"
          >
            <Download size={14} className="text-[var(--color-text-secondary)]" />
          </button>
          <button
            onClick={onClearAll}
            className="p-1 rounded hover:bg-[var(--color-surface-3)] transition-colors"
            title="Clear all"
          >
            <Trash2 size={14} className="text-[var(--color-text-secondary)]" />
          </button>
        </div>
      </div>

      {/* Items */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {items.map((item) => (
          <CanvasItemCard key={item.id} item={item} onDelete={onDelete} />
        ))}
      </div>
    </div>
  );
}
