"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { LinkButton } from "@/components/ui";

export function PublicHeader() {
  const { user, loading } = useAuth();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={
        "fixed inset-x-0 top-0 z-50 transition-all duration-300 " +
        (scrolled
          ? "border-b border-[var(--hairline)] bg-[color-mix(in_oklab,var(--surface-0)_85%,transparent)] backdrop-blur-xl"
          : "border-b border-transparent")
      }
    >
      <div className="mx-auto flex w-full max-w-[1180px] items-center gap-6 px-5 py-4">
        <Link href="/" className="display shrink-0 text-h2 leading-none tracking-tight">
          Wealth<span className="metal">OS</span>
        </Link>

        <nav className="ml-4 hidden gap-6 md:flex">
          {[
            ["Capabilities", "#capabilities"],
            ["Method", "#method"],
            ["Results", "#results"],
          ].map(([label, href]) => (
            <a key={href} href={href}
               className="text-body text-[var(--ink-secondary)] transition-colors hover:text-[var(--ink-primary)]">
              {label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2.5">
          {loading ? null : user ? (
            <LinkButton href="/home" size="sm">Go to dashboard</LinkButton>
          ) : (
            <>
              <Link href="/login"
                    className="px-2.5 py-1.5 text-body text-[var(--ink-secondary)] transition-colors hover:text-[var(--ink-primary)]">
                Sign in
              </Link>
              <LinkButton href="/register" size="sm">Get started</LinkButton>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

export function PublicFooter() {
  return (
    <footer className="border-t border-[var(--hairline)] bg-[var(--surface-1)]">
      <div className="mx-auto w-full max-w-[1180px] px-5 py-12">
        <div className="flex flex-wrap items-start justify-between gap-8">
          <div className="max-w-sm">
            <div className="display text-h3 leading-none tracking-tight">
              Wealth<span className="metal">OS</span>
            </div>
            <p className="mt-3 text-small leading-relaxed text-[var(--ink-secondary)]">
              Portfolio analytics, risk, goal forecasting and a grounded AI
              copilot, built on fifteen years of Indian market history.
            </p>
          </div>

          <div className="flex gap-12">
            <div>
              <div className="mb-2.5 text-micro font-semibold uppercase tracking-[0.16em] text-[var(--ink-faint)]">
                Product
              </div>
              {[["Sign in", "/login"], ["Create account", "/register"]].map(([l, h]) => (
                <Link key={h} href={h}
                      className="mb-1.5 block text-small text-[var(--ink-secondary)] hover:text-[var(--accent)]">
                  {l}
                </Link>
              ))}
            </div>
            <div>
              <div className="mb-2.5 text-micro font-semibold uppercase tracking-[0.16em] text-[var(--ink-faint)]">
                Project
              </div>
              <span className="mb-1.5 block text-small text-[var(--ink-secondary)]">
                Polaris School of Technology
              </span>
              <span className="mb-1.5 block text-small text-[var(--ink-secondary)]">
                Advanced Data Science, OJT
              </span>
            </div>
          </div>
        </div>

        <hr className="rule-fade my-8" />

        {/* The disclaimer is prominent, not buried in small print. */}
        <p className="text-caption leading-relaxed text-[var(--ink-muted)]">
          <strong className="text-[var(--ink-secondary)]">
            WealthOS is an academic research prototype, not a regulated financial
            advisory service.
          </strong>{" "}
          It explains computed portfolio metrics and does not provide investment
          advice. Forecasts are projections under stated assumptions, not
          predictions, and may be wrong. Market prices are real: live from
          your own Upstox account when you connect it, otherwise delayed from
          Yahoo Finance. Trading is paper only. The behaviour models were
          trained on a synthetic investor cohort, documented under Research.
        </p>
      </div>
    </footer>
  );
}
