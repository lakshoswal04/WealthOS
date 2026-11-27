import Link from "next/link";
import { HealthRing } from "@/components/marketing/previews";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_1.05fr]">
      <section className="flex flex-col p-6 sm:p-10">
        <Link href="/" className="display text-[28px] font-normal leading-none">Wealth<span className="metal">OS</span></Link>
        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-sm">{children}</div>
        </div>
        <p className="text-caption text-[var(--ink-muted)]">Paper trading only · research signals, not investment advice</p>
      </section>

      {/* The editorial panel: what WealthOS is, in one line and one picture. */}
      <section className="on-accent relative hidden overflow-hidden bg-[var(--accent)] p-12 text-[var(--accent-ink)] lg:flex lg:flex-col lg:justify-between">
        <div className="label opacity-70">Personal wealth intelligence</div>
        <div>
          <h2 className="display max-w-lg text-[clamp(2.6rem,4vw,3.8rem)] leading-[1.02]">
            Your portfolio, <em>measured</em> rather than guessed at.
          </h2>
          <p className="mt-6 max-w-md text-body-lg leading-relaxed opacity-80">
            Real NSE prices, models tested since 2013, and an assistant that can only quote figures WealthOS computed.
          </p>
          <div className="mt-10 w-fit rounded-[18px] bg-[var(--surface-1)] p-5 text-[var(--ink-primary)] shadow-[var(--lift-3)]">
            <HealthRing />
            <div className="label mt-3 text-[var(--ink-faint)]">Illustrative preview</div>
          </div>
        </div>
        <dl className="grid grid-cols-3 gap-6 border-t border-[color-mix(in_oklab,var(--accent-ink)_22%,transparent)] pt-6">
          {[["24 yrs", "of NSE history"], ["2013–26", "walk-forward tested"], ["100%", "AI figures checked"]].map(([v, l]) => (
            <div key={l}>
              <dt className="serif tabular text-[26px] leading-none">{v}</dt>
              <dd className="mt-1.5 text-caption opacity-70">{l}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
