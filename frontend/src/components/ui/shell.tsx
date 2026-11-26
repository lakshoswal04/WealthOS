"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";
import { rupeesCompact } from "@/lib/format";

/** Navigation is grouped so the dashboard reads as a wealth service with a
 *  research wing, rather than a flat list of eight equal pages. */
const NAV_GROUPS: { label: string; items: { href: string; label: string; hint: string }[] }[] = [
  {
    label: "Wealth",
    items: [
      { href: "/overview", label: "Overview", hint: "Wealth at a glance" },
      { href: "/portfolio", label: "Portfolio", hint: "Holdings and allocation" },
      { href: "/risk", label: "Risk", hint: "Volatility, drawdown, correlation" },
      { href: "/goals", label: "Goals", hint: "Targets and projections" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { href: "/insights", label: "Insights", hint: "Profile, anomalies, forecast" },
      { href: "/copilot", label: "Copilot", hint: "Ask about your portfolio" },
    ],
  },
  {
    label: "Research",
    items: [
      { href: "/research", label: "Model Lab", hint: "How the models were built" },
      { href: "/data-quality", label: "Data Quality", hint: "Sources and validation" },
    ],
  },
  {
    label: "Account",
    items: [
      { href: "/import", label: "Import", hint: "Upload holdings" },
      { href: "/profile", label: "Profile", hint: "Your investor details" },
    ],
  },
];

const ALL_ITEMS = NAV_GROUPS.flatMap((g) => g.items);

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, loading, signOut } = useAuth();
  const [open, setOpen] = useState(false);

  // A protected page must not flash its chrome before the session resolves.
  useEffect(() => {
    if (!loading && !user && typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }, [loading, user]);

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-body text-[var(--ink-secondary)]">
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--surface-3)] border-t-[var(--accent)]" />
        <span className="ml-3">Loading your portfolio…</span>
      </div>
    );
  }

  const current = ALL_ITEMS.find((i) => i.href === pathname);

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[246px_1fr]">
      {/* The first tab stop on every page. Without it, reaching the content
          past the sidebar means tabbing through every navigation link, on
          every page, every time. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-[var(--radius-sm)] focus:border focus:border-[var(--accent-dim)] focus:bg-[var(--surface-2)] focus:px-4 focus:py-2 focus:text-body focus:text-[var(--ink-primary)]"
      >
        Skip to content
      </a>

      {/* ── sidebar ── */}
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-40 w-[246px] border-r border-[var(--hairline)]",
          "bg-[var(--surface-1)] transition-transform duration-300 lg:static lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-full flex-col">
          <div className="border-b border-[var(--hairline)] px-5 py-5">
            <Link href="/" className="block">
              <div className="display text-h2 leading-none tracking-tight">
                Wealth<span className="metal">OS</span>
              </div>
              <div className="mt-2 text-micro uppercase tracking-[0.2em] text-[var(--ink-faint)]">
                Wealth Intelligence
              </div>
            </Link>
          </div>

          <nav className="flex-1 overflow-y-auto px-3 py-4">
            {NAV_GROUPS.map((group) => (
              <div key={group.label} className="mb-5 last:mb-0">
                <div className="px-3 pb-1.5 text-micro font-semibold uppercase tracking-[0.17em] text-[var(--ink-faint)]">
                  {group.label}
                </div>
                {group.items.map((item) => {
                  const active = pathname === item.href;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setOpen(false)}
                      aria-current={active ? "page" : undefined}
                      className={clsx(
                        "group relative mb-0.5 block rounded-[var(--radius-sm)] px-3 py-2 transition-colors",
                        active
                          ? "bg-[var(--surface-3)] text-[var(--ink-primary)]"
                          : "text-[var(--ink-secondary)] hover:bg-[var(--surface-2)] hover:text-[var(--ink-primary)]",
                      )}
                    >
                      {active && (
                        <span className="absolute inset-y-1.5 left-0 w-[2px] rounded-full bg-[var(--accent)]" />
                      )}
                      <span className="block text-body font-medium">{item.label}</span>
                      <span className="block text-micro leading-snug text-[var(--ink-faint)]">
                        {item.hint}
                      </span>
                    </Link>
                  );
                })}
              </div>
            ))}
          </nav>

          <div className="border-t border-[var(--hairline)] p-3">
            <div className="flex items-center gap-2.5 rounded-[var(--radius-sm)] bg-[var(--surface-2)] px-3 py-2.5">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-b from-[var(--accent-bright)] to-[var(--accent-dim)] text-caption font-semibold text-[var(--accent-ink)]">
                {(user.full_name || user.email).slice(0, 1).toUpperCase()}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-small text-[var(--ink-primary)]">
                  {user.full_name || user.email.split("@")[0]}
                </div>
                <button
                  onClick={signOut}
                  className="text-micro text-[var(--ink-muted)] transition-colors hover:text-[var(--accent)]"
                >
                  Sign out
                </button>
              </div>
            </div>
          </div>
        </div>
      </aside>

      {open && (
        <div className="fixed inset-0 z-30 bg-black/70 backdrop-blur-sm lg:hidden"
             onClick={() => setOpen(false)} />
      )}

      {/* ── content ── */}
      <div className="min-w-0">
        <TopBar title={current?.label} onMenu={() => setOpen((v) => !v)} />

        <main
          id="main"
          className="mx-auto w-full max-w-[1220px] px-4 py-7 sm:px-7 lg:py-9"
        >
          {children}
        </main>

        <footer className="mx-auto w-full max-w-[1220px] px-4 pb-12 sm:px-7">
          <hr className="rule-fade mb-4" />
          <p className="text-caption leading-relaxed text-[var(--ink-faint)]">
            WealthOS is an academic research prototype built for the Polaris School
            of Technology OJT programme. It explains computed portfolio metrics and
            does not provide investment advice. Investor-level data in
            demonstrations is synthetic; market prices are real and
            corporate-action adjusted.
          </p>
        </footer>
      </div>
    </div>
  );
}

