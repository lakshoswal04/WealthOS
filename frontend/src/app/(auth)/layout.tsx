export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* The left panel states what the product is and, just as importantly,
          what it is not. */}
      <section className="grain relative hidden flex-col justify-between border-r border-[var(--hairline)] bg-[var(--surface-1)] p-10 lg:flex">
        <div>
          <div className="display text-[26px] leading-none tracking-tight">
            Wealth<span className="text-[var(--accent)]">OS</span>
          </div>
          <div className="mt-2 text-[10.5px] uppercase tracking-[0.16em] text-[var(--ink-muted)]">
            Personal wealth intelligence
          </div>
        </div>

        <div className="max-w-md">
          <h2 className="display text-[34px] leading-[1.12] text-[var(--ink-primary)]">
            Your portfolio,
            <br />
            <span className="text-[var(--accent)]">measured</span> rather than
            <br />
            guessed at.
          </h2>
          <p className="mt-5 text-[13.5px] leading-relaxed text-[var(--ink-secondary)]">
            Risk, concentration, goal projections and a health score computed
            from fifteen years of real Indian market history — then explained
            in plain language by an assistant that can only quote figures the
            backend produced.
          </p>

          <dl className="mt-8 grid grid-cols-3 gap-5">
            {[
              ["58", "assets priced"],
              ["2012–26", "market history"],
              ["6", "score components"],
            ].map(([value, label]) => (
              <div key={label}>
                <dt className="tabular text-[19px] text-[var(--ink-primary)]">{value}</dt>
                <dd className="mt-0.5 text-[11px] leading-snug text-[var(--ink-muted)]">{label}</dd>
              </div>
            ))}
          </dl>
        </div>

        <p className="max-w-md text-[11px] leading-relaxed text-[var(--ink-muted)]">
          An academic research prototype. It explains computed portfolio metrics
          and does not provide investment advice.
        </p>
      </section>

      <section className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-sm">{children}</div>
      </section>
    </div>
  );
}
