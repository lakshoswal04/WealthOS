import type { ReactNode } from "react";

/** The public shell. Deliberately separate from the dashboard: a visitor
 *  who is not signed in should never see an empty portfolio chrome. */
export default function MarketingLayout({ children }: { children: ReactNode }) {
  return <div className="min-h-screen">{children}</div>;
}
