"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { SiteFooter, SiteNav } from "@/components/marketing/chrome";
import {
  AutopilotPreview, ChatPreview, ConcentrationBento, FloatCard, HealthRing, Illustrative, InsightCard, MarketsPreview,
  PicksPreview, PortfolioPreview, RiskBar,
} from "@/components/marketing/previews";
import { useApi, useAuth } from "@/lib/auth";
import { editorial } from "@/lib/editorial";
import { useInView } from "@/lib/use-in-view";
import { signals } from "@/lib/trade-api";

/* The method band quotes the swing models' out-of-sample record from the
   pipeline reports at runtime; the fallbacks are the same measured values. */
const FALLBACK = { ic: 0.033, t: 3.7, hit: 0.511, cagr: 0.254, ew: 0.176, dsr: 0.99, coverage: 0.803 };

export default function LandingPage() {
  const { user } = useAuth();
  const reports = useApi(() => signals.reports().catch(() => null), []);
  const card = reports.data?.swing_model_card;
  const ranker = reports.data?.swing_ranker;
  const m = {
    ic: card?.signal?.mean_ic ?? FALLBACK.ic,
    t: card?.signal?.t_stat ?? FALLBACK.t,
    hit: card?.hit_rate?.relative ?? FALLBACK.hit,
    cagr: card?.backtest?.cagr ?? FALLBACK.cagr,
    ew: card?.equal_weight?.cagr ?? FALLBACK.ew,
    dsr: ranker?.models?.ensemble?.deflated_sharpe?.dsr ?? FALLBACK.dsr,
    coverage: ranker?.intervals?.oos_coverage_calibrated ?? FALLBACK.coverage,
  };
  const start = user ? "/home" : "/register";

  return (
    <>
      <SiteNav />
      <main className="landing-page overflow-x-clip">
        {/* ───────────────── hero ───────────────── */}
        <section className="mx-auto grid w-full max-w-[1240px] items-center gap-14 px-5 pb-20 pt-32 sm:px-8 lg:grid-cols-[1fr_1.08fr] lg:pt-40 [&>*]:min-w-0">
          <div data-stagger>
            <div className="label text-[var(--accent)]">AI wealth intelligence · India</div>
            <h1 className="display mt-6 text-[clamp(3.2rem,7vw,6rem)] leading-[0.98]">Your wealth. <em>Understood.</em></h1>
            <p className="mt-7 max-w-[30rem] text-[18px] leading-relaxed text-[var(--ink-secondary)]">
              WealthOS reads your portfolio on real NSE prices, ranks the market with models tested since 2013, and
              answers your questions with your own numbers, every one of them checked.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <Link href={start} className="label rounded-[var(--radius-sm)] bg-[var(--action)] px-6 py-3.5 text-[var(--action-ink)] hover:opacity-90">
                {user ? "Open WealthOS →" : "Get started →"}
              </Link>
              <Link href="#portfolio" className="label rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] px-6 py-3.5 text-[var(--ink-primary)] hover:bg-[var(--surface-1)]">
                Explore WealthOS
              </Link>
            </div>
            <p className="mt-6 text-small text-[var(--ink-muted)]">Free · paper trading only · not investment advice</p>
          </div>

          <div className="relative mx-auto w-full max-w-[600px] lg:mx-0">
            <div className="rise"><PortfolioPreview /></div>
            <FloatCard className="float-slow absolute -left-6 top-[34%] hidden [animation-delay:250ms,1.1s] sm:block lg:-left-24"><HealthRing /></FloatCard>
            <FloatCard className="float-slow absolute -bottom-20 left-10 hidden [animation-delay:450ms,2.2s] sm:block lg:-left-6"><RiskBar /></FloatCard>
            <FloatCard className="float-slow absolute -bottom-28 right-2 hidden [animation-delay:650ms,3.3s] md:block lg:-right-8"><InsightCard /></FloatCard>
            <Illustrative className="absolute -bottom-36 right-2 hidden md:block" />
          </div>
        </section>

        {/* ───────────────── proof strip ───────────────── */}
        <section className="mt-28 border-y border-[var(--hairline)] bg-[var(--surface-1)]">
          <div className="mx-auto grid w-full max-w-[1240px] grid-cols-2 gap-y-4 px-5 py-6 sm:px-8 md:grid-cols-4">
            {["Real NSE prices", "Walk-forward tested since 2013", "Every AI figure checked", "Paper trading only"].map((t) => (
              <div key={t} className="label flex items-center gap-2 text-[var(--ink-secondary)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" /> {t}
              </div>
            ))}
          </div>
        </section>

        {/* ───────────────── showcases ───────────────── */}
        <Showcase id="portfolio" label="Portfolio intelligence" title="Every holding, *in context.*"
          body="Import a CSV or sync Upstox and WealthOS prices it on real market history: a health score with its six parts, risk against your profile, concentration by sector and name, drawdowns and goals."
          points={["Health score you can take apart", "Risk measured against your own target", "Concentration flagged before it hurts"]}
          visual={<ConcentrationBento />} />
        <Showcase id="ai" flip label="An AI that shows its working" title="Ask anything. Get *your* numbers."
          body="Ask in plain words, in English or Hindi. The assistant calls WealthOS's own tools for every figure and refuses to invent one; each answer carries a check of every number it quotes."
          points={["Plans like “invest ₹50,000 across sectors”", "Memory of how you like answers", "Nothing is placed without your confirmation"]}
          visual={<ChatPreview />} />
        <Showcase id="autopilot" label="Autopilot" title="An autopilot that *explains itself.*"
          body="Give it a paper budget. Every week, after the close, it rebuilds its basket from the models' picks, sized for your risk profile and the market regime, and writes down exactly why."
          points={["Leans away from sectors you already hold", "Respects names and sectors you avoid", "One switch to pause, one to stop and sell"]}
          visual={<AutopilotPreview />} />
        <Showcase id="models" flip label="Model picks" title="Ranked by models *tested since 2013.*"
          body="A LightGBM ensemble ranks the NIFTY 100 for the next two weeks. Each pick comes with a calibrated range, a volatility forecast, a stop and a target, and the reasons behind its score."
          points={["Ranges, never price promises", "Volatility-sized stops and targets", "A forward test that cannot be rewritten"]}
          visual={<PicksPreview />} />
        <Showcase id="markets" label="Markets and options" title="The whole market, *one calm view.*"
          body="Movers, sector heatmaps, news, results calendars and a charting terminal on delayed prices; with your own Upstox account, live option chains, open interest and futures."
          points={["Option chains, OI and Greeks with Upstox", "Screeners and backtests on real history", "Paper-trade any idea at real prices"]}
          visual={<MarketsPreview />} />

        {/* ───────────────── how it decides ───────────────── */}
        <section id="method" className="on-accent mt-28 bg-[var(--accent)] text-[var(--accent-ink)]">
          <div className="mx-auto w-full max-w-[1240px] px-5 py-24 sm:px-8">
            <Reveal>
              <div className="label opacity-70">How it decides</div>
              <h2 className="display mt-5 max-w-3xl text-[clamp(2.4rem,4.6vw,4rem)] leading-[1.02]">
                Data, models, and advice <em>you can check.</em>
              </h2>
            </Reveal>
            <div className="mt-14 grid gap-10 md:grid-cols-3">
              {[
                ["01", "Real data", "NSE prices from Yahoo and your Upstox account, 24 years of history, with survivorship bias measured rather than ignored."],
                ["02", "Tested models", "Each year from 2013 scored by a model trained only on earlier data, with Indian trading costs on every trade."],
                ["03", "Checked answers", "Every number the AI quotes is traced back to a WealthOS measurement before you see it."],
              ].map(([n, t, b]) => (
                <Reveal key={n}>
                  <div className="label opacity-60">{n}</div>
                  <div className="serif mt-3 text-[28px] leading-tight">{t}</div>
                  <p className="mt-3 text-body leading-relaxed opacity-80">{b}</p>
                </Reveal>
              ))}
            </div>
            <div className="mt-16 grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-lg)] border border-[color-mix(in_oklab,var(--accent-ink)_20%,transparent)] bg-[color-mix(in_oklab,var(--accent-ink)_20%,transparent)] md:grid-cols-4">
              {[
                [m.ic.toFixed(3), "rank IC, out of sample", `t = ${m.t.toFixed(1)}`],
                [`${(m.hit * 100).toFixed(1)}%`, "stocks on the right side", "51% is a real edge"],
                [`${(m.cagr * 100).toFixed(1)}%`, "a year, top-10 book", `vs ${(m.ew * 100).toFixed(1)}% equal-weight`],
                [`${(m.coverage * 100).toFixed(0)}%`, "of outcomes inside the 80% range", "calibrated, 2013–2026"],
              ].map(([v, l, s]) => (
                <div key={l} className="bg-[var(--accent)] p-6">
                  <div className="serif tabular text-[40px] leading-none">{v}</div>
                  <div className="mt-3 text-small opacity-85">{l}</div>
                  <div className="label mt-1 opacity-55">{s}</div>
                </div>
              ))}
            </div>
            <p className="mt-6 max-w-3xl text-small opacity-70">
              After Indian delivery costs, walk-forward 2013–2026. Returns are flattered by survivorship (the universe is
              today&apos;s NIFTY 100), so judge the margin over equal-weight. Research signals, not investment advice.
            </p>
          </div>
        </section>

        {/* ───────────────── trust ───────────────── */}
        <section id="trust" className="mx-auto w-full max-w-[1240px] px-5 py-28 sm:px-8">
          <Reveal>
            <div className="label text-[var(--accent)]">Security and honesty</div>
            <h2 className="display mt-5 max-w-3xl text-[clamp(2.2rem,4.2vw,3.6rem)] leading-[1.04]">Built to be <em>trusted</em>, not to impress.</h2>
          </Reveal>
          <div className="mt-14 grid gap-5 md:grid-cols-3">
            {[
              ["Your keys stay yours", "Broker keys are encrypted at rest and never shown again. Each person connects their own Upstox account; data is never shared between users."],
              ["Paper first, always", "Every order, including Autopilot's, is placed on paper at real prices. Nothing reaches a broker or an exchange."],
              ["Plain about limits", "Model outputs are research signals. Ranges instead of promises, an out-of-sample record on every page, and no claims of guaranteed returns."],
            ].map(([t, b]) => (
              <Reveal key={t}>
                <div className="h-full rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-[var(--surface-1)] p-7">
                  <div className="serif text-[24px] leading-tight">{t}</div>
                  <p className="mt-3 text-body leading-relaxed text-[var(--ink-secondary)]">{b}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* ───────────────── closing CTA ───────────────── */}
        <section className="border-t border-[var(--hairline)]">
          <Reveal className="mx-auto w-full max-w-[1240px] px-5 py-28 text-center sm:px-8">
            <h2 className="display mx-auto max-w-4xl text-[clamp(2.6rem,6vw,5.2rem)] leading-[1]">Start with what you <em>own.</em></h2>
            <p className="mx-auto mt-6 max-w-xl text-[18px] leading-relaxed text-[var(--ink-secondary)]">
              Import your holdings in a minute, or start on paper with ₹10 lakh of virtual money.
            </p>
            <Link href={start} className="label mt-10 inline-block rounded-[var(--radius-sm)] bg-[var(--action)] px-7 py-4 text-[var(--action-ink)] hover:opacity-90">
              {user ? "Open WealthOS →" : "Get started →"}
            </Link>
          </Reveal>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}

function Reveal({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useInView<HTMLDivElement>();
  return <div ref={ref} className={`reveal ${className ?? ""}`}>{children}</div>;
}

function Showcase({ id, label, title, body, points, visual, flip = false }: {
  id: string; label: string; title: string; body: string; points: string[]; visual: ReactNode; flip?: boolean;
}) {
  return (
    <section id={id} className="mx-auto w-full max-w-[1240px] px-5 pt-28 sm:px-8">
      <div className={`grid items-center gap-14 lg:grid-cols-[0.9fr_1.1fr] [&>*]:min-w-0 ${flip ? "lg:[&>*:first-child]:order-2" : ""}`}>
        <Reveal>
          <div className="label text-[var(--accent)]">{label}</div>
          <h2 className="display mt-5 text-[clamp(2.2rem,4.2vw,3.6rem)] leading-[1.04]">{editorial(title)}</h2>
          <p className="mt-6 max-w-[34rem] text-body-lg leading-relaxed text-[var(--ink-secondary)]">{body}</p>
          <ul className="mt-7 space-y-3">
            {points.map((p) => (
              <li key={p} className="flex items-start gap-3 text-body">
                <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent)]" />{p}
              </li>
            ))}
          </ul>
        </Reveal>
        <Reveal>
          {visual}
          <Illustrative className="mt-3 block text-right" />
        </Reveal>
      </div>
    </section>
  );
}
