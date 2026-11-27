"use client";

/**
 * The application frame now lives in components/trade/app-shell.tsx (chat
 * sidebar, index ticker, trading navigation). This module keeps the names
 * the analytics pages import, so they did not need rewriting when they
 * moved under /analysis.
 */

export { AppShell as Shell } from "@/components/trade/app-shell";

/** Page heading used across the analytics pages. */
export function PageHead({ title, lede, aside, eyebrow }: {
  title: string; lede?: string; aside?: React.ReactNode; eyebrow?: string;
}) {
  return (
    <div className="rise mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && (
          <div className="mb-2 text-micro font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
            {eyebrow}
          </div>
        )}
        <h1 className="display text-display leading-none tracking-tight text-[var(--ink-primary)]">
          {title}
        </h1>
        {lede && (
          <p className="mt-2.5 max-w-2xl text-body leading-relaxed text-[var(--ink-secondary)]">
            {lede}
          </p>
        )}
      </div>
      {aside}
    </div>
  );
}
