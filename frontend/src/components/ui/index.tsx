"use client";

import clsx from "clsx";
import Link from "next/link";
import type { ReactNode } from "react";

/* ─────────────────────────── surfaces ─────────────────────────── */

export function Card({ className, tone = "default", children, ...rest }:
  React.HTMLAttributes<HTMLDivElement> & { tone?: "default" | "accent" | "flat" }
) {
  return (
    <div
      {...rest}
      className={clsx(
        "grain edge-lit relative overflow-hidden rounded-[var(--radius)] border backdrop-blur-[2px]",
        tone === "accent"
          ? "border-[var(--accent-dim)] bg-[var(--glass-strong)] shadow-[var(--glow-accent)]"
          : tone === "flat"
            ? "border-[var(--hairline)] bg-[var(--surface-1)]"
            : "border-[var(--hairline)] bg-[var(--glass)] shadow-[var(--lift-2)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, action, eyebrow }: {
  title: ReactNode; subtitle?: ReactNode; action?: ReactNode; eyebrow?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[var(--hairline)] px-5 py-4">
      <div className="min-w-0">
        {eyebrow && (
          <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--accent)]">
            {eyebrow}
          </div>
        )}
        <h2 className="display text-[17.5px] leading-tight text-[var(--ink-primary)]">{title}</h2>
        {subtitle && (
          <p className="mt-1.5 max-w-prose text-[12.5px] leading-relaxed text-[var(--ink-secondary)]">
            {subtitle}
          </p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("px-5 py-4", className)}>{children}</div>;
}

export function Section({ title, lede, children, id }: {
  title: string; lede?: string; children: ReactNode; id?: string;
}) {
  return (
    <section id={id} className="mt-9 first:mt-0">
      <div className="mb-4">
        <h2 className="display text-[22px] leading-tight text-[var(--ink-primary)]">{title}</h2>
        {lede && (
          <p className="mt-1.5 max-w-3xl text-[13px] leading-relaxed text-[var(--ink-secondary)]">
            {lede}
          </p>
        )}
      </div>
      {children}
    </section>
  );
}

/* ─────────────────────────── figures ─────────────────────────── */

export function Stat({ label, value, sub, tone, hint, size = "md" }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: string; hint?: string;
  size?: "sm" | "md" | "lg";
}) {
  const sizes = { sm: "text-[19px]", md: "text-[26px]", lg: "text-[34px]" };
  return (
    <div className="min-w-0" title={hint}>
      <div className="text-[10.5px] font-medium uppercase tracking-[0.13em] text-[var(--ink-muted)]">
        {label}
      </div>
      <div className={clsx("tabular mt-2 leading-none", sizes[size], tone ?? "text-[var(--ink-primary)]")}>
        {value}
      </div>
      {sub && <div className="mt-2 text-[12px] leading-snug text-[var(--ink-secondary)]">{sub}</div>}
    </div>
  );
}

/** A labelled 0–100 meter. The number is always shown alongside: the bar
 *  alone would make the value readable only by eye. */
export function Meter({ value, max = 100, color }: { value: number; max?: number; color?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--surface-3)]">
      <div
        className="h-full rounded-full transition-[width] duration-[900ms] ease-[var(--ease)]"
        style={{
          width: `${pct}%`,
          background: color ?? "linear-gradient(90deg, var(--accent-dim), var(--accent))",
        }}
      />
    </div>
  );
}

