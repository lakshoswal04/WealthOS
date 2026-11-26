"use client";

/**
 * Chart components.
 *
 * Conventions applied throughout, from the data-visualisation reference:
 *  - categorical hues assigned in fixed order, never cycled;
 *  - one y-axis per chart, never two scales;
 *  - a legend whenever two or more series are present;
 *  - 2px lines, >=8px markers, recessive grid and axes;
 *  - a hover tooltip on every plotted form;
 *  - correlation uses a two-hue diverging ramp with a neutral midpoint,
 *    because it has a meaningful zero; magnitude uses a single hue.
 */

import { useEffect, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart,
  Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import {
  ASSET_CLASS_COLOR, AXIS, CHART, GRID, GRID_VERTICAL, LEGEND, SERIES,
  STATIC_SERIES, STATUS, TOOLTIP_LABEL_STYLE, TOOLTIP_STYLE, decimate,
  divergingColor, seriesColor,
} from "@/lib/viz";
import { monthLabel, percent, rupeesCompact, titleCase } from "@/lib/format";

/* AXIS, TOOLTIP_STYLE, GRID, LEGEND, STATIC_SERIES and decimate all live in
   lib/viz.ts now. They were defined privately here, which is why the chart
   greys had drifted from the interface greys and the tooltip card was a
   hard-coded #11161d rather than the card surface. */

/**
 * A viewport-aware width for a category Y axis.
 *
 * These were fixed at 128-168px. On a 360px phone a 168px axis is 47% of the
 * viewport, leaving the bars less room than their own labels, so the chart
 * stopped being readable exactly where space was tightest. Below the `sm`
 * breakpoint the labels are truncated by the axis instead.
 */
function useCategoryAxisWidth(desktop: number): number {
  const [width, setWidth] = useState(desktop);
  useEffect(() => {
    const measure = () => {
      const viewport = window.innerWidth;
      setWidth(
        viewport < 480 ? Math.min(desktop, 84)
        : viewport < 640 ? Math.min(desktop, 104)
        : desktop,
      );
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [desktop]);
  return width;
}

function Frame({ height = 260, children }: { height?: number; children: React.ReactElement }) {
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
    </div>
  );
}

/* ───────────────────── allocation donut ───────────────────── */

export function AllocationDonut({ data, byAssetClass = true }: {
  data: { label: string; value: number; weight: number }[];
  byAssetClass?: boolean;
}) {
  if (!data.length) return null;
  const colored = data.map((slice, i) => ({
    ...slice,
    fill: byAssetClass
      ? (ASSET_CLASS_COLOR[slice.label.toLowerCase()] ?? seriesColor(i))
      : seriesColor(i),
  }));

  return (
    // The donut is given a fixed basis rather than flexing: inside a flex row
    // a 100%-width chart container consumes the whole track and squeezes the
    // legend until its labels truncate to single characters.
    <div className="flex flex-col items-center gap-5 sm:flex-row">
      <div className="w-full shrink-0 sm:w-[220px]">
      <Frame height={210}>
        <PieChart>
          <Pie
            data={colored} dataKey="value" nameKey="label"
            innerRadius={58} outerRadius={88} paddingAngle={2}
            stroke={CHART.surface} strokeWidth={2}
          >
            {colored.map((slice) => <Cell key={slice.label} fill={slice.fill} />)}
          </Pie>
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_LABEL_STYLE}
            formatter={(value: number, name: string) => [
              `${rupeesCompact(value)} · ${percent((colored.find(c => c.label === name)?.weight) ?? 0, 1)}`,
              titleCase(name),
            ]}
          />
        </PieChart>
      </Frame>
      </div>
      {/* A legend carries identity, so colour is never the only cue. */}
      <ul className="w-full min-w-0 flex-1 space-y-2">
        {colored.map((slice) => (
          <li key={slice.label} className="flex items-center justify-between gap-3 text-small">
            <span className="flex min-w-0 items-center gap-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: slice.fill }} />
              <span className="truncate text-[var(--ink-secondary)]">{titleCase(slice.label)}</span>
            </span>
            <span className="tabular shrink-0 whitespace-nowrap text-[var(--ink-primary)]">
              {percent(slice.weight, 1)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ───────────────────── cumulative return ───────────────────── */

export function CumulativeReturnChart({ dates, portfolio, benchmark }: {
  dates: string[]; portfolio: number[]; benchmark: number[] | null;
}) {
  // Thin to roughly 400 points: more marks than pixels only costs render time.
  // One decimation helper, shared. The old loop dropped the final point
  // whenever the length was not a multiple of the step, so a cumulative
  // return chart could stop short of its own last observation.
  const data = decimate(dates).map(({ value: date, index }) => ({
    date,
    portfolio: portfolio[index],
    benchmark: benchmark ? benchmark[index] : undefined,
  }));

  return (
    <Frame height={280}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="date" {...AXIS} minTickGap={48} tickFormatter={monthLabel} />
        <YAxis {...AXIS} width={52} tickFormatter={(v: number) => percent(v, 0)} />
        <ReferenceLine y={0} stroke={CHART.axis} strokeDasharray="3 3" />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_LABEL_STYLE}
          labelFormatter={monthLabel}
          formatter={(v: number, name: string) => [percent(v, 2), titleCase(name)]}
        />
        <Legend verticalAlign="top" align="right" {...LEGEND} />
        <Line
          type="monotone" dataKey="portfolio" name="Your portfolio"
          stroke={SERIES[0]} strokeWidth={2} dot={false} {...STATIC_SERIES}
        />
        {benchmark && (
          <Line
            type="monotone" dataKey="benchmark" name="NIFTY 50"
            stroke={CHART.inkMuted} strokeWidth={2} strokeDasharray="4 3"
            dot={false} {...STATIC_SERIES}
          />
        )}
      </LineChart>
    </Frame>
  );
}

/* ───────────────────── drawdown ───────────────────── */

export function DrawdownChart({ dates, drawdown }: { dates: string[]; drawdown: number[] }) {
  // The trough is the point of this chart, so losing the last observation
  // to an off-by-one in the old loop mattered here most of all.
  const data = decimate(dates).map(({ value: date, index }) => ({
    date, drawdown: drawdown[index],
  }));

  return (
    <Frame height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
        <defs>
          <linearGradient id="ddFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART.accent} stopOpacity={0.05} />
            <stop offset="100%" stopColor={STATUS.critical} stopOpacity={0.38} />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="date" {...AXIS} minTickGap={48} tickFormatter={monthLabel} />
        <YAxis {...AXIS} width={52} tickFormatter={(v: number) => percent(v, 0)} />
        <ReferenceLine y={0} stroke={CHART.axis} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_LABEL_STYLE}
          labelFormatter={monthLabel}
          formatter={(v: number) => [percent(v, 2), "Below peak"]}
        />
        <Area
          type="monotone" dataKey="drawdown" stroke={STATUS.critical} strokeWidth={2}
          fill="url(#ddFill)" {...STATIC_SERIES}
        />
      </AreaChart>
    </Frame>
  );
}

/* ───────────────────── sector exposure ───────────────────── */

export function SectorBar({ data }: { data: { label: string; weight: number }[] }) {
  const sorted = [...data].sort((a, b) => b.weight - a.weight).slice(0, 12);
  const axisWidth = useCategoryAxisWidth(132);
  return (
    <Frame height={Math.max(180, sorted.length * 28)}>
      <BarChart data={sorted} layout="vertical" margin={{ top: 4, right: 48, bottom: 4, left: 8 }}>
        <CartesianGrid {...GRID_VERTICAL} />
        <XAxis type="number" {...AXIS} tickFormatter={(v: number) => percent(v, 0)} />
        <YAxis type="category" dataKey="label" {...AXIS} width={axisWidth} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} cursor={{ fill: "rgba(255,255,255,0.03)" }}
          formatter={(v: number) => [percent(v, 2), "Weight"]}
        />
        {/* One measure, one hue: a different colour per bar would imply a
            categorical distinction that is not there. */}
        <Bar dataKey="weight" fill={SERIES[0]} radius={[0, 4, 4, 0]} {...STATIC_SERIES} />
      </BarChart>
    </Frame>
  );
}

/* ───────────────────── risk vs return ───────────────────── */

export function RiskReturnScatter({ points }: {
  points: { symbol: string; annualized_return: number; annualized_volatility: number; weight: number }[];
}) {
  const data = points.map((p) => ({
    ...p,
    x: p.annualized_volatility * 100,
    y: p.annualized_return * 100,
    z: Math.max(p.weight * 100, 1.5),
  }));
  return (
    <Frame height={300}>
      <ScatterChart margin={{ top: 12, right: 18, bottom: 16, left: 4 }}>
        <CartesianGrid {...GRID} vertical />
        <XAxis
          type="number" dataKey="x" name="Volatility" {...AXIS}
          unit="%" label={{ value: "Annualised volatility", position: "insideBottom",
            offset: -8, fill: CHART.inkMuted, fontSize: 11 }}
        />
        <YAxis
          type="number" dataKey="y" name="Return" {...AXIS} width={52} unit="%"
          label={{ value: "Return", angle: -90, position: "insideLeft",
            fill: CHART.inkMuted, fontSize: 11 }}
        />
        <ZAxis type="number" dataKey="z" range={[60, 460]} />
        <ReferenceLine y={0} stroke={CHART.axis} strokeDasharray="3 3" />
        <Tooltip
          contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} cursor={{ strokeDasharray: "3 3", stroke: CHART.axis }}
          formatter={(value: number, name: string) =>
            name === "Volatility" || name === "Return"
              ? [`${value.toFixed(2)}%`, name] : [value, name]}
          labelFormatter={() => ""}
          content={({ payload }) => {
            if (!payload?.length) return null;
            const p = payload[0].payload as typeof data[number];
            return (
              <div style={TOOLTIP_STYLE} className="px-3 py-2">
                <div className="font-medium">{p.symbol}</div>
                <div className="tabular mt-1 text-caption text-[var(--ink-secondary)]">
                  Return {p.y.toFixed(2)}% · Volatility {p.x.toFixed(2)}%
                </div>
                <div className="tabular text-caption text-[var(--ink-secondary)]">
                  Weight {(p.weight * 100).toFixed(1)}%
                </div>
              </div>
            );
          }}
        />
        {/* A single series: the marks are one population, distinguished by
            position and size rather than by hue. Labels carry identity. */}
        <Scatter data={data} fill={SERIES[0]} fillOpacity={0.75}
                 stroke={CHART.surface} strokeWidth={2} {...STATIC_SERIES} />
      </ScatterChart>
    </Frame>
  );
}

/* ───────────────────── correlation heatmap ───────────────────── */

export function CorrelationHeatmap({ symbols, matrix }: {
  symbols: string[]; matrix: (number | null)[][];
}) {
  // Correlation runs -1 to +1 around a meaningful zero, so it takes a
  // diverging ramp: two hues with a neutral midpoint, never a rainbow.
  //
  // This was re-implemented inline while lib/viz.ts exported an unused
  // `divergingColor` doing the same thing, so the two could disagree about
  // what zero looks like. One ramp now.
  const color = (v: number | null) =>
    v === null || Number.isNaN(v) ? CHART.grid : divergingColor(v);

  return (
    <div className="overflow-x-auto">
      <table className="border-separate" style={{ borderSpacing: 2 }}>
        <caption className="sr-only">
          Correlation matrix of your holdings, from minus one to plus one
        </caption>
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-[var(--surface-2)]" />
            {symbols.map((s) => (
              <th key={s} className="px-1 pb-1 text-micro font-normal text-[var(--ink-muted)]">
                <span className="block origin-bottom-left -rotate-45 whitespace-nowrap">{s}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {symbols.map((row, i) => (
            <tr key={row}>
              <th className="sticky left-0 z-10 bg-[var(--surface-2)] pr-2 text-right text-micro font-normal text-[var(--ink-secondary)]">
                {row}
              </th>
              {symbols.map((col, j) => {
                const v = matrix[i]?.[j] ?? null;
                return (
                  <td key={col} title={`${row} vs ${col}: ${v === null ? "—" : v.toFixed(3)}`}>
                    <div
                      className="tabular flex h-8 w-11 items-center justify-center rounded-[3px] text-micro"
                      style={{
                        background: color(v),
                        // The value is printed, so the cell is never readable
                        // by colour alone.
                        color: Math.abs(v ?? 0) > 0.55 ? CHART.inkPrimary : CHART.inkSecondary,
                      }}
                    >
                      {v === null ? "—" : v.toFixed(2)}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex items-center gap-3 text-caption text-[var(--ink-muted)]">
        <span>−1 moves opposite</span>
        <span className="h-2.5 w-28 rounded-full"
              style={{
                background:
                  `linear-gradient(90deg, ${SERIES[1]}, var(--surface-3), ${SERIES[0]})`,
              }} />
        <span>+1 moves together</span>
      </div>
    </div>
  );
}

/* ───────────────────── goal projection ───────────────────── */

export function GoalProjectionChart({ path, target }: {
  path: { months: number[]; projected_value: number[] }; target: number;
}) {
  // 180 rather than 400 here, because a goal path is monthly and a fifteen
  // year goal is 180 points to begin with.
  const data = decimate(path.months, 180).map(({ value: month, index }) => ({
    month, value: path.projected_value[index],
  }));

  return (
    <Frame height={240}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="goalFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SERIES[2]} stopOpacity={0.35} />
            <stop offset="100%" stopColor={SERIES[2]} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="month" {...AXIS} minTickGap={40}
               tickFormatter={(m: number) => `${Math.round(m / 12)}y`} />
        <YAxis {...AXIS} width={64} tickFormatter={rupeesCompact} />
        <ReferenceLine
          y={target} stroke={CHART.accent} strokeDasharray="5 4"
          label={{ value: "Target", position: "insideTopRight",
            fill: CHART.accent, fontSize: 11 }}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_LABEL_STYLE}
          labelFormatter={(m: number) => `Month ${m}`}
          formatter={(v: number) => [rupeesCompact(v), "Projected"]}
        />
        <Area type="monotone" dataKey="value" stroke={SERIES[2]} strokeWidth={2}
              fill="url(#goalFill)" {...STATIC_SERIES} />
      </AreaChart>
    </Frame>
  );
}

/* ───────────────────── health score breakdown ───────────────────── */

export function HealthBreakdown({ components }: {
  components: { name: string; score: number | null; weight: number; contribution: number }[];
}) {
  const data = components
    .filter((c) => c.score !== null)
    .map((c) => ({ name: titleCase(c.name), score: c.score as number, weight: c.weight }));

  const axisWidth = useCategoryAxisWidth(128);
  return (
    <Frame height={Math.max(180, data.length * 34)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 44, bottom: 4, left: 8 }}>
        <CartesianGrid {...GRID_VERTICAL} />
        <XAxis type="number" domain={[0, 100]} {...AXIS} />
        <YAxis type="category" dataKey="name" {...AXIS} width={axisWidth} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} cursor={{ fill: "rgba(255,255,255,0.03)" }}
          formatter={(v: number, _n, item) => [
            `${v.toFixed(1)} / 100 · worth ${(item.payload as { weight: number }).weight} pts`,
            "Score",
          ]}
        />
        <ReferenceLine x={70} stroke={CHART.axis} strokeDasharray="3 3" />
        <Bar dataKey="score" radius={[0, 4, 4, 0]} {...STATIC_SERIES}>
          {data.map((entry) => (
            <Cell
              key={entry.name}
              // Status colours, reserved for state and never reused as a
              // series hue. The numeric score is always shown alongside.
              fill={entry.score >= 80 ? STATUS.good
                    : entry.score >= 60 ? STATUS.warning : STATUS.serious}
            />
          ))}
        </Bar>
      </BarChart>
    </Frame>
  );
}

/* ───────────────────── anomaly timeline ───────────────────── */

export function AnomalyTimeline({ timeline, threshold }: {
  timeline: { date: string; score: number; is_anomaly: boolean }[]; threshold: number;
}) {
  return (
    <Frame height={220}>
      <BarChart data={timeline} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="date" {...AXIS} minTickGap={28} tickFormatter={monthLabel} />
        <YAxis {...AXIS} width={48} />
        <ReferenceLine
          y={threshold} stroke={CHART.accent} strokeDasharray="4 3"
          label={{ value: "Threshold", position: "insideTopRight",
            fill: CHART.accent, fontSize: 10.5 }}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} cursor={{ fill: "rgba(255,255,255,0.03)" }}
          labelFormatter={monthLabel}
          formatter={(v: number) => [v.toFixed(4), "Reconstruction error"]}
        />
        <Bar dataKey="score" radius={[3, 3, 0, 0]} {...STATIC_SERIES}>
          {timeline.map((point) => (
            <Cell key={point.date} fill={point.is_anomaly ? STATUS.critical : "var(--surface-4)"} />
          ))}
        </Bar>
      </BarChart>
    </Frame>
  );
}

/* ───────────────────── cluster comparison ───────────────────── */

export function ClusterComparison({ rows }: {
  rows: { feature: string; investor: number; cluster_average: number }[];
}) {
  const data = rows.map((r) => ({
    name: titleCase(r.feature),
    You: r.investor,
    "Cluster average": r.cluster_average,
  }));
  const axisWidth = useCategoryAxisWidth(150);
  return (
    <Frame height={Math.max(200, data.length * 46)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 20, bottom: 4, left: 8 }}>
        <CartesianGrid {...GRID_VERTICAL} />
        <XAxis type="number" {...AXIS} />
        <YAxis type="category" dataKey="name" {...AXIS} width={axisWidth} />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(255,255,255,0.03)" }}
                 formatter={(v: number) => v.toFixed(3)} />
        <Legend verticalAlign="top" align="right" {...LEGEND} />
        <Bar dataKey="You" fill={SERIES[0]} radius={[0, 3, 3, 0]} {...STATIC_SERIES} />
        <Bar dataKey="Cluster average" fill={SERIES[1]} radius={[0, 3, 3, 0]} {...STATIC_SERIES} />
      </BarChart>
    </Frame>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Research charts — used by the Model Lab and Data Quality pages.
   Same conventions as above: fixed hue order, one axis, legend for two or
   more series, recessive furniture, a tooltip on every plotted form.
   ══════════════════════════════════════════════════════════════════════════ */

/** Silhouette against k, with the selected k marked. Shows that k was
 *  chosen by a criterion rather than picked. */
export function SilhouetteByK({ points, chosen }: {
  points: { k: number; silhouette: number; davies_bouldin: number }[]; chosen: number;
}) {
  return (
    <Frame height={240}>
      <LineChart data={points} margin={{ top: 10, right: 14, bottom: 4, left: 4 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="k" {...AXIS}
               label={{ value: "clusters (k)", position: "insideBottom", offset: -2,
                        fill: CHART.inkMuted, fontSize: 11 }} />
        <YAxis {...AXIS} width={48} tickFormatter={(v: number) => v.toFixed(2)} />
        <ReferenceLine x={chosen} stroke={CHART.accent} strokeDasharray="4 3"
                       label={{ value: `k = ${chosen}`, position: "top",
                                fill: CHART.accent, fontSize: 11 }} />
        <Tooltip contentStyle={TOOLTIP_STYLE}
                 labelFormatter={(k: number) => `k = ${k}`}
                 formatter={(v: number) => [v.toFixed(4), "Silhouette"]} />
        <Line type="monotone" dataKey="silhouette" stroke={SERIES[0]} strokeWidth={2}
              dot={{ r: 3, fill: SERIES[0] }} activeDot={{ r: 5 }} {...STATIC_SERIES} />
      </LineChart>
    </Frame>
  );
}

/** The investor cohort projected to two principal components.
 *  Seven clusters exceed the three-slot all-pairs limit for scatter, so the
 *  legend is always present and each group is also labelled by name — colour
 *  is never the only cue. */
export function ClusterMapScatter({ points }: { points: ClusterPoint[] }) {
  const groups = new Map<number, { name: string; data: ClusterPoint[] }>();
  for (const point of points) {
    if (!groups.has(point.cluster)) {
      groups.set(point.cluster, { name: point.cluster_name, data: [] });
    }
    groups.get(point.cluster)!.data.push(point);
  }
  const ordered = [...groups.entries()].sort((a, b) => a[0] - b[0]);

  return (
    <div>
      <Frame height={360}>
        <ScatterChart margin={{ top: 10, right: 16, bottom: 18, left: 4 }}>
          <CartesianGrid {...GRID} vertical />
          <XAxis type="number" dataKey="pc1" {...AXIS}
                 tickFormatter={(v: number) => v.toFixed(1)}
                 label={{ value: "principal component 1", position: "insideBottom",
                          offset: -8, fill: CHART.inkMuted, fontSize: 11 }} />
          <YAxis type="number" dataKey="pc2" {...AXIS} width={48}
                 tickFormatter={(v: number) => v.toFixed(1)}
                 label={{ value: "PC 2", angle: -90, position: "insideLeft",
                          fill: CHART.inkMuted, fontSize: 11 }} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} cursor={{ strokeDasharray: "3 3", stroke: CHART.axis }}
            content={({ payload }) => {
              if (!payload?.length) return null;
              const point = payload[0].payload as ClusterPoint;
              return (
                <div style={TOOLTIP_STYLE} className="px-3 py-2">
                  <div className="font-medium">{point.cluster_name}</div>
                  <div className="mt-1 text-caption text-[var(--ink-secondary)]">
                    generated as {titleCase(point.archetype)}
                  </div>
                </div>
              );
            }}
          />
          {ordered.map(([cluster, group]) => (
            <Scatter key={cluster} name={group.name} data={group.data}
                     fill={seriesColor(cluster)} fillOpacity={0.6}
                     {...STATIC_SERIES} />
          ))}
        </ScatterChart>
      </Frame>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
        {ordered.map(([cluster, group]) => (
          <li key={cluster} className="flex items-center gap-2 text-caption text-[var(--ink-secondary)]">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: seriesColor(cluster) }} />
            {group.name}
            <span className="text-[var(--ink-faint)]">{group.data.length}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface ClusterPoint {
  pc1: number; pc2: number; cluster: number; cluster_name: string; archetype: string;
}

/** Training and holdout loss. The gap between the two lines is the point:
 *  it is what overfitting looks like. */
export function LossCurve({ history }: {
  history: { epoch: number; train_loss: number; holdout_loss?: number; validation_loss?: number }[];
}) {
  const data = history.map((h) => ({
    epoch: h.epoch,
    training: h.train_loss,
    holdout: h.holdout_loss ?? h.validation_loss,
  }));
  return (
    <Frame height={230}>
      <LineChart data={data} margin={{ top: 10, right: 14, bottom: 4, left: 4 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="epoch" {...AXIS}
               label={{ value: "epoch", position: "insideBottom", offset: -2,
                        fill: CHART.inkMuted, fontSize: 11 }} />
        <YAxis {...AXIS} width={62} tickFormatter={(v: number) => v.toFixed(3)} />
        <Tooltip contentStyle={TOOLTIP_STYLE}
                 labelFormatter={(e: number) => `Epoch ${e}`}
                 formatter={(v: number, name: string) => [v.toFixed(6), titleCase(name)]} />
        <Legend verticalAlign="top" align="right" {...LEGEND} />
        <Line type="monotone" dataKey="training" name="Training" stroke={SERIES[0]}
              strokeWidth={2} dot={false} {...STATIC_SERIES} />
        <Line type="monotone" dataKey="holdout" name="Held out" stroke={SERIES[1]}
              strokeWidth={2} strokeDasharray="4 3" dot={false} {...STATIC_SERIES} />
      </LineChart>
    </Frame>
  );
}

/** Forecast skill across horizons, with zero marked. Below the line a model
 *  is worse than the baseline, which is a result worth seeing. */
export function SkillByHorizon({ rows }: {
  rows: { horizon: string; [model: string]: string | number }[]; 
}) {
  const models = Object.keys(rows[0] ?? {}).filter((k) => k !== "horizon");
  return (
    <Frame height={280}>
      <LineChart data={rows} margin={{ top: 10, right: 16, bottom: 4, left: 4 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="horizon" {...AXIS} />
        <YAxis {...AXIS} width={54} tickFormatter={(v: number) => v.toFixed(2)} />
        <ReferenceLine y={0} stroke={CHART.axis} strokeDasharray="4 3"
                       label={{ value: "baseline", position: "insideTopLeft",
                                fill: CHART.inkMuted, fontSize: 10.5 }} />
        <Tooltip contentStyle={TOOLTIP_STYLE}
                 formatter={(v: number, name: string) => [v.toFixed(4), titleCase(name)]} />
        <Legend verticalAlign="top" align="right" {...LEGEND} />
        {models.map((model, index) => (
          <Line key={model} type="monotone" dataKey={model} name={titleCase(model)}
                stroke={seriesColor(index)} strokeWidth={2}
                dot={{ r: 3 }} {...STATIC_SERIES} />
        ))}
      </LineChart>
    </Frame>
  );
}

/** Two models compared across several metrics. Grouped bars, one hue per
 *  model, so the comparison is the shape rather than the colour. */
export function MetricComparisonBars({ metrics, seriesNames }: {
  metrics: { metric: string; [model: string]: string | number }[]; seriesNames: [string, string];
}) {
  return (
    <Frame height={260}>
      <BarChart data={metrics} margin={{ top: 10, right: 16, bottom: 4, left: 4 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="metric" {...AXIS} />
        <YAxis {...AXIS} width={48} domain={[0, 1]} tickFormatter={(v: number) => v.toFixed(1)} />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(255,255,255,0.03)" }}
                 formatter={(v: number) => v.toFixed(4)} />
        <Legend verticalAlign="top" align="right" {...LEGEND} />
        <Bar dataKey={seriesNames[0]} fill={SERIES[0]} radius={[4, 4, 0, 0]} {...STATIC_SERIES} />
        <Bar dataKey={seriesNames[1]} fill={SERIES[1]} radius={[4, 4, 0, 0]} {...STATIC_SERIES} />
      </BarChart>
    </Frame>
  );
}

/** A labelled magnitude matrix — used for archetype against recovered
 *  cluster. One hue, light to dark, because the quantity is a count with no
 *  meaningful midpoint. Every cell prints its value. */
export function CountMatrix({ rows, columns, values, rowLabel, columnLabel }: {
  rows: string[]; columns: string[]; values: number[][];
  rowLabel?: string; columnLabel?: string;
}) {
  const max = Math.max(1, ...values.flat());

  return (
    <div className="overflow-x-auto">
      {columnLabel && (
        <div className="mb-1.5 pl-[150px] text-micro uppercase tracking-[0.12em] text-[var(--ink-faint)]">
          {columnLabel}
        </div>
      )}
      <table className="border-separate" style={{ borderSpacing: 2 }}>
        <caption className="sr-only">
          Feature values by cluster, shaded by magnitude
        </caption>
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-[var(--surface-2)]" />
            {columns.map((column) => (
              <th key={column} className="px-1 pb-1 text-micro font-normal text-[var(--ink-muted)]">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row}>
              <th className="sticky left-0 z-10 w-[150px] bg-[var(--surface-2)] pr-2.5 text-right text-micro font-normal text-[var(--ink-secondary)]">
                {row}
              </th>
              {columns.map((column, j) => {
                const value = values[i]?.[j] ?? 0;
                const intensity = value / max;
                return (
                  <td key={column} title={`${row} → ${column}: ${value}`}>
                    <div
                      className="tabular flex h-9 w-14 items-center justify-center rounded-[3px] text-micro"
                      style={{
                        background:
                          `color-mix(in oklab, ${CHART.grid} ${(1 - intensity) * 100}%, ${SERIES[0]} ${intensity * 100}%)`,
                        color: intensity > 0.45 ? CHART.inkPrimary : CHART.inkMuted,
                      }}
                    >
                      {value || "·"}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rowLabel && (
        <div className="mt-2 text-micro uppercase tracking-[0.12em] text-[var(--ink-faint)]">
          {rowLabel}
        </div>
      )}
    </div>
  );
}

/** A horizontal magnitude bar list — feature importances, recall by type.
 *  One hue: these are one measure, not separate categories. */
export function MagnitudeBars({ items, format, color, domain }: {
  items: { label: string; value: number }[];
  format?: (v: number) => string; color?: string; domain?: [number, number];
}) {
  const data = [...items].sort((a, b) => b.value - a.value);
  const axisWidth = useCategoryAxisWidth(168);
  return (
    <Frame height={Math.max(160, data.length * 30)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 52, bottom: 4, left: 8 }}>
        <CartesianGrid {...GRID_VERTICAL} />
        <XAxis type="number" {...AXIS} domain={domain ?? [0, "auto"]}
               tickFormatter={format ?? ((v: number) => v.toFixed(2))} />
        <YAxis type="category" dataKey="label" {...AXIS} width={axisWidth} />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(255,255,255,0.03)" }}
                 formatter={(v: number) => (format ?? ((x: number) => x.toFixed(4)))(v)} />
        <Bar dataKey="value" fill={color ?? SERIES[0]} radius={[0, 4, 4, 0]} {...STATIC_SERIES} />
      </BarChart>
    </Frame>
  );
}

/** The Monte Carlo fan: nested percentile bands around the median, against
 *  the target. Deliberately not a single line — one line would imply a
 *  precision the simulation does not have. */
export function ProjectionFan({ months, bands, deterministic, target }: {
  months: number[];
  bands: Record<string, number[]>;
  deterministic?: number[];
  target: number;
}) {
  // The fourth copy of the same loop, with a fourth divisor. All four now
  // go through `decimate`.
  const data = decimate(months, 200)
    .map(({ value: month, index }) => {
      const p10 = bands.p10?.[index] ?? 0;
      const p25 = bands.p25?.[index] ?? 0;
      const p75 = bands.p75?.[index] ?? 0;
      const p90 = bands.p90?.[index] ?? 0;
      return {
        month,
        // Stacked offsets: Recharts draws each area from the previous top,
        // so the bands nest instead of overpainting one another.
        base: p10,
        outer: Math.max(0, p25 - p10),
        inner: Math.max(0, p75 - p25),
        outerTop: Math.max(0, p90 - p75),
        median: bands.p50?.[index] ?? 0,
        expected: deterministic?.[index],
        p10, p25, p75, p90,
      };
    });

  return (
    <Frame height={300}>
      <AreaChart data={data} margin={{ top: 10, right: 16, bottom: 4, left: 8 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="month" {...AXIS} minTickGap={42}
               tickFormatter={(m: number) => (m >= 12 ? `${Math.round(m / 12)}y` : `${m}m`)} />
        <YAxis {...AXIS} width={66} tickFormatter={rupeesCompact} />
        <ReferenceLine y={target} stroke={CHART.accent} strokeDasharray="5 4"
                       label={{ value: "Target", position: "insideTopRight",
                                fill: CHART.accent, fontSize: 11 }} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_LABEL_STYLE}
          labelFormatter={(m: number) => `Month ${m}`}
          content={({ payload, label }) => {
            if (!payload?.length) return null;
            const point = payload[0].payload as (typeof data)[number];
            return (
              <div style={TOOLTIP_STYLE} className="px-3 py-2">
                <div className="mb-1 font-medium">Month {label}</div>
                {([["p90", "Best 10%"], ["p75", "Upper quartile"], ["median", "Median"],
                   ["p25", "Lower quartile"], ["p10", "Worst 10%"]] as const).map(([key, name]) => (
                  <div key={key} className="tabular flex justify-between gap-6 text-caption">
                    <span className="text-[var(--ink-secondary)]">{name}</span>
                    <span>{rupeesCompact(point[key as keyof typeof point] as number)}</span>
                  </div>
                ))}
              </div>
            );
          }}
        />
        {/* The transparent base lifts the stack to the p10 line. */}
        <Area dataKey="base" stackId="fan" stroke="none" fill="transparent" {...STATIC_SERIES} />
        <Area dataKey="outer" stackId="fan" stroke="none"
              fill={SERIES[0]} fillOpacity={0.14} {...STATIC_SERIES} />
        <Area dataKey="inner" stackId="fan" stroke="none"
              fill={SERIES[0]} fillOpacity={0.28} {...STATIC_SERIES} />
        <Area dataKey="outerTop" stackId="fan" stroke="none"
              fill={SERIES[0]} fillOpacity={0.14} {...STATIC_SERIES} />
        <Area dataKey="median" stroke={SERIES[0]} strokeWidth={2} fill="none"
              {...STATIC_SERIES} />
        {deterministic && (
          <Area dataKey="expected" stroke={CHART.inkMuted} strokeWidth={1.5}
                strokeDasharray="4 3" fill="none" {...STATIC_SERIES} />
        )}
      </AreaChart>
    </Frame>
  );
}
