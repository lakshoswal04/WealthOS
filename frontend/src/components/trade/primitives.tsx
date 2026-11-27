"use client";

import clsx from "clsx";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Unavailable } from "@/lib/clients/http";
import type { PriceSource } from "@/lib/trade-api";
import { pct, tone } from "@/lib/tfmt";

/* ─────────────────────────── icons ─────────────────────────── */

const PATHS: Record<string, ReactNode> = {
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
  sidebar: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  bell: <><path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8" /><path d="M10 20a2 2 0 0 0 4 0" /></>,
  globe: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>,
  chevron: <path d="m6 9 6 6 6-6" />,
  chevronRight: <path d="m9 6 6 6-6 6" />,
  chevronLeft: <path d="m15 6-6 6 6 6" />,
  clip: <path d="m21 11-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7" />,
  mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>,
  wave: <path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4" />,
  bolt: <path d="M13 2 4 14h7l-1 8 9-12h-7z" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  pencil: <path d="M4 20h4L19 9l-4-4L4 16zM13 7l4 4" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  trash: <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />,
  history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></>,
  share: <path d="M12 3v12M7 8l5-5 5 5M5 14v6h14v-6" />,
  expand: <path d="M4 10V4h6M20 14v6h-6M4 4l7 7M20 20l-7-7" />,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7 7 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z" /></>,
  candles: <><path d="M8 3v4M8 15v6M16 3v8M16 17v4" /><rect x="5.5" y="7" width="5" height="8" rx="1" /><rect x="13.5" y="11" width="5" height="6" rx="1" /></>,
  layers: <path d="m12 3 9 5-9 5-9-5zM3 13l9 5 9-5" />,
  bookmark: <path d="M6 3h12v18l-6-4-6 4z" />,
  grid: <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M4 10h16M4 15h16M10 4v16" /></>,
  alarm: <><circle cx="12" cy="13" r="7" /><path d="M12 10v3l2 1M5 3 2 6M19 3l3 3" /></>,
  target: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></>,
  briefcase: <><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M9 7V4h6v3M3 13h18" /></>,
  bars: <path d="M5 20V10M10 20V4M15 20v-8M20 20v-4" />,
  swap: <path d="M7 4 3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7" />,
  sparkle: <path d="M12 3c.5 4 2.5 6.5 7 7-4.5.5-6.5 3-7 7-.5-4-2.5-6.5-7-7 4.5-.5 6.5-3 7-7z" />,
  eyeOff: <><path d="M3 3l18 18M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 9 6 9 6a17 17 0 0 1-3.3 3.8M6.3 7.6C4.3 9.1 3 12 3 12s4 6 9 6c1.4 0 2.7-.4 3.9-1" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  logout: <path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11" />,
  flask: <path d="M9 3h6M10 3v6L4 19a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2l-6-10V3" />,
  upload: <path d="M12 16V4M7 9l5-5 5 5M4 20h16" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  refresh: <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />,
  lock: <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>,
  link: <><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>,
  sliders: <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4" />,
  brain: <path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3h1V4zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3h-1V4z" />,
  wallet: <><rect x="3" y="6" width="18" height="14" rx="2" /><path d="M3 10h18M16 15h2" /></>,
  play: <><circle cx="12" cy="12" r="9" /><path d="m10 8 6 4-6 4z" /></>,
  keyboard: <><rect x="2" y="6" width="20" height="12" rx="2" /><path d="M6 10h0M10 10h0M14 10h0M18 10h0M7 14h10" /></>,
  moon: <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  copy: <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3" /></>,
  download: <path d="M12 4v12M7 11l5 5 5-5M4 20h16" />,
  news: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 9h10M7 13h10M7 17h6" /></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></>,
};

export function Icon({ name, size = 18, className, strokeWidth = 1.7 }: {
  name: keyof typeof PATHS | string; size?: number; className?: string; strokeWidth?: number;
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      className={clsx("shrink-0", className)}>
      {PATHS[name]}
    </svg>
  );
}

/* ─────────────────────────── figures ─────────────────────────── */

/** A percentage change, coloured by direction, that blinks when it moves. */
export function Change({ value, className, parens }: { value: number | null | undefined; className?: string; parens?: boolean }) {
  const prev = useRef(value);
  const [flash, setFlash] = useState<"" | "tick-up" | "tick-down">("");
  useEffect(() => {
    if (prev.current !== undefined && prev.current !== null && value !== null && value !== undefined && value !== prev.current) {
      setFlash(value > prev.current ? "tick-up" : "tick-down");
      const id = window.setTimeout(() => setFlash(""), 900);
      prev.current = value;
      return () => window.clearTimeout(id);
    }
    prev.current = value;
  }, [value]);
  const text = pct(value);
  return <span className={clsx("tabular", tone(value), flash, className)}>{parens ? `(${text})` : text}</span>;
}