export function Badge({ tone = "neutral", children }: {
  tone?: "neutral" | "good" | "warning" | "serious" | "critical" | "accent";
  children: ReactNode;
}) {
  const tones: Record<string, string> = {
    neutral: "border-[var(--hairline-strong)] bg-[var(--surface-3)] text-[var(--ink-secondary)]",
    good: "border-[color-mix(in_oklab,var(--good)_40%,transparent)] bg-[color-mix(in_oklab,var(--good)_13%,transparent)] text-[var(--good-ink)]",
    warning: "border-[color-mix(in_oklab,var(--warning)_40%,transparent)] bg-[color-mix(in_oklab,var(--warning)_13%,transparent)] text-[var(--warning-ink)]",
    serious: "border-[color-mix(in_oklab,var(--serious)_40%,transparent)] bg-[color-mix(in_oklab,var(--serious)_13%,transparent)] text-[var(--serious-ink)]",
    critical: "border-[color-mix(in_oklab,var(--critical)_45%,transparent)] bg-[color-mix(in_oklab,var(--critical)_13%,transparent)] text-[var(--critical-ink)]",
    accent: "border-[var(--accent-dim)] bg-[var(--accent-wash)] text-[var(--accent)]",
  };
  return (
    <span className={clsx(
      "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-[3px] text-[11px] font-medium",
      tones[tone],
    )}>
      {children}
    </span>
  );
}

/* ─────────────────────────── controls ─────────────────────────── */

export function Button({ variant = "primary", size = "md", className, ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "primary" | "ghost" | "subtle" | "danger"; size?: "sm" | "md" | "lg";
  }
) {
  const variants = {
    primary:
      "bg-gradient-to-b from-[var(--accent-bright)] to-[var(--accent)] text-[var(--accent-ink)] " +
      "shadow-[var(--lift-1)] hover:brightness-110 active:brightness-95 disabled:from-[var(--accent-dim)] disabled:to-[var(--accent-dim)]",
    ghost:
      "border border-[var(--hairline-strong)] bg-transparent text-[var(--ink-primary)] hover:border-[var(--surface-4)] hover:bg-[var(--surface-3)]",
    subtle: "bg-[var(--surface-3)] text-[var(--ink-primary)] hover:bg-[var(--surface-4)]",
    danger:
      "border border-[color-mix(in_oklab,var(--critical)_45%,transparent)] bg-transparent text-[var(--critical-ink)] " +
      "hover:bg-[color-mix(in_oklab,var(--critical)_12%,transparent)]",
  };
  const sizes = { sm: "px-2.5 py-1.5 text-[12px]", md: "px-4 py-2 text-[13px]", lg: "px-5 py-2.5 text-[14px]" };
  return (
    <button
      {...rest}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-[var(--radius-sm)] font-medium",
        "transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-60",
        variants[variant], sizes[size], className,
      )}
    />
  );
}

export function LinkButton({ href, variant = "primary", size = "md", className, children }: {
  href: string; variant?: "primary" | "ghost"; size?: "sm" | "md" | "lg";
  className?: string; children: ReactNode;
}) {
  const variants = {
    primary:
      "bg-gradient-to-b from-[var(--accent-bright)] to-[var(--accent)] text-[var(--accent-ink)] " +
      "shadow-[var(--lift-1)] hover:brightness-110",
    ghost:
      "border border-[var(--hairline-strong)] bg-transparent text-[var(--ink-primary)] hover:bg-[var(--surface-3)]",
  };
  const sizes = { sm: "px-2.5 py-1.5 text-[12px]", md: "px-4 py-2 text-[13px]", lg: "px-5 py-2.5 text-[14px]" };
  return (
    <Link href={href} className={clsx(
      "inline-flex items-center justify-center gap-2 rounded-[var(--radius-sm)] font-medium transition-all duration-150",
      variants[variant], sizes[size], className,
    )}>
      {children}
    </Link>
  );
}

export function Field({ label, hint, children }: {
  label: string; hint?: string; children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12px] font-medium text-[var(--ink-secondary)]">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-[11.5px] leading-snug text-[var(--ink-muted)]">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-1)] px-3 py-2 " +
  "text-[13.5px] text-[var(--ink-primary)] placeholder:text-[var(--ink-faint)] transition-colors " +
  "focus:border-[var(--accent-dim)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-dim)]";

/** A labelled range input that always shows its current value — a slider
 *  whose number is hidden makes the user guess what they set. */
