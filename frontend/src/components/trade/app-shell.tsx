"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { editorial } from "@/lib/editorial";
import { useDismiss, usePoll } from "@/lib/hooks";
import { account, paper as paperClient, trade, type ChatThread, type Instrument, type Quote } from "@/lib/trade-api";
import { num, pct, tone } from "@/lib/tfmt";
import { OrderTicketProvider } from "./order-ticket";
import { SettingsProvider, useSettings } from "./settings-context";
import { Icon, Modal } from "./primitives";

/* ─────────────────────────── chat threads context ─────────────────────────── */

interface ChatState {
  threads: ChatThread[];
  refresh: () => Promise<void>;
  activeId: number | null;
  setActiveId: (id: number | null) => void;
}

const ChatContext = createContext<ChatState | null>(null);

export function useChatThreads() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatThreads must be used inside AppShell");
  return ctx;
}

function ChatProvider({ children }: { children: ReactNode }) {
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const refresh = useCallback(async () => {
    try { setThreads((await trade.threads()).threads ?? []); } catch { /* sidebar stays as it was */ }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const value = useMemo(() => ({ threads, refresh, activeId, setActiveId }), [threads, refresh, activeId]);
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

/* ─────────────────────────── navigation model ─────────────────────────── */

type MenuItem = { label: string; href: string };
type MenuSection = { title: string; items: MenuItem[] };

const MARKETS_MENU: MenuSection[] = [
  { title: "Prices and lists", items: [
    { label: "Top gainers and losers", href: "/market" },
    { label: "Indices", href: "/market/indices" },
    { label: "Industries", href: "/market/heatmap" },
    { label: "Stocks in the news", href: "/market/news" },
  ] },
  { title: "Open interest", items: [
    { label: "OI analysis", href: "/market/oi" },
    { label: "Multi-strike OI", href: "/market/oi?view=multi" },
    { label: "OI crossovers", href: "/market/oi?view=crossovers" },
  ] },
  { title: "Options and futures", items: [
    { label: "F&O heatmap", href: "/market/heatmap" },
    { label: "Strategy chart", href: "/tools/strategy-chart" },
    { label: "Unusual option activity", href: "/market/unusual" },
    { label: "Option chain", href: "/market/option-chain" },
    { label: "Index F&O", href: "/market?segment=options" },
    { label: "Stock F&O", href: "/market?segment=futures" },
  ] },
  { title: "More markets", items: [
    { label: "Commodities", href: "/market/commodities" },
    { label: "Stock events", href: "/market/events" },
    { label: "Calendar", href: "/market/calendar" },
  ] },
  { title: "Tools", items: [
    { label: "Strategy wizard", href: "/tools/strategy-wizard" },
    { label: "Build your own", href: "/market/screener?build=1" },
    { label: "Strategy builder", href: "/tools/strategy-chart" },
    { label: "Pair builder", href: "/tools/pairs" },
    { label: "Pair screener", href: "/tools/pairs?view=screener" },
  ] },
];

const SCREENERS_MENU: MenuSection[] = [
  { title: "Screens", items: [
    { label: "Technicals", href: "/market/screener?group=technicals" },
    { label: "Fundamentals", href: "/market/screener?group=fundamentals" },
    { label: "Candlestick", href: "/market/screener?group=candlestick" },
    { label: "My screens", href: "/market/screener?group=mine" },
  ] },
  { title: "Build", items: [
    { label: "Build new screen", href: "/market/screener?build=1" },
  ] },
];

const IDEAS_MENU: MenuSection[] = [
  { title: "Models", items: [
    { label: "Model picks", href: "/market/model-picks" },
    { label: "Swing plan", href: "/market/model-picks#swing-plan" },
    { label: "Invest an amount", href: "/market/model-picks#invest-amount" },
    { label: "Autopilot", href: "/autopilot" },
    { label: "How they were tested →", href: "/analysis/swing-lab" },
  ] },
  { title: "Recommendations", items: [
    { label: "Intraday", href: "/market/recommendations?kind=intraday" },
    { label: "Delivery", href: "/market/recommendations?kind=delivery" },
    { label: "F&O", href: "/market/recommendations?kind=fno" },
    { label: "All recommendations →", href: "/market/recommendations" },
  ] },
  { title: "Strategies", items: [
    { label: "Intraday", href: "/strategy-templates?style=intraday" },
    { label: "Swing", href: "/strategy-templates?style=swing" },
    { label: "Positional", href: "/strategy-templates?style=positional" },
    { label: "The whole library →", href: "/strategy-templates" },
  ] },
];

/* ─────────────────────────── shell ─────────────────────────── */

export function AppShell({ children, bare = false }: { children: ReactNode; bare?: boolean }) {
  const { user, loading } = useAuth();

  useEffect(() => {
    if (!loading && !user && typeof window !== "undefined") window.location.href = "/login";
  }, [loading, user]);

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-body text-[var(--ink-secondary)]">
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--surface-3)] border-t-[var(--ink-primary)]" />
        <span className="ml-3">Loading…</span>
      </div>
    );
  }

  return (
    <SettingsProvider>
      <ChatProvider>
        <OrderTicketProvider>
          {bare ? children : <Frame>{children}</Frame>}
        </OrderTicketProvider>
      </ChatProvider>
    </SettingsProvider>
  );
}

