import type { Metadata } from "next";
import { Inter_Tight, JetBrains_Mono, Newsreader } from "next/font/google";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

// Self-hosted at build time by next/font: no runtime font requests.
const serif = Newsreader({
  subsets: ["latin"], weight: ["300", "400", "500"], style: ["normal", "italic"],
  variable: "--font-serif-face", display: "swap",
});
const sans = Inter_Tight({
  subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-sans-face", display: "swap",
});
const mono = JetBrains_Mono({
  subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono-face", display: "swap",
});

export const metadata: Metadata = {
  title: "WealthOS — Your wealth, understood",
  description:
    "Portfolio intelligence, trained market models, an AI that answers with your own numbers, "
    + "and an Autopilot that runs on paper. Research signals, not investment advice.",
};

// Applies a saved theme before first paint, so a dark-theme user never sees
// a flash of the light page (and vice versa).
const THEME_BOOT = `try{var t=localStorage.getItem("wealthos.theme");if(t==="terminal"||t==="light")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="light" data-scroll-behavior="smooth"
      className={`${serif.variable} ${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body className="antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
