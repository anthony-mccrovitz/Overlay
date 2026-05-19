import type { Metadata } from "next";
import "./globals.css";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

export const metadata: Metadata = {
  title: "Overlay — Model-Backed Sports Picks",
  description:
    "Daily NBA & MLB picks from a transparent quantitative model. $29/mo, tracked record, no hype.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
          <Header />
          <main style={{ flex: 1, maxWidth: 1100, width: "100%", margin: "0 auto", padding: "32px 20px" }}>
            {children}
          </main>
          <Footer />
        </div>
      </body>
    </html>
  );
}
