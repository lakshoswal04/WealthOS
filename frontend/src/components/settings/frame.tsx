"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "@/components/trade/primitives";

/** The frame every account page shares: a title, an info hint and a close (×). */
export function SettingsFrame({ title, hint, action, children }: {
  title: string; hint?: string; action?: ReactNode; children: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-[960px] pb-16 pt-4">
      <div className="mb-10 flex items-center justify-between gap-4">
        <h1 className="display flex items-center gap-2.5 text-[34px] font-semibold tracking-tight">
          {title}
          {hint && <span title={hint} aria-label={hint} className="cursor-help text-body-lg font-normal text-[var(--ink-muted)]">ⓘ</span>}
        </h1>
        <Link href="/home" aria-label="Close" className="rounded-full p-2 text-[var(--ink-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]">
          <Icon name="x" size={22} />
        </Link>
      </div>
      {action && <div className="mb-6 flex justify-end">{action}</div>}
      {children}
    </div>
  );
}

export function SettingsCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-[var(--surface-1)] ${className}`}>{children}</section>;
}

export function Toggle({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition-colors disabled:opacity-50 ${on ? "bg-[var(--buy)]" : "bg-[var(--surface-4)]"}`}>
      <span className={`absolute top-1 h-5 w-5 rounded-full bg-white transition-all ${on ? "left-6" : "left-1"}`} />
    </button>
  );
}

export const fieldClass =
  "w-full rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-4 py-3 text-body-lg " +
  "focus:border-[var(--ink-muted)] focus:outline-none";
