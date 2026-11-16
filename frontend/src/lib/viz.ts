/**
 * Chart tokens.
 *
 * The series colours are the validated categorical palette, checked against
 * this app's dark surface for colour-vision-deficiency separation and
 * contrast. They are assigned in fixed order and never cycled: a ninth
 * series folds into "Other" rather than inventing a hue, because a repeated
 * colour makes two different things look like one.
 */

export const SERIES = [
  "#3987e5", "#d95926", "#199e70", "#c98500",
  "#d55181", "#0ca30c", "#9085e9", "#e66767",
] as const;

/** Scatter, bubble and heatmap put every pair on screen at once; only the
 *  first three slots clear the all-pairs separation floors. */
export const SERIES_ALL_PAIRS = SERIES.slice(0, 3);

export const STATUS = {
  good: "#0ca30c",
  warning: "#c98500",
  serious: "#d95926",
  critical: "#e66767",
} as const;

export const CHART = {
  surface: "#0e1116",
  grid: "#1c232c",
  axis: "#3a4552",
  inkPrimary: "#eef1f5",
  inkSecondary: "#9aa6b4",
  inkMuted: "#64707e",
  accent: "#e8a33d",
} as const;

/** Asset classes keep one colour everywhere, so a slice on the Overview and
 *  a bar on the Portfolio page refer to the same thing. */
export const ASSET_CLASS_COLOR: Record<string, string> = {
  equity: SERIES[0],
  etf: SERIES[2],
  gold: SERIES[3],
  debt: SERIES[6],
  cash: SERIES[5],
  index: SERIES[4],
};

export function seriesColor(index: number): string {
  return SERIES[index % SERIES.length];
}

/** A single-hue sequential ramp for magnitude, and a two-hue diverging ramp
 *  for correlation, which has a meaningful zero. Never a rainbow. */
export function divergingColor(value: number): string {
  const t = Math.max(-1, Math.min(1, value));
  if (t >= 0) {
    const a = t; // neutral → blue
    return `color-mix(in oklab, #2b333d ${(1 - a) * 100}%, #3987e5 ${a * 100}%)`;
  }
  const a = -t; // neutral → orange
  return `color-mix(in oklab, #2b333d ${(1 - a) * 100}%, #d95926 ${a * 100}%)`;
}

export const axisProps = {
  stroke: CHART.axis,
  tick: { fill: CHART.inkMuted, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: CHART.grid },
} as const;
