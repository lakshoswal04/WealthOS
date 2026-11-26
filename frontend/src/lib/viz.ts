/**
 * Chart tokens, resolved from the CSS custom properties rather than copied.
 *
 * Every value here used to be a hex literal duplicated from `globals.css`,
 * and six of the seven had drifted apart:
 *
 *   token           viz.ts     globals.css
 *   grid            #1c232c    #1a212a
 *   axis            #3a4552    #3c4654
 *   inkPrimary      #eef1f5    #f2f5f8
 *   inkSecondary    #9aa6b4    #a3b0bf
 *   inkMuted        #6b7889 -> was #64707e
 *   accent          #e8a33d    #d4a24c
 *
 * So charts were drawn with slightly different greys and a visibly different
 * accent from the rest of the interface, and nothing in the stack could
 * notice. The CSS file is now the only place the values live; this module
 * refers to them.
 *
 * `var(--token)` is used directly in SVG presentation attributes, which
 * resolves in every browser this app supports. The single exception is a
 * colour that has to be computed at runtime -- see `readToken`.
 */

const v = (token: string) => `var(--${token})`;

/**
 * The validated categorical palette, in fixed assignment order.
 *
 * Validated against `--surface-1` for lightness band, chroma floor,
 * colour-vision-deficiency separation and 3:1 contrast. A ninth series folds
 * into "Other" rather than cycling: a repeated colour makes two different
 * things look like one.
 */
export const SERIES = [
  v("series-1"), v("series-2"), v("series-3"), v("series-4"),
  v("series-5"), v("series-6"), v("series-7"), v("series-8"),
] as const;

/** Scatter, bubble and heatmap put every pair on screen at once; only the
 *  first three slots clear the all-pairs separation floors. */
export const SERIES_ALL_PAIRS = SERIES.slice(0, 3);

export const STATUS = {
  good: v("good"),
  warning: v("warning"),
  serious: v("serious"),
  critical: v("critical"),
} as const;

export const CHART = {
  surface: v("surface-1"),
  grid: v("grid"),
  axis: v("axis"),
  inkPrimary: v("ink-primary"),
  inkSecondary: v("ink-secondary"),
  inkMuted: v("ink-muted"),
  accent: v("accent"),
  tooltipSurface: v("surface-2"),
  tooltipBorder: v("hairline-strong"),
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

/**
 * Read a token's computed value, for the rare case that needs a real colour.
 *
 * `color-mix()` and SVG attributes both accept `var()`, so this is only for
 * code that must do arithmetic on a colour. Returns an empty string during
 * server rendering, where there is no computed style to read; callers must
 * tolerate that rather than assume a value.
 */
export function readToken(token: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement)
    .getPropertyValue(`--${token}`)
    .trim();
}

/**
 * A two-hue diverging ramp for correlation, which has a meaningful zero.
 * Never a rainbow: a rainbow implies an ordering the data does not have.
 *
 * This was previously unused while `CorrelationHeatmap` re-implemented the
 * same mix inline, so the two could disagree about what zero looks like.
 */
export function divergingColor(value: number): string {
  const t = Math.max(-1, Math.min(1, value));
  const neutral = v("surface-3");
  if (t >= 0) {
    return `color-mix(in oklab, ${neutral} ${(1 - t) * 100}%, ${SERIES[0]} ${t * 100}%)`;
  }
  const a = -t;
  return `color-mix(in oklab, ${neutral} ${(1 - a) * 100}%, ${SERIES[1]} ${a * 100}%)`;
}

/* ──────────────────────────────────────────────────────────────────────────
   Shared chart furniture

   `CartesianGrid` appeared 12 times, `Tooltip contentStyle` 14 times,
   `isAnimationActive={false}` 24 times and `Legend` 5 times with three
   different heights. Each repetition is a chance for one chart to drift from
   the others, and several already had.
   ────────────────────────────────────────────────────────────────────── */

/** Axis defaults. Spread into every XAxis and YAxis. */
export const AXIS = {
  stroke: CHART.axis,
  tick: { fill: CHART.inkMuted, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: CHART.grid },
} as const;

/** Tooltip card styling, matched to the card surface rather than hard-coded. */
export const TOOLTIP_STYLE = {
  background: CHART.tooltipSurface,
  border: `1px solid ${CHART.tooltipBorder}`,
  borderRadius: 8,
  fontSize: 12,
  color: CHART.inkPrimary,
  boxShadow: "0 8px 24px rgb(0 0 0 / 0.45)",
} as const;

export const TOOLTIP_LABEL_STYLE = { color: CHART.inkSecondary } as const;

/** Horizontal rules only. Vertical gridlines on a time axis imply a
 *  precision the monthly sampling does not have. */
export const GRID = { stroke: CHART.grid, vertical: false } as const;

/** For the rare chart whose categories sit on the Y axis. */
export const GRID_VERTICAL = { stroke: CHART.grid, horizontal: false } as const;

/** One legend height everywhere. Three different values meant three
 *  different gaps between a chart and its caption. */
export const LEGEND = {
  height: 28,
  wrapperStyle: { fontSize: 12, color: CHART.inkSecondary },
} as const;

/**
 * Animation is off on every series, deliberately.
 *
 * These charts are read, not watched. A growth animation on a drawdown chart
 * makes the trough arrive late, and anyone comparing two panels sees them
 * disagree until both settle. Spread this rather than repeating the prop.
 */
export const STATIC_SERIES = { isAnimationActive: false } as const;

/**
 * Thin a series to at most `limit` points, keeping the last one.
 *
 * The same loop was copy-pasted four times with three different divisors
 * (400, 400, 180), and all four dropped the final point when the length was
 * not a multiple of the step -- so a drawdown chart could end before its own
 * trough. Keeping the last index is the fix, and having one implementation
 * is what stops the next divisor from being a fourth number.
 */
export function decimate<T>(values: readonly T[], limit = 400): { value: T; index: number }[] {
  if (values.length === 0) return [];
  const step = Math.max(1, Math.ceil(values.length / limit));
  const out: { value: T; index: number }[] = [];
  for (let i = 0; i < values.length; i += step) {
    out.push({ value: values[i], index: i });
  }
  const lastIndex = values.length - 1;
  if (out[out.length - 1].index !== lastIndex) {
    out.push({ value: values[lastIndex], index: lastIndex });
  }
  return out;
}
