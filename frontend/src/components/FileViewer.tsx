import { useState } from "react";
import { X, Code, Eye, Download } from "lucide-react";
import type { FilePreview } from "../types";

interface FileViewerProps {
  file: FilePreview;
  onClose: () => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileViewer({ file, onClose }: FileViewerProps) {
  const [showRaw, setShowRaw] = useState(false);
  const hasPreview =
    file.preview_type !== "text" && file.preview_type !== "binary";
  const hasRawData = !!file.data;

  return (
    <div className="flex flex-col h-full bg-[var(--color-surface)]">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--color-border)] bg-[var(--color-surface-2)]">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-medium text-[var(--color-text)] truncate">
            {file.name}
          </span>
          <span className="text-xs text-[var(--color-text-muted)] flex-shrink-0">
            {formatSize(file.size)}
          </span>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {hasPreview && hasRawData && (
            <button
              onClick={() => setShowRaw((v) => !v)}
              className="p-1 rounded hover:bg-[var(--color-surface-3)] transition-colors"
              title={showRaw ? "Preview" : "View raw"}
            >
              {showRaw ? (
                <Eye
                  size={14}
                  className="text-[var(--color-text-secondary)]"
                />
              ) : (
                <Code
                  size={14}
                  className="text-[var(--color-text-secondary)]"
                />
              )}
            </button>
          )}
          <a
            href={`/api/files/download?path=${encodeURIComponent(file.path)}`}
            download={file.name}
            className="p-1 rounded hover:bg-[var(--color-surface-3)] transition-colors"
            title="Download"
          >
            <Download
              size={14}
              className="text-[var(--color-text-secondary)]"
            />
          </a>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-[var(--color-surface-3)] transition-colors"
          >
            <X size={14} className="text-[var(--color-text-secondary)]" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {showRaw && hasRawData ? (
          <RawView content={file.data!} />
        ) : (
          <PreviewContent file={file} />
        )}
      </div>
    </div>
  );
}

function PreviewContent({ file }: { file: FilePreview }) {
  switch (file.preview_type) {
    case "text":
      return <RawView content={file.data || ""} />;

    case "image":
      return (
        <div className="flex items-center justify-center p-6">
          <img
            src={`data:${file.mime || "image/png"};base64,${file.data}`}
            alt={file.name}
            className="max-w-full max-h-[80vh] rounded shadow-sm"
          />
        </div>
      );

    case "html":
      return (
        <iframe
          srcDoc={file.data || ""}
          title={file.name}
          className="w-full h-full border-0"
          sandbox="allow-scripts"
        />
      );

    case "csv":
      return <CsvPreview headers={file.headers} rows={file.rows} />;

    case "pdf":
      return file.data ? (
        <iframe
          src={`data:application/pdf;base64,${file.data}`}
          title={file.name}
          className="w-full h-full border-0"
        />
      ) : (
        <div className="flex flex-col items-center justify-center h-full gap-4 text-[var(--color-text-secondary)]">
          <p className="text-sm">PDF preview is not available.</p>
          <a
            href={`/api/files/download?path=${encodeURIComponent(file.path)}`}
            download={file.name}
            className="text-sm text-[var(--color-primary)] hover:underline"
          >
            Download {file.name}
          </a>
        </div>
      );

    case "binary":
      return (
        <div className="flex flex-col items-center justify-center h-full gap-4 text-[var(--color-text-secondary)]">
          <p className="text-sm">Binary file — cannot display.</p>
          <a
            href={`/api/files/download?path=${encodeURIComponent(file.path)}`}
            download={file.name}
            className="text-sm text-[var(--color-primary)] hover:underline"
          >
            Download {file.name}
          </a>
        </div>
      );
  }
}

function RawView({ content }: { content: string }) {
  const lines = content.split("\n");
  return (
    <pre className="text-sm font-mono leading-relaxed">
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, i) => (
            <tr key={i} className="hover:bg-[var(--color-surface-2)]">
              <td className="text-right pr-3 pl-3 py-0 select-none text-[var(--color-text-muted)] text-xs w-[1%] whitespace-nowrap">
                {i + 1}
              </td>
              <td className="pr-4 py-0 whitespace-pre text-[var(--color-text)]">
                {line || " "}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </pre>
  );
}

function CsvPreview({
  headers,
  rows,
}: {
  headers?: string[];
  rows?: Record<string, string>[];
}) {
  if (!headers?.length || !rows?.length) {
    return (
      <div className="p-4 text-sm text-[var(--color-text-muted)]">
        Empty or invalid CSV file.
      </div>
    );
  }

  return (
    <div className="overflow-auto p-3">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {headers.map((h) => (
              <th
                key={h}
                className="px-3 py-1.5 text-left text-xs font-semibold bg-[var(--color-surface-3)] border border-[var(--color-border)] whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {headers.map((h) => (
                <td
                  key={h}
                  className="px-3 py-1 border border-[var(--color-border)] text-[var(--color-text)] whitespace-nowrap"
                >
                  {row[h] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length >= 50 && (
        <p className="mt-2 text-xs text-[var(--color-text-muted)]">
          Showing first 50 rows. Download to see all data.
        </p>
      )}
    </div>
  );
}
