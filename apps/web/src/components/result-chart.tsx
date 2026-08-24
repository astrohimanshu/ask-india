"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "@/lib/api";

const PALETTE = ["var(--color-saffron)", "var(--color-chart-2)", "var(--color-chart-3)", "var(--color-chart-4)"];

function toNumber(v: unknown): number | null {
  if (typeof v === "number") return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

export function ResultChart({ spec, rows }: { spec: ChartSpec; rows: Record<string, unknown>[] }) {
  if (spec.type === "table" || !spec.x || spec.y.length === 0 || rows.length < 2) return null;
  const data = rows.map((r) => {
    const out: Record<string, unknown> = { [spec.x as string]: String(r[spec.x as string]) };
    for (const y of spec.y) out[y] = toNumber(r[y]);
    return out;
  });
  const Chart = spec.type === "line" ? LineChart : BarChart;
  return (
    <figure className="mt-4 rounded-lg border border-border/60 bg-card p-3">
      {spec.title ? (
        <figcaption className="mb-2 text-sm font-medium text-foreground">{spec.title}</figcaption>
      ) : null}
      <ResponsiveContainer width="100%" height={260}>
        <Chart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis dataKey={spec.x} tick={{ fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 11 }} width={70} tickFormatter={(v: number) => Intl.NumberFormat("en-IN", { notation: "compact" }).format(v)} />
          <Tooltip formatter={(v) => Intl.NumberFormat("en-IN").format(Number(v))} />
          {spec.y.length > 1 ? <Legend /> : null}
          {spec.y.map((key, i) =>
            spec.type === "line" ? (
              <Line key={key} type="monotone" dataKey={key} stroke={PALETTE[i % PALETTE.length]} dot={false} strokeWidth={2} />
            ) : (
              <Bar key={key} dataKey={key} fill={PALETTE[i % PALETTE.length]} radius={[3, 3, 0, 0]} />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </figure>
  );
}