function Frame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [sidebar, setSidebar] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("wealthos.sidebar");
    if (saved === "closed") setSidebar(false);
  }, []);
  const toggle = () => {
    setSidebar((v) => {
      window.localStorage.setItem("wealthos.sidebar", v ? "closed" : "open");
      return !v;
    });
  };
  useEffect(() => { setMobileOpen(false); }, [pathname]);

  return (
    <div className={clsx("min-h-screen lg:grid", sidebar ? "lg:grid-cols-[300px_1fr]" : "lg:grid-cols-[64px_1fr]")}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-full focus:bg-[var(--surface-2)] focus:px-4 focus:py-2">
        Skip to content
      </a>
      <ChatSidebar collapsed={!sidebar} onToggle={toggle} mobileOpen={mobileOpen} onMobileClose={() => setMobileOpen(false)} />
      <div className="min-w-0">
        <div className="sticky top-0 z-30 bg-[var(--surface-0)]">
          <TickerStrip />
          <TopNav onMenu={() => setMobileOpen(true)} />
        </div>
        <main id="main" key={pathname} className="page-enter mx-auto w-full max-w-[1500px] px-4 py-6 sm:px-8 lg:px-12">
          {children}
        </main>
      </div>
    </div>
  );
}

/* ─────────────────────────── sidebar ─────────────────────────── */

function monthKey(iso: string | null) {
  if (!iso) return "EARLIER";
  const d = new Date(iso);
  const now = new Date();
  const name = d.toLocaleDateString("en-GB", { month: "long" }).toUpperCase();
  return d.getFullYear() === now.getFullYear() ? name : `${name} ${d.getFullYear()}`;
}

