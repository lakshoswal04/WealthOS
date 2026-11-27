"use client";

/**
 * Product previews for the landing page: small, faithful renderings of real
 * WealthOS screens (portfolio, health score, risk, the AI chat, Autopilot,
 * model picks, the option chain). They use the app's own tokens, so they
 * follow the theme. The figures are illustrative and each preview says so.
 */

import clsx from "clsx";
import type { ReactNode } from "react";

/* A deterministic, gently rising wealth path (no randomness, no live data). */
function path(n = 64, w = 560, h = 180, seed = 3) {
  const pts: [number, number][] = [];
  let v = 0.32;
  for (let i = 0; i < n; i++) {
    v += 0.009 + Math.sin(i * 0.55 + seed) * 0.018 + Math.sin(i * 0.17) * 0.011;
    pts.push([(i / (n - 1)) * w, h - Math.max(0.05, Math.min(0.95, v)) * h]);
  }
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  return { line, area: `${line} L${w},${h} L0,${h} Z`, last: pts[pts.length - 1] };
}

export function Illustrative({ className }: { className?: string }) {
  return <span className={clsx("label text-[var(--ink-faint)]", className)}>Illustrative preview</span>;
}

export function Frame({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx("rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-[var(--surface-1)] shadow-[var(--lift-3)]", className)}>
      {children}
    </div>
  );
}

export function FloatCard({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx("rounded-[18px] border border-[var(--hairline)] bg-[var(--surface-1)] p-4 shadow-[var(--lift-3)]", className)}>
      {children}
    </div>
  );
}

/* ─────────────────────────── portfolio ─────────────────────────── */

export function PortfolioPreview() {
  const p = path();
  return (
    <Frame className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 px-6 pt-6">
        <div>
          <div className="label text-[var(--ink-muted)]">Total wealth</div>
          <div className="serif tabular mt-1 text-[clamp(32px,6vw,44px)] leading-none">₹24,86,310</div>
          <div className="mt-2 text-small text-[var(--up)]">▲ ₹3,12,480 (14.4%) this year</div>
        </div>
        <div className="flex gap-1 rounded-full bg-[var(--surface-2)] p-1 text-caption">
          {["1M", "6M", "1Y", "All"].map((t) => (
            <span key={t} className={clsx("rounded-full px-2.5 py-0.5", t === "1Y" ? "bg-[var(--action)] text-[var(--action-ink)]" : "text-[var(--ink-muted)]")}>{t}</span>
          ))}
        </div>
      </div>
      <svg viewBox="0 0 560 180" className="mt-4 block h-[180px] w-full" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="wealth-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.16" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[45, 90, 135].map((y) => <line key={y} x1="0" x2="560" y1={y} y2={y} stroke="var(--grid)" strokeWidth="1" />)}
        <path d={p.area} fill="url(#wealth-fill)" />
        <path d={p.line} fill="none" stroke="var(--accent)" strokeWidth="2.2" className="draw" style={{ ["--len" as string]: 1400 }} />
        <circle cx={p.last[0] - 2} cy={p.last[1]} r="4.5" fill="var(--accent)" stroke="var(--surface-1)" strokeWidth="2" />
      </svg>
      <div className="grid grid-cols-2 border-t border-[var(--hairline)] text-small sm:grid-cols-4">
        {[["Equity", "62%"], ["Gold", "12%"], ["Bonds", "18%"], ["Cash", "8%"]].map(([k, v]) => (
          <div key={k} className="border-r border-[var(--hairline)] px-5 py-3 last:border-0">
            <div className="text-[var(--ink-muted)]">{k}</div>
            <div className="tabular font-medium">{v}</div>
          </div>
        ))}
      </div>
    </Frame>
  );
}