/** A persistent bar carrying the portfolio's headline value. On a wealth
 *  service the balance should never be more than a glance away. */
function TopBar({ title, onMenu }: { title?: string; onMenu: () => void }) {
  const summary = useApi(() => api.portfolio().catch(() => null), []);

  return (
    <header className="sticky top-0 z-20 border-b border-[var(--hairline)] bg-[color-mix(in_oklab,var(--surface-0)_82%,transparent)] backdrop-blur-xl">
      <div className="mx-auto flex w-full max-w-[1220px] items-center gap-3 px-4 py-3 sm:px-7">
        <button
          onClick={onMenu}
          aria-label="Toggle navigation"
          className="rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] px-2.5 py-1.5 text-small text-[var(--ink-secondary)] lg:hidden"
        >
          Menu
        </button>
        <span className="display text-body-lg lg:hidden">
          Wealth<span className="metal">OS</span>
        </span>

        <span className="hidden text-small text-[var(--ink-muted)] lg:inline">{title}</span>

        <div className="ml-auto flex items-center gap-5">
          {summary.data && summary.data.n_holdings > 0 && (
            <>
              <div className="text-right">
                <div className="text-micro uppercase tracking-[0.14em] text-[var(--ink-faint)]">
                  Portfolio
                </div>
                <div className="tabular text-body-lg leading-tight text-[var(--ink-primary)]">
                  {rupeesCompact(summary.data.total_value)}
                </div>
              </div>
              <div className="hidden text-right sm:block">
                <div className="text-micro uppercase tracking-[0.14em] text-[var(--ink-faint)]">
                  Gain
                </div>
                <div className={clsx(
                  "tabular text-body-lg leading-tight",
                  summary.data.unrealized_gain >= 0
                    ? "text-[var(--good-ink)]" : "text-[var(--critical-ink)]",
                )}>
                  {summary.data.unrealized_gain_pct >= 0 ? "+" : ""}
                  {(summary.data.unrealized_gain_pct * 100).toFixed(2)}%
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

/** Page heading used across the dashboard. */
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
