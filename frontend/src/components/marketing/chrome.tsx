"use client";

import clsx from "clsx";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";

const PRODUCT = [
  { href: "/#portfolio", title: "Portfolio intelligence", body: "Health, risk and concentration on real prices" },
  { href: "/#ai", title: "AI that answers with your numbers", body: "Every figure checked against your data" },
  { href: "/#autopilot", title: "Autopilot", body: "A paper sleeve the models run, with reasons" },
  { href: "/#models", title: "Model picks", body: "NIFTY 100 ranked for the next two weeks" },
  { href: "/#markets", title: "Markets and options", body: "Movers, heatmaps, option chains, charts" },
];

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={clsx("display font-normal leading-none", className)}>
      Wealth<span className="metal">OS</span>
    </span>
  );
}

export function SiteNav() {
  const { user, loading } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <header className={clsx("fixed inset-x-0 top-0 z-50 transition-all duration-300",
      scrolled ? "border-b border-[var(--hairline)] bg-[color-mix(in_oklab,var(--surface-0)_88%,transparent)] backdrop-blur-md" : "border-b border-transparent")}>
      <div className="mx-auto flex w-full max-w-[1240px] items-center gap-8 px-5 py-4 sm:px-8">
        <Link href="/" className="shrink-0"><Wordmark className="text-[26px]" /></Link>
        <nav className="hidden items-center gap-7 text-body text-[var(--ink-secondary)] md:flex">
          <div ref={box} className="relative">
            <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex items-center gap-1 hover:text-[var(--ink-primary)]">
              Product <span className={clsx("text-caption transition-transform", open && "rotate-180")}>▾</span>
            </button>
            {open && (
              <div className="fade absolute left-0 top-9 w-[380px] rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-[var(--surface-1)] p-3 shadow-[var(--lift-3)]">
                {PRODUCT.map((p) => (
                  <Link key={p.href} href={p.href} onClick={() => setOpen(false)} className="block rounded-[14px] px-3 py-2.5 hover:bg-[var(--surface-2)]">
                    <div className="text-body font-medium text-[var(--ink-primary)]">{p.title}</div>
                    <div className="text-small text-[var(--ink-muted)]">{p.body}</div>
                  </Link>
                ))}
              </div>
            )}
          </div>
          <Link href="/#method" className="hover:text-[var(--ink-primary)]">How it decides</Link>
          <Link href="/#trust" className="hover:text-[var(--ink-primary)]">Security</Link>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {!loading && (user ? (
            <Link href="/home" className="label rounded-[var(--radius-sm)] bg-[var(--action)] px-4 py-2.5 text-[var(--action-ink)] hover:opacity-90">Open WealthOS →</Link>
          ) : (
            <>
              <Link href="/login" className="hidden text-body text-[var(--ink-secondary)] hover:text-[var(--ink-primary)] sm:block">Log in</Link>
              <Link href="/register" className="label rounded-[var(--radius-sm)] bg-[var(--action)] px-4 py-2.5 text-[var(--action-ink)] hover:opacity-90">Get started →</Link>
            </>
          ))}
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  const cols: [string, [string, string][]][] = [
    ["Product", [["Portfolio intelligence", "/#portfolio"], ["AI chat", "/#ai"], ["Autopilot", "/#autopilot"], ["Model picks", "/#models"], ["Markets", "/#markets"]]],
    ["Research", [["How it decides", "/#method"], ["Swing Lab", "/analysis/swing-lab"], ["Model Lab", "/analysis/model-lab"]]],
    ["Account", [["Get started", "/register"], ["Log in", "/login"], ["Security", "/#trust"]]],
  ];
  return (
    <footer className="border-t border-[var(--hairline)] bg-[var(--surface-1)]">
      <div className="mx-auto grid w-full max-w-[1240px] gap-10 px-5 py-16 sm:px-8 md:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div>
          <Wordmark className="text-[30px]" />
          <p className="mt-4 max-w-xs text-small leading-relaxed text-[var(--ink-muted)]">
            Portfolio intelligence, trained market models and an AI that answers with your own numbers.
          </p>
        </div>
        {cols.map(([title, links]) => (
          <div key={title}>
            <div className="label mb-4 text-[var(--ink-muted)]">{title}</div>
            <ul className="space-y-2.5 text-body">
              {links.map(([label, href]) => <li key={label}><Link href={href} className="text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">{label}</Link></li>)}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-[var(--hairline)]">
        <p className="mx-auto w-full max-w-[1240px] px-5 py-8 text-caption leading-relaxed text-[var(--ink-muted)] sm:px-8">
          WealthOS is an academic research prototype. Model outputs are research signals for paper trading, not
          investment advice, and past results do not promise future returns. Trading is paper only: no order reaches a
          broker or an exchange. Market data from Yahoo Finance (delayed) and, when you connect it, your own Upstox
          account. Personalised investment advice in India requires SEBI registration.
        </p>
      </div>
    </footer>
  );
}
