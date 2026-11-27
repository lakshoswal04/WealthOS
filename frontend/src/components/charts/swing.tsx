"use client";

/**
 * Charts for the swing models (Swing Lab, model picks).
 *
 * Same conventions as components/charts: fixed hue order, one y-axis, a
 * legend whenever there are two or more series, a tooltip on every mark.
 * Benchmarks are drawn dashed in a muted ink so the eye goes to the model.
 */

import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { monthLabel, percent } from "@/lib/format";
import { AXIS, CHART, GRID, LEGEND, STATIC_SERIES, TOOLTIP_LABEL_STYLE, TOOLTIP_STYLE, decimate, seriesColor } from "@/lib/viz";

function Frame({ height, children }: { height: number; children: React.ReactElement }) {
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
    </div>
  );
}

export interface GrowthSeries { key: string; name: string; points: { date: string; value: number }[]; benchmark?: boolean }

/** Growth of ₹1 for several books on one date axis. */
export function GrowthCurves({ series, height = 300, log = true }: { series: GrowthSeries[]; height?: number; log?: boolean }) {
  const byDate = new Map<string, Record<string, number | string>>();
  for (const s of series) {
    for (const p of s.points) {
      const row = byDate.get(p.date) ?? { date: p.date };
      row[s.key] = p.value;
      byDate.set(p.date, row);
    }
  }
  const rows = [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const data = decimate(rows, 500).map(({ value }) => value);
  let modelIndex = 0;
  return (
    <Frame height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="date" {...AXIS} minTickGap={56} tickFormatter={monthLabel} />
        <YAxis {...AXIS} width={48} scale={log ? "log" : "auto"} domain={["auto", "auto"]} allowDataOverflow
          tickFormatter={(v: number) => `${v.toFixed(v < 2 ? 2 : 1)}×`} />
        <ReferenceLine y={1} stroke={CHART.axis} strokeDasharray="3 3" />
        <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} labelFormatter={(l: string) => l}
          formatter={(v: number, name: string) => [`${v.toFixed(2)}×`, name]} />
        <Legend verticalAlign="top" align="right" {...LEGEND} />
        {series.map((s) => {
          const color = s.benchmark ? CHART.inkMuted : seriesColor(modelIndex++);
          return (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={color}
              strokeWidth={s.benchmark ? 1.6 : 2} strokeDasharray={s.benchmark ? "4 3" : undefined}
              dot={false} connectNulls {...STATIC_SERIES} />
          );
        })}
      </LineChart>
    </Frame>
  );
}

/** Mean daily rank IC per test year, one bar group per year. */
export function ICByYear({ rows, series }: {
  rows: { year: string; [model: string]: number | string | null }[];
  series: { key: string; name: string }[];
}) {
  return (
    <Frame height={260}>
      <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="year" {...AXIS} />
        <YAxis {...AXIS} width={52} tickFormatter={(v: number) => v.toFixed(2)} />
        <ReferenceLine y={0} stroke={CHART.axis} />
        <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL_STYLE}
          formatter={(v: number, name: string) => [v === null ? "—" : v.toFixed(3), name]} />
        <Legend verticalAlign="top" align="right" {...LEGEND} />
        {series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.name} fill={seriesColor(i)} radius={[2, 2, 0, 0]} {...STATIC_SERIES} />
        ))}
      </BarChart>
    </Frame>
  );
}

const REGIME_COLORS = { calm: "var(--up)", normal: "var(--ink-muted)", stress: "var(--down)" } as const;

/** Filtered regime probabilities over time, stacked to 100%. */
export function RegimeTimeline({ points, height = 220 }: {
  points: { date: string; calm: number; normal: number; stress: number }[]; height?: number;
}) {
  const data = decimate(points, 600).map(({ value }) => value);
  return (
    <Frame height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }} stackOffset="expand">
        <CartesianGrid {...GRID} />
        <XAxis dataKey="date" {...AXIS} minTickGap={56} tickFormatter={monthLabel} />
        <YAxis {...AXIS} width={44} tickFormatter={(v: number) => percent(v, 0)} />
        <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL_STYLE}
          formatter={(v: number, name: string) => [percent(v, 0), name]} />
        <Legend verticalAlign="top" align="right" {...LEGEND} />
        {(["calm", "normal", "stress"] as const).map((k) => (
          <Area key={k} type="stepAfter" dataKey={k} name={k[0].toUpperCase() + k.slice(1)} stackId="r"
            stroke={REGIME_COLORS[k]} fill={REGIME_COLORS[k]} fillOpacity={0.35} strokeWidth={1} {...STATIC_SERIES} />
        ))}
      </AreaChart>
    </Frame>
  );
}

/**
 * A 10-session return range on a shared scale: the bar spans the 80% range,
 * the tick marks the median, zero is the hairline.
 */
export function RangeBar({ low, mid, high, scale = 0.15 }: {
  low: number | null; mid: number | null; high: number | null; scale?: number;
}) {
  if (low === null || high === null) return <span className="text-[var(--ink-faint)]">—</span>;
  const pos = (v: number) => `${Math.min(100, Math.max(0, ((v + scale) / (2 * scale)) * 100))}%`;
  return (
    <div className="flex items-center gap-2" title={`80% range ${percent(low, 1, true)} to ${percent(high, 1, true)}`}>
      <span className="tabular w-12 text-right text-caption text-[var(--down)]">{percent(low, 1, true)}</span>
      <div className="relative h-2 w-28 rounded-full bg-[var(--surface-3)]">
        <span className="absolute top-[-3px] h-[14px] w-px bg-[var(--hairline-strong)]" style={{ left: pos(0) }} />
        <span className="absolute top-0 h-2 rounded-full bg-[var(--accent-dim,var(--ink-faint))]"
          style={{ left: pos(low), width: `calc(${pos(high)} - ${pos(low)})` }} />
        {mid !== null && <span className="absolute top-[-2px] h-3 w-[2px] rounded bg-[var(--ink-primary)]" style={{ left: pos(mid) }} />}
      </div>
      <span className="tabular w-12 text-caption text-[var(--up)]">{percent(high, 1, true)}</span>
    </div>
  );
}
