import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { TickerBar } from "@/components/TickerBar";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { AutoRefresh } from "@/components/AutoRefresh";
import { readFeed } from "@/lib/feed";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://overlay-gray.vercel.app";

export const metadata: Metadata = {
  metadataBase: new URL(BASE_URL),
  title: {
    default: "Overlay — ML Sports Betting Edge Detection",
    template: "%s | Overlay",
  },
  description:
    "Three-model ensemble (XGBoost + LightGBM + CatBoost) finds positive EV in NBA, MLB, and NHL lines. Public ledger, SHA-256 timestamped picks, free tools.",
  keywords: [
    "sports betting model",
    "MLB totals model",
    "NBA totals picks",
    "positive EV betting",
    "sports betting edge",
    "closing line value",
    "no vig calculator",
    "NRFI picks",
    "sports betting ML model",
    "quantitative sports betting",
  ],
  authors: [{ name: "Anthony McCrovitz" }],
  openGraph: {
    type: "website",
    siteName: "Overlay",
    title: "Overlay — ML Sports Betting Edge Detection",
    description:
      "Three-model ensemble finds positive EV in NBA, MLB, and NHL lines. 108-70 (60.7%) with +38u profit. Public ledger, free tools.",
    url: BASE_URL,
  },
  twitter: {
    card: "summary_large_image",
    site: "@ChefTonyAIBets",
    creator: "@ChefTonyAIBets",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true },
  },
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  themeColor: "#0A0B0D",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const feed = await readFeed();
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body>
        <AutoRefresh intervalMs={2 * 60 * 1000} />
        <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
          <TickerBar items={feed?.ticker || []} />
          <Header />
          <main style={{ flex: 1, width: "100%" }}>{children}</main>
          <Footer />
        </div>
      </body>
    </html>
  );
}
