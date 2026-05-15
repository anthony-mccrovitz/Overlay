"use client";

import { Inter, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import { usePathname } from "next/navigation";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const mono  = JetBrains_Mono({ variable: "--font-mono-jetbrains", subsets: ["latin"], weight: ["400","500","600","700"] });

const NAV = [
  { href: "/",          label: "Home"   },
  { href: "/dashboard", label: "Picks"  },
  { href: "/record",    label: "Record" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isEarlyAccess = pathname === "/early-access";

  return (
    <html lang="en" className={`${inter.variable} ${mono.variable} h-full`}>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="theme-color" content="#06080f" />
        <title>Overlay — Find the edge every day</title>
        <meta name="description" content="AI-powered sharp betting analytics. Daily edges across MLB, NBA, and golf. Verified track record. No cherry-picking." />
      </head>
      <body className="min-h-full flex flex-col" style={{ background: "#06080f", color: "#e2e8f0" }}>

        {/* Nav — hidden on early-access page */}
        {!isEarlyAccess && (
          <header style={{
            position: "sticky", top: 0, zIndex: 50,
            background: "rgba(6,8,15,0.85)", backdropFilter: "blur(12px)",
            borderBottom: "1px solid rgba(255,255,255,0.06)",
          }}>
            <div style={{ maxWidth: 1100, margin: "0 auto", padding: "0 24px", height: 56, display: "flex", alignItems: "center", gap: 32 }}>

              {/* Logo */}
              <Link href="/" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none", flexShrink: 0 }}>
                <div style={{
                  width: 28, height: 28, borderRadius: 7,
                  background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 13, color: "#fff", fontWeight: 900,
                }}>◈</div>
                <span style={{ fontWeight: 800, fontSize: 16, color: "#f1f5f9", letterSpacing: "-0.02em" }}>Overlay</span>
              </Link>

              {/* Links */}
              <nav style={{ display: "flex", gap: 4, flex: 1 }}>
                {NAV.map(({ href, label }) => {
                  const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
                  return (
                    <Link key={href} href={href} style={{
                      padding: "5px 12px", borderRadius: 7, fontSize: 13, fontWeight: 500,
                      textDecoration: "none", transition: "all 0.15s",
                      color: active ? "#818cf8" : "#64748b",
                      background: active ? "rgba(99,102,241,0.1)" : "transparent",
                    }}>{label}</Link>
                  );
                })}
              </nav>

              {/* CTA */}
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginLeft: "auto" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", animation: "pulse-dot 2s ease-in-out infinite" }} />
                  <span style={{ fontSize: 10, color: "#22c55e", fontWeight: 700, letterSpacing: "0.12em" }}>LIVE</span>
                </div>
                <Link href="/early-access" style={{
                  background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
                  color: "#fff", fontWeight: 700, fontSize: 12,
                  padding: "7px 16px", borderRadius: 8, textDecoration: "none",
                  letterSpacing: "0.03em",
                }}>Get Access →</Link>
              </div>
            </div>
          </header>
        )}

        <main style={{ flex: 1 }}>{children}</main>

        {/* Mobile bottom nav */}
        {!isEarlyAccess && (
          <>
            <nav style={{
              position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 50,
              borderTop: "1px solid rgba(255,255,255,0.07)",
              background: "rgba(6,8,15,0.95)", backdropFilter: "blur(12px)",
              display: "flex", height: 56,
            }} className="md:hidden">
              {[...NAV, { href: "/early-access", label: "Join" }].map(({ href, label }) => {
                const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
                const isJoin = href === "/early-access";
                return (
                  <Link key={href} href={href} style={{
                    flex: 1, display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center",
                    fontSize: 9, fontWeight: 700, letterSpacing: "0.1em",
                    textDecoration: "none",
                    color: isJoin ? "#818cf8" : active ? "#6366f1" : "#475569",
                    background: active && !isJoin ? "rgba(99,102,241,0.08)" : "transparent",
                  }}>
                    <span style={{ fontSize: 15, marginBottom: 2 }}>
                      {href === "/" ? "◎" : href === "/dashboard" ? "⚡" : href === "/record" ? "◼" : "★"}
                    </span>
                    {label.toUpperCase()}
                  </Link>
                );
              })}
            </nav>
            <div className="md:hidden" style={{ height: 56 }} />
          </>
        )}
      </body>
    </html>
  );
}