/** Where a number came from: the user's own Upstox session, or Yahoo's delayed feed. */
export function SourceTag({ source, className }: { source: PriceSource | string | null | undefined; className?: string }) {
  if (!source || (source !== "live" && source !== "delayed")) return null;
  const live = source === "live";
  return (
    <span title={live ? "Real-time, from your Upstox session." : "From Yahoo Finance, about 15 minutes behind NSE."}
      className={clsx("inline-flex items-center gap-1 rounded-full border border-[var(--hairline-strong)] px-2 py-[1px] text-micro font-medium text-[var(--ink-muted)]", className)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", live ? "bg-[var(--up)]" : "bg-[var(--ink-faint)]")} />
      {live ? "Live · Upstox" : "Delayed ~15m"}
    </span>
  );
}

/**
 * Shown wherever real data is missing, instead of any stand-in number.
 * `upstox_required` failures carry an action (connect or log in again).
 */
export function DataUnavailable({ failure, compact = false, title }: {
  failure: Unavailable | null | undefined; compact?: boolean; title?: string;
}) {
  if (!failure) return null;
  const needsUpstox = failure.code === "upstox_required";
  return (
    <div className={clsx("rounded-[var(--radius-lg)] border border-dashed border-[var(--hairline-strong)] text-center",
      compact ? "px-4 py-5" : "px-6 py-12")}>
      <div className={clsx("mx-auto flex items-center justify-center rounded-full bg-[var(--surface-3)] text-[var(--ink-secondary)]",
        compact ? "mb-2 h-8 w-8" : "mb-4 h-11 w-11")}>
        <Icon name={needsUpstox ? "link" : "eyeOff"} size={compact ? 16 : 20} />
      </div>
      <div className={clsx("font-medium", compact ? "text-body" : "text-body-lg")}>
        {title ?? (needsUpstox ? "Live option data needs Upstox"
          : failure.code === "models_unavailable" ? "Models not trained yet" : "Data unavailable")}
      </div>
      <p className={clsx("mx-auto mt-1.5 max-w-md text-[var(--ink-secondary)]", compact ? "text-small" : "text-body")}>{failure.message}</p>
      {failure.action && (
        <a href={failure.action.href}
          className="mt-4 inline-flex rounded-full bg-[var(--action)] px-5 py-2 text-body font-semibold text-[var(--action-ink)] hover:opacity-90">
          {failure.action.label}
        </a>
      )}
    </div>
  );
}

/* ─────────────────────────── controls ─────────────────────────── */

/** Pill-shaped segmented control, as in the reference's Stocks/Options/Futures. */
export function Segmented<T extends string>({ options, value, onChange, size = "md", className }: {
  options: { value: T; label: ReactNode }[]; value: T; onChange: (v: T) => void;
  size?: "sm" | "md"; className?: string;
}) {
  return (
    <div role="tablist" className={clsx("inline-flex items-center rounded-full border border-[var(--hairline)] bg-[var(--surface-2)] p-1", className)}>
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={o.value === value} onClick={() => onChange(o.value)}
          className={clsx("rounded-full font-medium transition-colors",
            size === "sm" ? "px-3 py-1 text-small" : "px-4 py-1.5 text-body",
            o.value === value ? "bg-[var(--action)] text-[var(--action-ink)]"
              : "text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Underlined text tabs, as in the reference's "Top gainers / Top losers". */
export function TextTabs<T extends string>({ options, value, onChange, size = "lg" }: {
  options: { value: T; label: ReactNode; count?: number }[]; value: T; onChange: (v: T) => void; size?: "md" | "lg";
}) {
  return (
    <div role="tablist" className="flex flex-wrap items-end gap-6">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={o.value === value} onClick={() => onChange(o.value)}
          className={clsx("-mb-px border-b-2 pb-2 font-medium transition-colors",
            size === "lg" ? "text-h3" : "text-body-lg",
            o.value === value ? "border-[var(--accent)] text-[var(--ink-primary)]"
              : "border-transparent text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]")}>
          {o.label}
          {o.count !== undefined && <span className="ml-1.5 text-small text-[var(--ink-muted)]">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Panel({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...rest} className={clsx("rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-[var(--surface-1)] shadow-[var(--lift-1)]", className)}>
      {children}
    </div>
  );
}

/* ─────────────────────────── sparkline ─────────────────────────── */

export function Sparkline({ values, width = 120, height = 34, className }: {
  values: number[]; width?: number; height?: number; className?: string;
}) {
  if (!values || values.length < 2) return <div style={{ width, height }} />;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * width},${height - 2 - ((v - min) / span) * (height - 4)}`);
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} className={className} aria-hidden="true">
      <polyline points={pts.join(" ")} fill="none" strokeWidth={1.5}
        stroke={up ? "var(--up)" : "var(--down)"} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/* ─────────────────────────── modal ─────────────────────────── */

export function Modal({ open, onClose, title, children, width = 440 }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: number;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}
        className="fade w-full rounded-[var(--radius-lg)] border border-[var(--hairline-strong)] bg-[var(--surface-1)] shadow-[var(--lift-3)]"
        style={{ maxWidth: width }}>
        <div className="flex items-center justify-between border-b border-[var(--hairline)] px-5 py-3.5">
          <div className="text-body-lg font-medium">{title}</div>
          <button onClick={onClose} aria-label="Close" className="rounded-full p-1 text-[var(--ink-muted)] hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]">
            <Icon name="x" size={16} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2.5 py-8 text-small text-[var(--ink-muted)]">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--surface-4)] border-t-[var(--ink-primary)]" />
      {label}…
    </div>
  );
}

export function SoonBadge() {
  return <span className="rounded-full border border-[var(--hairline-strong)] px-1.5 py-[1px] text-micro text-[var(--ink-faint)]">Soon</span>;
}
