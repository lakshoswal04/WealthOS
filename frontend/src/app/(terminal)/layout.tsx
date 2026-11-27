import { AppShell } from "@/components/trade/app-shell";

/** The chart terminal fills the screen: no chat sidebar, no ticker strip. */
export default function TerminalLayout({ children }: { children: React.ReactNode }) {
  return <AppShell bare>{children}</AppShell>;
}
