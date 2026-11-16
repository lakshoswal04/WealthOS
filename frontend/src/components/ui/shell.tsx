"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/overview", label: "Overview", hint: "Wealth at a glance" },
  { href: "/portfolio", label: "Portfolio", hint: "Holdings and allocation" },
  { href: "/risk", label: "Risk", hint: "Volatility, drawdown, correlation" },
  { href: "/goals", label: "Goals", hint: "Targets and projections" },
  { href: "/insights", label: "Insights", hint: "Profile, anomalies, forecast" },
  { href: "/copilot", label: "Copilot", hint: "Ask about your portfolio" },
  { href: "/import", label: "Import", hint: "Upload holdings" },
  { href: "/profile", label: "Profile", hint: "Your investor details" },
];

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
      <div className="flex min-h-screen items-center justify-center text-[13px] text-[var(--ink-secondary)]">
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--surface-3)] border-t-[var(--accent)]" />
        <span className="ml-3">Loading your portfolio…</span>
      </div>
    );
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      {/* ── sidebar ── */}
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-40 w-[232px] border-r border-[var(--hairline)]",
          "bg-[var(--surface-1)] transition-transform lg:static lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-full flex-col">
          <div className="border-b border-[var(--hairline)] px-5 py-5">
            <Link href="/overview" className="block">
              <div className="display text-[20px] leading-none tracking-tight text-[var(--ink-primary)]">
                Wealth<span className="text-[var(--accent)]">OS</span>
              </div>
              <div className="mt-1.5 text-[10.5px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                Wealth intelligence
              </div>
            </Link>
          </div>

          <nav className="flex-1 overflow-y-auto px-3 py-4">
            {NAV.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className={clsx(
                    "group mb-0.5 block rounded-[8px] px-3 py-2 transition-colors",
                    active
                      ? "bg-[var(--surface-3)] text-[var(--ink-primary)]"
                      : "text-[var(--ink-secondary)] hover:bg-[var(--surface-2)] hover:text-[var(--ink-primary)]",
                  )}
                >
                  <span className="flex items-center gap-2 text-[13.5px] font-medium">
                    <span
                      className={clsx(
                        "h-3.5 w-[2px] rounded-full transition-colors",
                        active ? "bg-[var(--accent)]" : "bg-transparent group-hover:bg-[var(--surface-3)]",
                      )}
                    />
                    {item.label}
                  </span>
                  <span className="ml-[14px] block text-[11px] text-[var(--ink-muted)]">
                    {item.hint}
                  </span>
                </Link>
              );
            })}
          </nav>

          <div className="border-t border-[var(--hairline)] px-4 py-4">
            <div className="truncate text-[12.5px] text-[var(--ink-primary)]">
              {user.full_name || user.email}
            </div>
            <div className="truncate text-[11px] text-[var(--ink-muted)]">{user.email}</div>
            <button
              onClick={signOut}
              className="mt-2.5 text-[11.5px] text-[var(--ink-secondary)] underline-offset-2 hover:text-[var(--accent)] hover:underline"
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {open && (
        <div className="fixed inset-0 z-30 bg-black/60 lg:hidden" onClick={() => setOpen(false)} />
      )}

      {/* ── content ── */}
      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-[var(--hairline)] bg-[color-mix(in_oklab,var(--surface-0)_88%,transparent)] px-4 py-3 backdrop-blur lg:hidden">
          <button
            onClick={() => setOpen((v) => !v)}
            className="rounded-[7px] border border-[var(--hairline)] px-2.5 py-1.5 text-[12px] text-[var(--ink-secondary)]"
            aria-label="Toggle navigation"
          >
            Menu
          </button>
          <span className="display text-[16px]">
            Wealth<span className="text-[var(--accent)]">OS</span>
          </span>
        </header>

        <main className="mx-auto w-full max-w-[1180px] px-4 py-6 sm:px-6 lg:py-9">
          {children}
        </main>

        <footer className="mx-auto w-full max-w-[1180px] px-4 pb-10 sm:px-6">
          <p className="border-t border-[var(--hairline)] pt-4 text-[11.5px] leading-relaxed text-[var(--ink-muted)]">
            WealthOS is an academic research prototype built for the Polaris OJT
            programme. It explains computed portfolio metrics and does not provide
            investment advice. Investor-level data in demonstrations is synthetic;
            market prices are real and corporate-action adjusted.
          </p>
        </footer>
      </div>
    </div>
  );
}

/** Page heading used across the dashboard. */
export function PageHead({ title, lede, aside }: {
  title: string; lede?: string; aside?: React.ReactNode;
}) {
  return (
    <div className="rise mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="display text-[30px] leading-none tracking-tight text-[var(--ink-primary)]">
          {title}
        </h1>
        {lede && (
          <p className="mt-2 max-w-2xl text-[13.5px] leading-relaxed text-[var(--ink-secondary)]">
            {lede}
          </p>
        )}
      </div>
      {aside}
    </div>
  );
}
