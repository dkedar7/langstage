import { Globe, ExternalLink } from "lucide-react";
import type { BrowserViewState } from "../types";

interface BrowserPanelProps {
  browser: BrowserViewState;
}

export function BrowserPanel({ browser }: BrowserPanelProps) {
  if (browser.status === "idle" && !browser.latestFrame) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 px-6">
        <div className="w-10 h-10 rounded-lg bg-[var(--color-surface-3)] flex items-center justify-center">
          <Globe size={20} className="text-[var(--color-text-muted)]" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-[var(--color-text-secondary)]">No browser active</p>
          <p className="text-xs text-[var(--color-text-muted)] mt-1">
            The browser will appear here when the agent navigates to a page
          </p>
        </div>
      </div>
    );
  }

  const statusColor =
    browser.status === "running"
      ? "bg-[var(--color-success)]"
      : browser.status === "navigating"
        ? "bg-yellow-400 animate-pulse"
        : "bg-[var(--color-text-muted)]";

  return (
    <div className="flex flex-col h-full">
      {/* URL bar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--color-border)]">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusColor}`} />
        <div className="flex-1 min-w-0 text-xs text-[var(--color-text-secondary)] truncate font-mono bg-[var(--color-surface-3)] rounded px-2 py-1">
          {browser.currentUrl || "about:blank"}
        </div>
        {browser.currentUrl && (
          <a
            href={browser.currentUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-shrink-0 p-1 rounded hover:bg-[var(--color-surface-3)] transition-colors"
            title="Open in browser"
          >
            <ExternalLink size={13} className="text-[var(--color-text-muted)]" />
          </a>
        )}
      </div>

      {/* Frame display */}
      <div className="flex-1 overflow-hidden bg-[var(--color-surface-3)] flex items-center justify-center">
        {browser.latestFrame ? (
          <img
            src={`data:image/jpeg;base64,${browser.latestFrame}`}
            alt="Browser view"
            className="max-w-full max-h-full object-contain"
            style={{
              aspectRatio: `${browser.frameWidth} / ${browser.frameHeight}`,
            }}
          />
        ) : (
          <p className="text-xs text-[var(--color-text-muted)]">Waiting for first frame...</p>
        )}
      </div>
    </div>
  );
}
