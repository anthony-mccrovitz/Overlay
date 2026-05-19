import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { TickerBar } from "@/components/TickerBar";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { readFeed } from "@/lib/feed";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Overlay — Quant-backed NBA & MLB picks",
  description:
    "Three-model ensemble. Public ledger. Founding seats $29/mo. No touts, no parlays, no hype.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const feed = await readFeed();
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body>
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
