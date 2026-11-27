"use client";

/**
 * The application frame now lives in components/trade/app-shell.tsx (chat
 * sidebar, index ticker, trading navigation). This module keeps the names
 * the analytics pages import, so they did not need rewriting when they
 * moved under /analysis.
 */

import { editorial } from "@/lib/editorial";

export { AppShell as Shell } from "@/components/trade/app-shell";

/** Page heading used across the analytics pages. */
export function PageHead({ title, lede, aside, eyebrow }: {
  title: string; lede?: string; aside?: React.ReactNode; eyebrow?: string;
}) {
  return (
    <div className="rise mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && (
          <div className="label mb-3 text-[var(--accent)]">
            {eyebrow}
          </div>
        )}
        <h1 className="display text-display text-[var(--ink-primary)]">
          {editorial(title)}
        </h1>
        {lede && (
          <p className="mt-3 max-w-2xl text-body-lg leading-relaxed text-[var(--ink-secondary)]">
            {lede}
          </p>
        )}
      </div>
      {aside}
    </div>
  );
}