function ChatSidebar({ collapsed, onToggle, mobileOpen, onMobileClose }: {
  collapsed: boolean; onToggle: () => void; mobileOpen: boolean; onMobileClose: () => void;
}) {
  const { threads, activeId, refresh } = useChatThreads();
  const router = useRouter();
  const [filter, setFilter] = useState("");
  const [searching, setSearching] = useState(false);

  const groups = useMemo(() => {
    const out: { month: string; items: ChatThread[] }[] = [];
    for (const t of threads.filter((t) => t.title.toLowerCase().includes(filter.toLowerCase()))) {
      const key = monthKey(t.updated_at);
      const g = out.find((x) => x.month === key);
      if (g) g.items.push(t); else out.push({ month: key, items: [t] });
    }
    return out;
  }, [threads, filter]);

  async function remove(id: number) {
    await trade.deleteThread(id).catch(() => {});
    await refresh();
    if (activeId === id) router.push("/home");
  }

  const body = (
    <div className="flex h-full flex-col">
      <div className={clsx("flex items-center px-4 pb-3 pt-4", collapsed ? "flex-col gap-3" : "justify-between")}>
        <Link href="/home" aria-label="WealthOS home" className="flex items-center gap-2">
          <Logo />
          {!collapsed && <span className="display text-h3 font-normal">Wealth<span className="metal">OS</span></span>}
        </Link>
        <div className={clsx("flex items-center gap-1 text-[var(--ink-secondary)]", collapsed && "flex-col")}>
          <button aria-label="Search chats" onClick={() => { if (collapsed) onToggle(); setSearching((v) => !v); }}
            className="rounded-full p-2 hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]">
            <Icon name="search" size={18} />
          </button>
          <button aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={onToggle}
            className="hidden rounded-full p-2 hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)] lg:block">
            <Icon name="sidebar" size={18} />
          </button>
          <button aria-label="Close" onClick={onMobileClose} className="rounded-full p-2 lg:hidden"><Icon name="x" size={18} /></button>
        </div>
      </div>

      <div className="px-4">
        <Link href="/home?new=1"
          className={clsx("flex items-center gap-3 rounded-full border border-[var(--hairline-strong)] text-body-lg transition-colors hover:bg-[var(--surface-3)]",
            collapsed ? "justify-center p-2.5" : "px-5 py-3")}>
          <Icon name="plus" size={18} />
          {!collapsed && "New Chat"}
        </Link>
      </div>

      {!collapsed && (
        <>
          {searching && (
            <div className="px-4 pt-3">
              <input autoFocus value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search chats"
                className="w-full rounded-full border border-[var(--hairline-strong)] bg-[var(--surface-1)] px-4 py-2 text-small focus:outline-none" />
            </div>
          )}
          <div className="flex items-center justify-between px-6 pb-1 pt-5 text-small">
            <span className="font-medium text-[var(--ink-secondary)]">All chats</span>
            <span className="text-caption text-[var(--ink-muted)]">{threads.length || ""}</span>
          </div>
          <nav className="no-scrollbar flex-1 overflow-y-auto px-3 pb-6">
            {threads.length === 0 && (
              <p className="px-3 py-4 text-small leading-relaxed text-[var(--ink-muted)]">
                Your conversations with the AI appear here. Ask about a stock, an option chain or your paper portfolio.
              </p>
            )}
            {groups.map((g) => (
              <div key={g.month} className="mt-4">
                <div className="px-3 pb-1.5 text-micro font-semibold tracking-[0.14em] text-[var(--ink-faint)]">{g.month}</div>
                {g.items.map((t) => (
                  <div key={t.id} className={clsx("group flex items-center rounded-[var(--radius-sm)]",
                    t.id === activeId ? "bg-[var(--surface-3)]" : "hover:bg-[var(--surface-2)]")}>
                    <Link href={`/home?thread=${t.id}`} className="min-w-0 flex-1 truncate px-3 py-2.5 text-body-lg text-[var(--ink-secondary)] group-hover:text-[var(--ink-primary)]">
                      {t.title}
                    </Link>
                    <button aria-label={`Delete ${t.title}`} onClick={() => remove(t.id)}
                      className="mr-1 hidden rounded p-1 text-[var(--ink-faint)] hover:text-[var(--down)] group-hover:block">
                      <Icon name="trash" size={14} />
                    </button>
                  </div>
                ))}
              </div>
            ))}
          </nav>
        </>
      )}
    </div>
  );

  return (
    <>
      <aside className={clsx("sticky top-0 hidden h-screen border-r border-[var(--hairline)] bg-[var(--surface-0)] lg:block")}>
        {body}
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/70" onClick={onMobileClose} />
          <aside className="absolute inset-y-0 left-0 w-[300px] border-r border-[var(--hairline)] bg-[var(--surface-0)]">{body}</aside>
        </div>
      )}
    </>
  );
}

