"use client";

import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart,
  type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Bar } from "@/lib/trade-api";
import { num } from "@/lib/tfmt";

/** IST is UTC+5:30. lightweight-charts draws its axis in UTC, so times are
 *  shifted for display; the data itself stays in true UNIX seconds. */
const IST_OFFSET = 19_800;

export interface PriceLineSpec { price: number; title: string; color?: string; dashed?: boolean }
export interface Overlays { sma20?: boolean; sma50?: boolean; ema9?: boolean; ema21?: boolean; vwap?: boolean }
export interface CandleChartHandle { fit: () => void; screenshot: () => string | null }

function css(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** "#3fcf7f" + alpha -> "rgba(63, 207, 127, a)", for the chart's own colour parser. */
function alpha(hex: string, a: number) {
  const h = hex.replace("#", "");
  if (h.length !== 6) return hex;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

const sma = (bars: Bar[], n: number) => bars.map((_, i) => i < n - 1 ? null
  : bars.slice(i - n + 1, i + 1).reduce((s, b) => s + b.close, 0) / n);
const ema = (bars: Bar[], n: number) => {
  const k = 2 / (n + 1); let prev: number | null = null;
  return bars.map((b, i) => { prev = prev === null ? b.close : b.close * k + prev * (1 - k); return i < n - 1 ? null : prev; });
};
/** VWAP that restarts each session (calendar day in IST). */
const vwap = (bars: Bar[]) => {
  let day = -1, pv = 0, vol = 0;
  return bars.map((b) => {
    const d = Math.floor((b.time + IST_OFFSET) / 86_400);
    if (d !== day) { day = d; pv = 0; vol = 0; }
    const typical = (b.high + b.low + b.close) / 3;
    pv += typical * (b.volume || 0); vol += b.volume || 0;
    return vol > 0 ? pv / vol : null;
  });
};

export const CandleChart = forwardRef<CandleChartHandle, {
  bars: Bar[]; kind?: "candles" | "line"; overlays?: Overlays; priceLines?: PriceLineSpec[];
  volume?: boolean; label?: string; compact?: boolean; intraday?: boolean;
}>(function CandleChart({ bars, kind = "candles", overlays = {}, priceLines = [], volume = true, label, compact = false, intraday = true }, ref) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const main = useRef<ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | null>(null);
  const vol = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lines = useRef<ISeriesApi<"Line">[]>([]);
  const plines = useRef<IPriceLine[]>([]);
  const fitted = useRef(false);
  const [legend, setLegend] = useState<Bar | null>(null);

  useImperativeHandle(ref, () => ({
    fit: () => chart.current?.timeScale().fitContent(),
    screenshot: () => chart.current?.takeScreenshot().toDataURL("image/png") ?? null,
  }));

  // Build the chart once per series type; data updates reuse it.
  useEffect(() => {
    if (!box.current) return;
    const up = css("--up", "#3fcf7f"), down = css("--down", "#f2665e");
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--ink-muted", "#8c8c8c"),
                fontSize: compact ? 10 : 11, attributionLogo: !compact },
      grid: { vertLines: { color: css("--grid", "#1b1b1b") }, horzLines: { color: css("--grid", "#1b1b1b") } },
      rightPriceScale: { borderColor: css("--hairline", "#222") },
      timeScale: { borderColor: css("--hairline", "#222"), timeVisible: intraday, secondsVisible: false, rightOffset: 4 },
      crosshair: { mode: CrosshairMode.Normal },
    });
    const series = kind === "candles"
      ? c.addSeries(CandlestickSeries, { upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down })
      : c.addSeries(LineSeries, { color: css("--accent", "#e2b450"), lineWidth: 2 });
    main.current = series;
    if (volume) {
      vol.current = c.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
      c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    }
    c.subscribeCrosshairMove((p) => {
      const d = p.seriesData.get(series) as { open?: number; high?: number; low?: number; close?: number; value?: number } | undefined;
      if (!d) { setLegend(null); return; }
      const close = d.close ?? d.value ?? 0;
      setLegend({ time: Number(p.time), open: d.open ?? close, high: d.high ?? close, low: d.low ?? close, close, volume: 0 });
    });
    chart.current = c;
    fitted.current = false;
    return () => { c.remove(); chart.current = null; main.current = null; vol.current = null; lines.current = []; plines.current = []; };
  }, [kind, volume, compact, intraday]);

  // Data, overlays and price lines.
  useEffect(() => {
    const c = chart.current, s = main.current;
    if (!c || !s) return;
    const t = (b: Bar) => (b.time + IST_OFFSET) as UTCTimestamp;
    if (kind === "candles") {
      (s as ISeriesApi<"Candlestick">).setData(bars.map((b) => ({ time: t(b), open: b.open, high: b.high, low: b.low, close: b.close })));
    } else {
      (s as ISeriesApi<"Line">).setData(bars.map((b) => ({ time: t(b), value: b.close })));
    }
    if (vol.current) {
      const up = css("--up", "#3fcf7f"), down = css("--down", "#f2665e");
      vol.current.setData(bars.map((b) => ({ time: t(b), value: b.volume || 0,
        color: alpha(b.close >= b.open ? up : down, 0.35) })));
    }

    for (const l of lines.current) c.removeSeries(l);
    lines.current = [];
    const add = (values: (number | null)[], color: string) => {
      const l = c.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      l.setData(bars.map((b, i) => values[i] === null ? { time: t(b) } : { time: t(b), value: values[i] as number }));
      lines.current.push(l);
    };
    if (overlays.sma20) add(sma(bars, 20), css("--series-1", "#3987e5"));
    if (overlays.sma50) add(sma(bars, 50), css("--series-2", "#d95926"));
    if (overlays.ema9) add(ema(bars, 9), css("--series-7", "#9085e9"));
    if (overlays.ema21) add(ema(bars, 21), css("--series-5", "#d55181"));
    if (overlays.vwap) add(vwap(bars), css("--accent", "#e2b450"));

    for (const pl of plines.current) s.removePriceLine(pl);
    plines.current = priceLines.map((p) => s.createPriceLine({
      price: p.price, title: p.title, color: p.color ?? css("--ink-muted", "#8c8c8c"), lineWidth: 1,
      lineStyle: p.dashed === false ? LineStyle.Solid : LineStyle.Dashed, axisLabelVisible: true,
    }));

    if (!fitted.current && bars.length) { c.timeScale().fitContent(); fitted.current = true; }
  }, [bars, kind, overlays.sma20, overlays.sma50, overlays.ema9, overlays.ema21, overlays.vwap, priceLines]);

  const last = legend ?? bars[bars.length - 1];
  const upBar = last ? last.close >= last.open : true;
  return (
    <div className="relative h-full w-full">
      {last && label && (
        <div className="pointer-events-none absolute left-3 top-2 z-10 flex flex-wrap items-center gap-x-3 text-small">
          <span className="text-[var(--ink-secondary)]">{label}</span>
          {(["open", "high", "low", "close"] as const).map((k) => (
            <span key={k} className="tabular"><span className="text-[var(--ink-muted)]">{k[0].toUpperCase()}</span>
              <span className={upBar ? "text-[var(--up)]" : "text-[var(--down)]"}>{num(last[k])}</span></span>
          ))}
        </div>
      )}
      <div ref={box} className="h-full w-full" />
    </div>
  );
});
