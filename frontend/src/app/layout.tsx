import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

/* A characterful serif for headings against a technical sans for the
   interface, with a mono reserved for figures so columns of numbers line up. */
// Fraunces is a variable font: `axes` and an explicit `weight` list are
// mutually exclusive, so the whole weight range stays available.
const display = Fraunces({
  subsets: ["latin"], variable: "--font-display",
  axes: ["SOFT", "WONK", "opsz"],
});
const body = IBM_Plex_Sans({
  subsets: ["latin"], variable: "--font-body", weight: ["400", "500", "600"],
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"], variable: "--font-mono", weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "WealthOS — Personal Wealth Intelligence",
  description:
    "Portfolio analytics, risk, goal forecasting and a grounded AI copilot. "
    + "An academic research prototype, not investment advice.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark">
      <body className={`${display.variable} ${body.variable} ${mono.variable} antialiased`}>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