export function Logo({ size = 26 }: { size?: number }) {
  // An original mark: a rising bar inside a rounded square.
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
      <rect x="1" y="1" width="26" height="26" rx="8" fill="var(--accent)" />
      <path d="M8 19v-3M12.5 19v-6M17 19v-9M21 19V7" stroke="var(--accent-ink)" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

/* ─────────────────────────── ticker ─────────────────────────── */

function TickerStrip() {
  const { data } = usePoll(() => trade.indices(), 15_000);
  const indices = Array.isArray(data?.indices) ? data.indices : [];
  const label = (q: Quote) => (q.symbol === "INDIAVIX" ? "INDIA VIX" : q.symbol);
  const items = indices.length ? [...indices, ...indices] : [];

  return (
    <div className="flex h-11 items-center border-b border-[var(--hairline)] text-body">
      <div className="flex shrink-0 items-center gap-2 pl-4 pr-3 text-[var(--ink-secondary)] sm:pl-8">
        <span className={clsx("h-2 w-2 rounded-full", data?.market?.is_open ? "bg-[var(--up)]" : "bg-[var(--ink-faint)]")} />
        <span className="hidden sm:inline">{data?.market?.label ?? "Market"}</span>
      </div>
      <div className="relative min-w-0 flex-1 overflow-hidden [mask-image:linear-gradient(90deg,transparent,#000_3%,#000_97%,transparent)]">
        <div className="ticker-track flex w-max items-center gap-9 whitespace-nowrap">
          {items.map((q, i) => (
            <Link key={`${q.symbol}-${i}`} href={`/chart?symbol=${q.symbol}`} className="flex items-center gap-2 hover:opacity-80">
              <span className="font-semibold text-[var(--ink-primary)]">{label(q)}</span>
              <span className="tabular text-[var(--ink-primary)]">{num(q.ltp)}</span>
              <span className={clsx("tabular", tone(q.change))}>
                {q.change >= 0 ? "+" : ""}{num(q.change)} ({pct(q.change_pct)})
              </span>
            </Link>
          ))}
        </div>
      </div>
      <div className="shrink-0 px-4 text-[var(--ink-muted)]" title="NSE · BSE · prices delayed about 15 minutes">
        <Icon name="globe" size={18} />
      </div>
    </div>
  );
}

/* ─────────────────────────── top navigation ─────────────────────────── */

function TopNav({ onMenu }: { onMenu: () => void }) {
  const pathname = usePathname();
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const close = useCallback(() => setOpenMenu(null), []);
  const ref = useDismiss(openMenu !== null, close);
  useEffect(() => { setOpenMenu(null); }, [pathname]);

  const isMarkets = pathname.startsWith("/market") && !pathname.startsWith("/market/screener") && !pathname.startsWith("/market/recommendations") && !pathname.startsWith("/market/model-picks");
  const nav: { key: string; label: string; href?: string; menu?: MenuSection[]; active: boolean; cols?: number }[] = [
    { key: "markets", label: "Markets", menu: MARKETS_MENU, active: isMarkets, cols: 3 },
    { key: "screeners", label: "Screeners", menu: SCREENERS_MENU, active: pathname.startsWith("/market/screener"), cols: 2 },
    { key: "ideas", label: "Ideas", menu: IDEAS_MENU, active: pathname.startsWith("/market/recommendations") || pathname.startsWith("/market/model-picks") || pathname.startsWith("/strategy-templates"), cols: 3 },
    { key: "charts", label: "Charts", href: "/chart", active: pathname.startsWith("/chart") },
    { key: "portfolio", label: "Portfolio", href: "/portfolio", active: pathname.startsWith("/portfolio") || pathname.startsWith("/analysis") },
  ];

  return (
    <header ref={ref} className="relative border-b border-[var(--hairline)]">
      <div className="flex h-16 items-center gap-1 px-3 sm:px-8 lg:px-12">
        <button aria-label="Open chats" onClick={onMenu} className="mr-1 rounded-full p-2 text-[var(--ink-secondary)] lg:hidden">
          <Icon name="menu" size={20} />
        </button>
        <nav className="no-scrollbar flex min-w-0 items-center gap-1 overflow-x-auto">
          {nav.map((item) => item.href ? (
            <Link key={item.key} href={item.href}
              className={clsx("whitespace-nowrap rounded-full px-3 py-2 text-body-lg transition-colors",
                item.active ? "font-medium text-[var(--accent)]" : "text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]")}>
              {item.label}
            </Link>
          ) : (
            <button key={item.key} onClick={() => setOpenMenu(openMenu === item.key ? null : item.key)}
              aria-expanded={openMenu === item.key}
              className={clsx("flex items-center gap-1 whitespace-nowrap rounded-full px-3 py-2 text-body-lg transition-colors",
                item.active || openMenu === item.key ? "font-medium text-[var(--accent)]" : "text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]")}>
              {item.label}
              <Icon name="chevron" size={14} className={clsx("transition-transform", openMenu === item.key && "rotate-180")} />
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2 pl-2">
          <ModeSwitch />
          <SearchButton />
          <AlertsBell />
          <Link href="/home?new=1" aria-label="New chat"
            className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--action)] text-[var(--action-ink)] transition-opacity hover:opacity-90">
            <Icon name="plus" size={22} strokeWidth={2.2} />
          </Link>
          <AccountMenu />
        </div>
      </div>

      {nav.map((item) => item.menu && openMenu === item.key && (
        <MegaMenu key={item.key} sections={item.menu} cols={item.cols ?? 3} onPick={close} />
      ))}
    </header>
  );
}

function MegaMenu({ sections, cols, onPick }: { sections: MenuSection[]; cols: number; onPick: () => void }) {
  return (
    <div className="fade absolute left-3 top-[calc(100%+6px)] z-40 rounded-[var(--radius-lg)] border border-[var(--hairline-strong)] bg-[var(--surface-1)] p-6 shadow-[var(--lift-3)] sm:left-8 lg:left-12">
      <div className="grid gap-x-12 gap-y-8" style={{ gridTemplateColumns: `repeat(${cols}, minmax(180px, auto))` }}>
        {sections.map((s) => (
          <div key={s.title}>
            <div className="label mb-3 text-[var(--ink-muted)]">{s.title}</div>
            <ul className="space-y-1">
              {s.items.map((it) => (
                <li key={it.label}>
                  <Link href={it.href} onClick={onPick}
                    className="-mx-2 block rounded-[var(--radius-sm)] px-2 py-1.5 text-body-lg text-[var(--ink-primary)] hover:bg-[var(--surface-3)]">
                    {it.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function ModeSwitch() {
  return (
    <div className="hidden items-center rounded-full border border-[var(--hairline-strong)] p-1 md:flex">
      <span className="rounded-full bg-[var(--action)] px-4 py-1.5 text-body font-medium text-[var(--action-ink)]">Mock</span>
      <span title="Live trading needs a SEBI-registered broker connection. This build trades on paper only."
        className="cursor-not-allowed px-4 py-1.5 text-body text-[var(--ink-faint)]">Live</span>
    </div>
  );
}

function SearchButton() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [results, setResults] = useState<Instrument[]>([]);
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(true); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { if (open) window.setTimeout(() => inputRef.current?.focus(), 10); }, [open]);
  useEffect(() => {
    if (!text.trim()) { setResults([]); return; }
    const id = window.setTimeout(() => {
      trade.search(text).then((r) => setResults(r.results)).catch(() => setResults([]));
    }, 150);
    return () => window.clearTimeout(id);
  }, [text]);

  const go = (symbol: string) => { setOpen(false); setText(""); router.push(`/chart?symbol=${symbol}`); };

  return (
    <>
      <button aria-label="Search stocks (⌘K)" onClick={() => setOpen(true)}
        className="rounded-full p-2.5 text-[var(--ink-primary)] hover:bg-[var(--surface-3)]">
        <Icon name="search" size={21} />
      </button>
      {open && (
        <div className="fixed inset-0 z-[70] flex items-start justify-center bg-black/60 p-4 pt-[12vh]" onMouseDown={() => setOpen(false)}>
          <div onMouseDown={(e) => e.stopPropagation()} className="fade w-full max-w-xl overflow-hidden rounded-[var(--radius-lg)] border border-[var(--hairline-strong)] bg-[var(--surface-1)] shadow-[var(--lift-3)]">
            <div className="flex items-center gap-3 border-b border-[var(--hairline)] px-4">
              <Icon name="search" size={18} className="text-[var(--ink-muted)]" />
              <input ref={inputRef} value={text} onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); if (e.key === "Enter" && results[0]) go(results[0].symbol); }}
                placeholder="Search NIFTY 100 stocks and indices" className="h-14 flex-1 bg-transparent text-body-lg focus:outline-none" />
              <kbd className="rounded border border-[var(--hairline-strong)] px-1.5 text-micro text-[var(--ink-muted)]">esc</kbd>
            </div>
            <ul className="max-h-[50vh] overflow-y-auto py-2">
              {results.map((r) => (
                <li key={r.symbol}>
                  <button onClick={() => go(r.symbol)} className="flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-[var(--surface-3)]">
                    <span><span className="font-semibold">{r.symbol}</span> <span className="text-small text-[var(--ink-muted)]">{r.name}</span></span>
                    <span className="text-caption text-[var(--ink-faint)]">{r.kind === "index" ? "Index" : r.sector}</span>
                  </button>
                </li>
              ))}
              {text && results.length === 0 && <li className="px-4 py-3 text-small text-[var(--ink-muted)]">No match in the NIFTY 100 universe.</li>}
              {!text && <li className="px-4 py-3 text-small text-[var(--ink-muted)]">Type a symbol or a company name. Opens the chart.</li>}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}

function AlertsBell() {
  const { settings } = useSettings();
  const { data } = usePoll(() => api.alerts().catch(() => ({ alerts: [], unread: 0 })), 120_000);
  const unread = settings && !settings.notifications.portfolio_alerts ? 0 : (data?.unread ?? 0);
  return (
    <Link href="/analysis/insights" aria-label={`Alerts${unread ? `, ${unread} unread` : ""}`}
      className="relative rounded-full p-2.5 text-[var(--ink-primary)] hover:bg-[var(--surface-3)]">
      <Icon name="bell" size={21} />
      {unread > 0 && (
        <span className="absolute right-0.5 top-0.5 min-w-[20px] rounded-full bg-[var(--ink-primary)] px-1 text-center text-micro font-bold leading-[18px] text-[var(--surface-0)]">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );
}

/** Theme: the dark terminal by default, a light theme on request; remembered. */
export function useTheme() {
  // The boot script in app/layout.tsx has already applied the saved theme;
  // read it back rather than overwrite it. Light is the default.
  const [theme, setTheme] = useState<"terminal" | "light">("light");
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "terminal" ? "terminal" : "light");
  }, []);
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "terminal" ? "light" : "terminal";
      document.documentElement.dataset.theme = next;
      window.localStorage.setItem("wealthos.theme", next);
      return next;
    });
  }, []);
  return { theme, toggle };
}

const SHORTCUTS: [string, string][] = [
  ["⌘ K", "Search stocks and indices"],
  ["⌘ /", "Show keyboard shortcuts"],
  ["Enter", "Send a message to the AI"],
  ["Shift + Enter", "New line in a message"],
  ["Esc", "Close a menu or dialog"],
];

function ShortcutsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="Keyboard shortcuts" width={420}>
      <ul className="divide-y divide-[var(--hairline)]">
        {SHORTCUTS.map(([keys, label]) => (
          <li key={keys} className="flex items-center justify-between py-2.5 text-body">
            <span className="text-[var(--ink-secondary)]">{label}</span>
            <kbd className="rounded-[6px] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-2 py-0.5 text-small">{keys}</kbd>
          </li>
        ))}
      </ul>
    </Modal>
  );
}

function AccountMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);
  const { theme, toggle } = useTheme();
  const wallet = usePoll(() => Promise.all([paperClient.portfolio(), account.brokers()]), open ? 60_000 : null, [open]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "/") { e.preventDefault(); setShortcuts(true); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  if (!user) return null;
  const name = user.full_name || user.email.split("@")[0];
  const initials = name.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  const brokers = wallet.data?.[1]?.brokers;
  const upstox = Array.isArray(brokers) ? brokers.find((b) => b.broker === "upstox") : undefined;
  const available = wallet.data?.[0]?.available;
  const brokerLine = !upstox || !upstox.credentials_saved ? "No broker connected"
    : upstox.state === "connected" ? "Upstox connected" : upstox.state === "expired" ? "Upstox: log in again" : "Upstox: not logged in";

  const row = "flex w-full items-center gap-3 rounded-[var(--radius-sm)] px-3 py-2.5 text-body-lg text-[var(--ink-primary)] hover:bg-[var(--surface-3)]";
  const items: { href: string; label: string; icon: string }[] = [
    { href: "/autopilot", label: "Autopilot", icon: "bolt" },
    { href: "/settings/brokers", label: "Broker APIs", icon: "link" },
    { href: "/settings/trading", label: "Trading Preferences", icon: "sliders" },
    { href: "/settings/memory", label: "Memory", icon: "brain" },
    { href: "/settings/account", label: "Account", icon: "user" },
    { href: "/settings/notifications", label: "Notifications", icon: "bell" },
  ];
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-label="Account menu" aria-expanded={open}
        className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--surface-4)] text-body font-semibold">
        {initials}
      </button>
      {open && (
        <div className="fade absolute right-0 top-[calc(100%+8px)] z-50 w-[300px] rounded-[var(--radius-lg)] border border-[var(--hairline-strong)] bg-[var(--surface-1)] p-2 shadow-[var(--lift-3)]">
          <div className="truncate px-3 pb-2 pt-2 text-body text-[var(--ink-secondary)]">{user.email}</div>
          <Link href="/portfolio" onClick={close} className={clsx(row, "items-start")}>
            <Icon name="wallet" size={19} className="mt-0.5 text-[var(--ink-secondary)]" />
            <span>
              <span className="block">Wallet</span>
              <span className="block text-small text-[var(--ink-muted)]">
                {typeof available === "number" ? `Paper ₹${Math.round(available).toLocaleString("en-IN")} · ${brokerLine}` : brokerLine}
              </span>
            </span>
          </Link>
          <div className="my-1.5 h-px bg-[var(--hairline)]" />
          {items.map((it) => (
            <Link key={it.href} href={it.href} onClick={close} className={row}>
              <Icon name={it.icon} size={19} className="text-[var(--ink-secondary)]" /> {it.label}
            </Link>
          ))}
          <div className="my-1.5 h-px bg-[var(--hairline)]" />
          <Link href="/prompt-book" onClick={close} className={row}>
            <Icon name="play" size={19} className="text-[var(--ink-secondary)]" /> Tutorials
          </Link>
          <button onClick={() => { close(); setShortcuts(true); }} className={clsx(row, "justify-between")}>
            <span className="flex items-center gap-3"><Icon name="keyboard" size={19} className="text-[var(--ink-secondary)]" /> Keyboard shortcuts</span>
            <span className="text-small text-[var(--ink-muted)]">⌘/</span>
          </button>
          <div className="my-1.5 h-px bg-[var(--hairline)]" />
          <div className="flex items-center justify-between">
            <button onClick={signOut} className={clsx(row, "flex-1")}>
              <Icon name="logout" size={19} className="text-[var(--ink-secondary)]" /> Log out
            </button>
            <button onClick={toggle} aria-label={theme === "terminal" ? "Switch to light theme" : "Switch to dark theme"}
              title="Toggle theme" className="mr-1 rounded-full p-2.5 text-[var(--ink-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]">
              <Icon name={theme === "terminal" ? "moon" : "sun"} size={19} />
            </button>
          </div>
        </div>
      )}
      <ShortcutsModal open={shortcuts} onClose={() => setShortcuts(false)} />
    </div>
  );
}

/** Heading used on the trading pages. */
export function TradeHead({ title, lede, aside, eyebrow }: { title: ReactNode; lede?: ReactNode; aside?: ReactNode; eyebrow?: string }) {
  return (
    <div className="rise mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="label mb-3 text-[var(--accent)]">{eyebrow}</div>}
        <h1 className="display text-display">{editorial(title)}</h1>
        {lede && <p className="mt-3 max-w-3xl text-body-lg leading-relaxed text-[var(--ink-secondary)]">{lede}</p>}
      </div>
      {aside}
    </div>
  );
}