export function HealthRing({ score = 78, size = 92 }: { score?: number; size?: number }) {
  const r = size / 2 - 7;
  const c = 2 * Math.PI * r;
  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth="7" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth="7" strokeLinecap="round"
          strokeDasharray={`${(score / 100) * c} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
        <text x="50%" y="54%" textAnchor="middle" dominantBaseline="middle" className="serif" fontSize={size * 0.32} fill="var(--ink-primary)">{score}</text>
      </svg>
      <div>
        <div className="label text-[var(--ink-muted)]">Health score</div>
        <div className="mt-1 text-body font-medium">Good, room to diversify</div>
        <div className="text-caption text-[var(--ink-muted)]">Concentration is the weakest of 6 parts</div>
      </div>
    </div>
  );
}

export function RiskBar() {
  return (
    <div className="w-[260px]">
      <div className="flex items-baseline justify-between">
        <span className="label text-[var(--ink-muted)]">Risk</span>
        <span className="text-caption text-[var(--ink-muted)]">target 18%</span>
      </div>
      <div className="serif tabular mt-1 text-[28px] leading-none">14.2% <span className="text-body text-[var(--ink-muted)]">volatility</span></div>
      <div className="relative mt-3 h-2 rounded-full bg-[var(--surface-3)]">
        <div className="h-2 rounded-full bg-[var(--sage)]" style={{ width: "57%" }} />
        <span className="absolute -top-1 h-4 w-[2px] rounded bg-[var(--ink-primary)]" style={{ left: "72%" }} />
      </div>
      <div className="mt-2 text-caption text-[var(--ink-muted)]">Within a moderate profile</div>
    </div>
  );
}

export function InsightCard() {
  return (
    <div className="w-[290px]">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--accent)] text-[11px] text-[var(--accent-ink)]">AI</span>
        <span className="label text-[var(--ink-muted)]">Insight</span>
      </div>
      <p className="mt-2 text-small leading-relaxed text-[var(--ink-primary)]">
        TCS is <b>31%</b> of your portfolio, above the 18% a moderate profile holds in one stock. Two of your
        holdings rank in the models&apos; bottom fifth for the next two weeks.
      </p>
      <div className="mt-2 text-caption text-[var(--accent)]">✓ every figure checked against your data</div>
    </div>
  );
}

/* ─────────────────────────── showcases ─────────────────────────── */

export function ConcentrationBento() {
  const rows = [["Information Technology", 0.38], ["Financial Services", 0.27], ["Energy", 0.14], ["FMCG", 0.11], ["Others", 0.1]] as const;
  return (
    <div className="grid gap-4 sm:grid-cols-[1.1fr_1fr]">
      <Frame className="p-6 sm:row-span-2"><HealthRing score={78} size={110} />
        <div className="mt-6 space-y-3">
          {rows.map(([k, v]) => (
            <div key={k}>
              <div className="flex justify-between text-small"><span>{k}</span><span className="tabular text-[var(--ink-muted)]">{Math.round(v * 100)}%</span></div>
              <div className="mt-1 h-1.5 rounded-full bg-[var(--surface-3)]"><div className="h-1.5 rounded-full bg-[var(--accent)]" style={{ width: `${v * 100 / 0.4}%`, opacity: 0.35 + v * 1.6 }} /></div>
            </div>
          ))}
        </div>
      </Frame>
      <Frame className="p-6"><RiskBar /></Frame>
      <Frame className="p-6">
        <div className="label text-[var(--ink-muted)]">Drawdown, worst</div>
        <div className="serif tabular mt-1 text-[28px] leading-none">−11.8%</div>
        <svg viewBox="0 0 240 60" className="mt-3 h-14 w-full" aria-hidden="true">
          <path d="M0,4 L30,6 L60,18 L80,42 L100,34 L130,22 L160,12 L200,8 L240,5" fill="none" stroke="var(--down)" strokeWidth="2" />
        </svg>
        <div className="text-caption text-[var(--ink-muted)]">Recovered in 74 days</div>
      </Frame>
    </div>
  );
}

export function ChatPreview() {
  return (
    <Frame className="p-6">
      <div className="ml-auto w-fit max-w-[80%] rounded-[18px] rounded-br-md bg-[var(--surface-3)] px-4 py-2.5 text-body">
        How can I invest ₹50,000 in banking and IT?
      </div>
      <div className="mt-5 flex gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--accent)] text-[11px] text-[var(--accent-ink)]">AI</span>
        <div className="min-w-0 text-body leading-relaxed">
          <p>For a moderate profile, the models&apos; best-ranked names in each sector:</p>
          <div className="mt-3 overflow-hidden rounded-[14px] border border-[var(--hairline)]">
            {[["Financial Services", "ICICIBANK", "18 × ₹1,342", "₹24,156"], ["Information Technology", "INFY", "15 × ₹1,598", "₹23,970"]].map((r) => (
              <div key={r[1]} className="grid grid-cols-[1.3fr_0.8fr_1fr_0.8fr] gap-2 border-b border-[var(--hairline)] px-3 py-2 text-caption last:border-0 sm:text-small">
                <span className="text-[var(--ink-muted)]">{r[0]}</span><b>{r[1]}</b><span className="tabular">{r[2]}</span><span className="tabular text-right">{r[3]}</span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[var(--ink-secondary)]">80% range over the next 10 sessions: −5.1% to +7.4%. ₹1,874 stays in cash.</p>
          <div className="mt-3 inline-flex items-center gap-2 rounded-full bg-[var(--sage-wash)] px-3 py-1 text-caption text-[var(--accent)]">
            ✓ 9 of 9 figures traced to WealthOS data
          </div>
        </div>
      </div>
    </Frame>
  );
}

export function AutopilotPreview() {
  const runs = [
    { d: "Fri 27 Nov", items: [["+", "ADANIPORTS", "new pick"], ["−", "TATASTEEL", "left the model's picks"], ["+", "DRREDDY", "resized to target"]] },
    { d: "Fri 20 Nov", items: [["+", "CGPOWER", "new pick"], ["+", "COALINDIA", "new pick"]] },
  ];
  return (
    <Frame className="p-6">
      <div className="flex items-center justify-between">
        <div className="label text-[var(--ink-muted)]">Autopilot · paper sleeve</div>
        <span className="rounded-full bg-[var(--sage-wash)] px-2.5 py-0.5 text-caption text-[var(--accent)]">On · weekly</span>
      </div>
      <div className="serif tabular mt-2 text-[34px] leading-none">₹1,04,812 <span className="text-body text-[var(--up)]">+4.8%</span></div>
      <ol className="mt-5 space-y-4">
        {runs.map((r) => (
          <li key={r.d} className="border-l-2 border-[var(--accent-dim)] pl-4">
            <div className="text-small font-medium">{r.d} · after the close</div>
            <ul className="mt-1 space-y-0.5 text-small text-[var(--ink-secondary)]">
              {r.items.map(([s, sym, why]) => <li key={sym}><span className={s === "+" ? "text-[var(--up)]" : "text-[var(--down)]"}>{s}</span> {sym} <span className="text-[var(--ink-muted)]">· {why}</span></li>)}
            </ul>
          </li>
        ))}
      </ol>
      <div className="mt-4 text-caption text-[var(--ink-muted)]">Regime: normal · 80% invested · stops at 1.25× forecast volatility</div>
    </Frame>
  );
}

function Range({ lo, hi }: { lo: number; hi: number }) {
  const pos = (v: number) => `${((v + 0.15) / 0.3) * 100}%`;
  return (
    <div className="flex items-center gap-2">
      <span className="tabular w-11 text-right text-caption text-[var(--down)]">{(lo * 100).toFixed(1)}%</span>
      <div className="relative h-1.5 w-28 rounded-full bg-[var(--surface-3)]">
        <span className="absolute -top-1 h-3.5 w-px bg-[var(--hairline-strong)]" style={{ left: pos(0) }} />
        <span className="absolute h-1.5 rounded-full bg-[var(--sage)]" style={{ left: pos(lo), width: `calc(${pos(hi)} - ${pos(lo)})` }} />
      </div>
      <span className="tabular w-11 text-caption text-[var(--up)]">+{(hi * 100).toFixed(1)}%</span>
    </div>
  );
}

export function PicksPreview() {
  const rows = [["1", "ADANIPORTS", "Services", -0.054, 0.075], ["2", "DRREDDY", "Healthcare", -0.05, 0.073], ["3", "ONGC", "Oil & Gas", -0.048, 0.069], ["4", "COALINDIA", "Metals & Mining", -0.045, 0.073]] as const;
  return (
    <Frame className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--hairline)] px-6 py-4">
        <div className="label text-[var(--ink-muted)]">Model picks · next 10 sessions</div>
        <span className="text-caption text-[var(--ink-muted)]">80% range</span>
      </div>
      {rows.map(([rank, sym, sector, lo, hi]) => (
        <div key={sym} className="flex items-center gap-4 border-b border-[var(--hairline)] px-6 py-3.5 last:border-0">
          <span className="tabular w-4 text-small text-[var(--ink-muted)]">{rank}</span>
          <div className="min-w-0 flex-1"><div className="text-body font-medium">{sym}</div><div className="text-caption text-[var(--ink-muted)]">{sector}</div></div>
          <Range lo={lo} hi={hi} />
        </div>
      ))}
    </Frame>
  );
}

export function MarketsPreview() {
  const tiles = [["RELIANCE", 1.8], ["HDFCBANK", -0.6], ["TCS", 0.9], ["INFY", 2.4], ["ICICIBANK", -1.2], ["ITC", 0.3], ["LT", 1.1], ["SBIN", -0.4], ["BHARTIARTL", 0.7]] as const;
  const chain = [[26000, "1.2L", "184.5", "62.1", "2.4L"], [26050, "86K", "151.0", "78.9", "1.1L"], [26100, "2.1L", "121.3", "99.6", "64K"]] as const;
  return (
    <div className="grid gap-4 sm:grid-cols-[1fr_1.15fr]">
      <Frame className="grid grid-cols-3 gap-1.5 p-3">
        {tiles.map(([s, c]) => (
          <div key={s} className="rounded-[10px] px-2 py-3 text-center"
            style={{ background: `color-mix(in oklab, var(${c >= 0 ? "--up" : "--down"}) ${Math.min(36, 8 + Math.abs(c) * 11)}%, var(--surface-1))` }}>
            <div className="text-caption font-medium">{s}</div>
            <div className="tabular text-caption">{c > 0 ? "+" : ""}{c.toFixed(1)}%</div>
          </div>
        ))}
      </Frame>
      <Frame className="p-4">
        <div className="label mb-3 text-[var(--ink-muted)]">NIFTY option chain</div>
        <div className="grid grid-cols-5 gap-2 border-b border-[var(--hairline)] pb-2 text-caption text-[var(--ink-muted)]"><span>Call OI</span><span>Call</span><span className="text-center">Strike</span><span>Put</span><span className="text-right">Put OI</span></div>
        {chain.map(([k, coi, c, p, poi]) => (
          <div key={k} className="grid grid-cols-5 gap-2 border-b border-[var(--hairline)] py-2 text-small last:border-0">
            <span className="tabular text-[var(--ink-muted)]">{coi}</span><span className="tabular">{c}</span>
            <span className="tabular text-center font-medium">{k}</span><span className="tabular">{p}</span><span className="tabular text-right text-[var(--ink-muted)]">{poi}</span>
          </div>
        ))}
        <div className="mt-2 text-caption text-[var(--ink-muted)]">Live with your Upstox account</div>
      </Frame>
    </div>
  );
}
