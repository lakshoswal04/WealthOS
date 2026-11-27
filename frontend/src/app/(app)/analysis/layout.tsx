"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";

/** The long-term portfolio analytics, reached from Portfolio → Analysis. */
const TABS = [
  { href: "/analysis/overview", label: "Overview" },
  { href: "/analysis/holdings", label: "Holdings" },
  { href: "/analysis/risk", label: "Risk" },
  { href: "/analysis/goals", label: "Goals" },
  { href: "/analysis/insights", label: "Insights" },
  { href: "/analysis/swing-lab", label: "Research · Swing Lab" },
  { href: "/analysis/model-lab", label: "Research · Model Lab" },
  { href: "/analysis/data-quality", label: "Research · Data" },
];

export default function AnalysisLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-[var(--hairline)]">
        <Link href="/portfolio" className="-mb-px pb-3 text-body-lg text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]">
          ← Paper portfolio
        </Link>
        <span className="mb-3 h-4 w-px bg-[var(--hairline-strong)]" />
        {TABS.map((t) => (
          <Link key={t.href} href={t.href}
            className={clsx("-mb-px border-b-2 pb-3 text-body-lg transition-colors",
              pathname === t.href ? "border-[var(--accent)] font-medium text-[var(--ink-primary)]"
                : "border-transparent text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]")}>
            {t.label}
          </Link>
        ))}
      </div>
      {children}
    </div>
  );
}
