import { useState, useRef, useEffect } from "react";
import { Loader2, Printer, RotateCcw, Zap } from "lucide-react";
import type { ConnectionStatus, TokenUsage, TurnUsage } from "../types";
import { TokenUsageChart } from "./TokenUsageChart";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

interface StatusBarProps {
  connectionStatus: ConnectionStatus;
  isStreaming: boolean;
  tokenUsage: TokenUsage;
  usageHistory: TurnUsage[];
  onNewSession: () => void;
}

export function StatusBar({
  connectionStatus,
  isStreaming,
  tokenUsage,
  usageHistory,
  onNewSession,
}: StatusBarProps) {
  const [showChart, setShowChart] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Close on click outside or Escape
  useEffect(() => {
    if (!showChart) return;
    const handleClick = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setShowChart(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowChart(false);
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [showChart]);

  return (
    <div className="flex items-center gap-2.5 text-[11px]">
      <button
        onClick={() => {
          if (window.confirm("Start a new session? This will clear all messages and cannot be undone.")) {
            onNewSession();
          }
        }}
        disabled={isStreaming}
        className="flex items-center gap-1 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
        title="New session"
      >
        <RotateCcw size={10} />
        New
      </button>
      <button
        onClick={() => window.print()}
        className="flex items-center gap-1 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors cursor-pointer"
        title="Print conversation"
      >
        <Printer size={10} />
        Print
      </button>
      {isStreaming && (
        <span className="flex items-center gap-1 text-[var(--color-text-secondary)]">
          <Loader2 size={10} className="animate-spin" />
          Working
        </span>
      )}
      {tokenUsage.total > 0 && (
        <div className="relative" ref={popoverRef}>
          <button
            onClick={() => setShowChart((v) => !v)}
            className="flex items-center gap-1 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors cursor-pointer"
            title="View token usage breakdown"
          >
            <Zap size={10} />
            {formatTokens(tokenUsage.total)} tokens
          </button>

          {showChart && (
            <div className="absolute right-0 top-full mt-2 w-[340px] p-4 rounded-lg shadow-md border border-[var(--color-border)] bg-[var(--color-card)] z-50">
              <div className="text-xs font-medium text-[var(--color-text)] mb-3">
                Token Usage by Turn
              </div>
              <TokenUsageChart data={usageHistory} tokenUsage={tokenUsage} />
            </div>
          )}
        </div>
      )}
      <span className="flex items-center gap-1.5">
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            connectionStatus === "connected"
              ? "bg-[var(--color-success)]"
              : connectionStatus === "error"
                ? "bg-[var(--color-error)]"
                : "bg-[var(--color-text-muted)]"
          }`}
        />
        <span className="text-[var(--color-text-muted)]">
          {connectionStatus === "connected"
            ? "Connected"
            : connectionStatus === "connecting"
              ? "Connecting"
              : connectionStatus === "error"
                ? "Error"
                : "Disconnected"}
        </span>
      </span>
    </div>
  );
}
