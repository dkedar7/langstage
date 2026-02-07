import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { TurnUsage, TokenUsage } from "../types";

interface TokenUsageChartProps {
  data: TurnUsage[];
  tokenUsage: TokenUsage;
}

function formatTick(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { payload: TurnUsage }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div
      className="px-3 py-2 rounded shadow-lg border text-xs"
      style={{
        backgroundColor: "var(--color-surface-2)",
        borderColor: "var(--color-border)",
        color: "var(--color-text)",
      }}
    >
      <p className="font-medium mb-1">Turn {d.turn}</p>
      <p style={{ color: "#3b82f6" }}>Input: {d.input.toLocaleString()}</p>
      <p style={{ color: "#14b8a6" }}>Output: {d.output.toLocaleString()}</p>
      <p className="mt-1 font-medium" style={{ color: "var(--color-text)" }}>
        Total: {d.total.toLocaleString()}
      </p>
    </div>
  );
}

export function TokenUsageChart({ data, tokenUsage }: TokenUsageChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-xs text-[var(--color-text-muted)]">
        No usage data yet
      </div>
    );
  }

  return (
    <div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--color-border)"
            opacity={0.3}
          />
          <XAxis
            dataKey="turn"
            stroke="var(--color-text-muted)"
            tick={{ fill: "var(--color-text-muted)", fontSize: 11 }}
            tickLine={false}
          />
          <YAxis
            stroke="var(--color-text-muted)"
            tick={{ fill: "var(--color-text-muted)", fontSize: 11 }}
            tickFormatter={formatTick}
            tickLine={false}
            width={42}
          />
          <Tooltip
            content={<CustomTooltip />}
            cursor={{ fill: "var(--color-surface)", opacity: 0.5 }}
          />
          <Bar dataKey="input" stackId="tokens" fill="#3b82f6" radius={[0, 0, 2, 2]} name="Input" />
          <Bar dataKey="output" stackId="tokens" fill="#14b8a6" radius={[2, 2, 0, 0]} name="Output" />
        </BarChart>
      </ResponsiveContainer>

      {/* Summary row */}
      <div className="grid grid-cols-3 gap-3 mt-3 pt-3 border-t border-[var(--color-border)] text-xs">
        <div>
          <div className="text-[var(--color-text-muted)] mb-0.5">Input</div>
          <div className="font-medium text-[var(--color-text)]">
            {tokenUsage.input.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-[var(--color-text-muted)] mb-0.5">Output</div>
          <div className="font-medium text-[var(--color-text)]">
            {tokenUsage.output.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-[var(--color-text-muted)] mb-0.5">Total</div>
          <div className="font-medium text-[var(--color-text)]">
            {tokenUsage.total.toLocaleString()}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 mt-2 text-[10px] text-[var(--color-text-muted)]">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: "#3b82f6" }} />
          Input
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: "#14b8a6" }} />
          Output
        </span>
      </div>
    </div>
  );
}
