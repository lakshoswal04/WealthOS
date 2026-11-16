"use client";

import clsx from "clsx";
import Link from "next/link";
import type { ReactNode } from "react";

/* ─────────────────────────── surfaces ─────────────────────────── */

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={clsx(
        "grain relative overflow-hidden rounded-[var(--radius)] border",
        "border-[var(--hairline)] bg-[var(--surface-2)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, action }: {
  title: ReactNode; subtitle?: ReactNode; action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[var(--hairline)] px-5 py-4">
      <div className="min-w-0">
        <h2 className="display text-[17px] leading-tight text-[var(--ink-primary)]">{title}</h2>
        {subtitle && (
          <p className="mt-1 text-[12.5px] leading-snug text-[var(--ink-secondary)]">{subtitle}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("px-5 py-4", className)}>{children}</div>;
}

/* ─────────────────────────── figures ─────────────────────────── */

export function Stat({ label, value, sub, tone, hint }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: string; hint?: string;
}) {
  return (
    <div className="min-w-0" title={hint}>
      <div className="text-[11px] font-medium uppercase tracking-[0.09em] text-[var(--ink-muted)]">
        {label}
      </div>
      <div className={clsx("tabular mt-1.5 text-[26px] leading-none", tone ?? "text-[var(--ink-primary)]")}>
        {value}
      </div>
      {sub && <div className="mt-1.5 text-[12.5px] text-[var(--ink-secondary)]">{sub}</div>}
    </div>
  );
}

/** A labelled 0–100 meter. The number is always shown: the bar alone would
 *  make the value readable only by eye. */
export function Meter({ value, max = 100, color }: { value: number; max?: number; color?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--surface-3)]">
      <div
        className="h-full rounded-full transition-[width] duration-700"
        style={{ width: `${pct}%`, background: color ?? "var(--accent)" }}
      />
    </div>
  );
}

export function Badge({ tone = "neutral", children }: {
  tone?: "neutral" | "good" | "warning" | "serious" | "critical" | "accent";
  children: ReactNode;
}) {
  const tones: Record<string, string> = {
    neutral: "border-[var(--hairline)] bg-[var(--surface-3)] text-[var(--ink-secondary)]",
    good: "border-[color-mix(in_oklab,var(--good)_40%,transparent)] bg-[color-mix(in_oklab,var(--good)_14%,transparent)] text-[#5ddc5d]",
    warning: "border-[color-mix(in_oklab,var(--warning)_40%,transparent)] bg-[color-mix(in_oklab,var(--warning)_14%,transparent)] text-[#e8b84b]",
    serious: "border-[color-mix(in_oklab,var(--serious)_40%,transparent)] bg-[color-mix(in_oklab,var(--serious)_14%,transparent)] text-[#f08a5d]",
    critical: "border-[color-mix(in_oklab,var(--critical)_45%,transparent)] bg-[color-mix(in_oklab,var(--critical)_14%,transparent)] text-[#ff8f8f]",
    accent: "border-[var(--accent-dim)] bg-[color-mix(in_oklab,var(--accent)_14%,transparent)] text-[var(--accent)]",
  };
  return (
    <span className={clsx(
      "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-[3px] text-[11px] font-medium",
      tones[tone],
    )}>
      {children}
    </span>
  );
}

/* ─────────────────────────── controls ─────────────────────────── */

export function Button({ variant = "primary", className, ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }
) {
  const variants = {
    primary: "bg-[var(--accent)] text-[var(--accent-ink)] hover:bg-[#f0b254] disabled:bg-[var(--accent-dim)]",
    ghost: "border border-[var(--hairline)] bg-transparent text-[var(--ink-primary)] hover:bg-[var(--surface-3)]",
    danger: "border border-[color-mix(in_oklab,var(--critical)_45%,transparent)] bg-transparent text-[#ff8f8f] hover:bg-[color-mix(in_oklab,var(--critical)_12%,transparent)]",
  };
  return (
    <button
      {...rest}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-[8px] px-3.5 py-2 text-[13px] font-medium",
        "transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
        "focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60",
        variants[variant], className,
      )}
    />
  );
}

export function Field({ label, hint, children }: {
  label: string; hint?: string; children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12px] font-medium text-[var(--ink-secondary)]">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11.5px] text-[var(--ink-muted)]">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-[8px] border border-[var(--hairline)] bg-[var(--surface-1)] px-3 py-2 " +
  "text-[13.5px] text-[var(--ink-primary)] placeholder:text-[var(--ink-muted)] " +
  "focus:border-[var(--accent-dim)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-dim)]";

/* ─────────────────────────── states ─────────────────────────── */

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 text-[13px] text-[var(--ink-secondary)]">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--surface-3)] border-t-[var(--accent)]" />
      {label ?? "Loading…"}
    </div>
  );
}

/** Explains why there is nothing to show and what to do next, rather than
 *  leaving a blank panel. */
export function Empty({ title, body, action }: {
  title: string; body?: string; action?: { label: string; href: string };
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <p className="display text-[16px] text-[var(--ink-primary)]">{title}</p>
      {body && <p className="max-w-sm text-[13px] leading-relaxed text-[var(--ink-secondary)]">{body}</p>}
      {action && (
        <Link
          href={action.href}
          className="mt-2 rounded-[8px] bg-[var(--accent)] px-3.5 py-2 text-[13px] font-medium text-[var(--accent-ink)] hover:bg-[#f0b254]"
        >
          {action.label}
        </Link>
      )}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-[8px] border border-[color-mix(in_oklab,var(--critical)_40%,transparent)] bg-[color-mix(in_oklab,var(--critical)_10%,transparent)] px-4 py-3 text-[13px] text-[#ffb3b3]">
      {message}
    </div>
  );
}

/** Model-backed panels say when a figure could not be computed, instead of
 *  rendering an empty chart. */
export function Unavailable({ reason }: { reason?: string }) {
  return (
    <div className="px-5 py-8 text-center">
      <p className="text-[13px] text-[var(--ink-secondary)]">
        {reason ?? "This measurement is not available yet."}
      </p>
    </div>
  );
}

export function Hairline() {
  return <div className="h-px w-full bg-[var(--hairline)]" />;
}

/** Assumptions travel with the numbers they produced. */
export function Assumptions({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid gap-x-6 gap-y-1.5 text-[11.5px] sm:grid-cols-2">
      {items.map(([term, value]) => (
        <div key={term} className="flex justify-between gap-3 border-b border-dashed border-[var(--hairline)] py-1">
          <dt className="text-[var(--ink-muted)]">{term}</dt>
          <dd className="tabular text-right text-[var(--ink-secondary)]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