export function Slider({ label, value, min, max, step, format, onChange, hint }: {
  label: string; value: number; min: number; max: number; step: number;
  format: (v: number) => string; onChange: (v: number) => void; hint?: string;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[12px] font-medium text-[var(--ink-secondary)]">{label}</span>
        <span className="tabular text-[13px] text-[var(--ink-primary)]">{format(value)}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={label}
        className="mt-2 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-[var(--surface-3)] accent-[var(--accent)]
                   [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5
                   [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full
                   [&::-webkit-slider-thumb]:bg-[var(--accent)] [&::-webkit-slider-thumb]:shadow-[var(--lift-1)]"
      />
      {hint && <span className="mt-1 block text-[11px] text-[var(--ink-muted)]">{hint}</span>}
    </div>
  );
}

/* ─────────────────────────── states ─────────────────────────── */

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 text-[13px] text-[var(--ink-secondary)]">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--surface-3)] border-t-[var(--accent)]" />
      {label ?? "Loading…"}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("shimmer rounded-[var(--radius-sm)]", className)} />;
}

/** Explains why there is nothing to show and what to do next, rather than
 *  leaving a blank panel. */
export function Empty({ title, body, action }: {
  title: string; body?: string; action?: { label: string; href: string };
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2.5 px-6 py-14 text-center">
      <p className="display text-[17px] text-[var(--ink-primary)]">{title}</p>
      {body && <p className="max-w-md text-[13px] leading-relaxed text-[var(--ink-secondary)]">{body}</p>}
      {action && <LinkButton href={action.href} className="mt-2">{action.label}</LinkButton>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-[color-mix(in_oklab,var(--critical)_40%,transparent)] bg-[color-mix(in_oklab,var(--critical)_9%,transparent)] px-4 py-3 text-[13px] leading-relaxed text-[var(--critical-ink)]">
      {message}
    </div>
  );
}

/** Model-backed panels say when a figure could not be computed, instead of
 *  rendering an empty chart. */
export function Unavailable({ reason }: { reason?: string }) {
  return (
    <div className="px-5 py-10 text-center">
      <p className="mx-auto max-w-md text-[13px] leading-relaxed text-[var(--ink-secondary)]">
        {reason ?? "This measurement is not available yet."}
      </p>
    </div>
  );
}

export function Hairline() {
  return <hr className="rule-fade my-6" />;
}

/** Assumptions travel with the numbers they produced. */
export function Assumptions({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid gap-x-7 gap-y-1.5 text-[11.5px] sm:grid-cols-2">
      {items.map(([term, value]) => (
        <div key={term} className="flex justify-between gap-3 border-b border-dashed border-[var(--hairline)] py-1.5">
          <dt className="text-[var(--ink-muted)]">{term}</dt>
          <dd className="tabular text-right text-[var(--ink-secondary)]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A short explanatory note in the accent voice — used where a number needs
 *  a caveat attached to it rather than buried in a footnote. */
export function Note({ children, tone = "accent" }: {
  children: ReactNode; tone?: "accent" | "muted";
}) {
  return (
    <p className={clsx(
      "rounded-[var(--radius-sm)] border px-3.5 py-2.5 text-[11.5px] leading-relaxed",
      tone === "accent"
        ? "border-[var(--accent-dim)] bg-[var(--accent-wash)] text-[var(--accent)]"
        : "border-[var(--hairline)] bg-[var(--surface-1)] text-[var(--ink-secondary)]",
    )}>
      {children}
    </p>
  );
}

/** A compact key/value row for dense metric lists. */
export function MetricRow({ label, value, tone, note }: {
  label: string; value: ReactNode; tone?: string; note?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-[var(--hairline)] py-2 last:border-0">
      <span className="min-w-0 text-[12.5px] text-[var(--ink-secondary)]">
        {label}
        {note && <span className="ml-2 text-[11px] text-[var(--ink-faint)]">{note}</span>}
      </span>
      <span className={clsx("tabular shrink-0 text-[13px]", tone ?? "text-[var(--ink-primary)]")}>
        {value}
      </span>
    </div>
  );
}
