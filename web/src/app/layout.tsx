"use client";

import { Inter, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import { usePathname } from "next/navigation";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-mono-jetbrains", subsets: ["latin"], weight: ["400", "500", "600", "700"] });

const NAV = [
  { href: "/dashboard", label: "PICKS",    key: "F1" },
  { href: "/record",    label: "RECORD",   key: "F2" },
  { href: "/paper-trade", label: "VALIDATE", key: "F3" },
  { href: "/pricing",   label: "PRICING",  key: "F4" },
];

function TopBar({ pathname }: { pathname: string }) {
  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border-hi)] bg-[var(--bg-panel)]">
      {/* Primary nav row */}
      <div className="flex items-center h-9 px-3 gap-0 overflow-x-auto no-scrollbar">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-1.5 mr-4 flex-shrink-0">
          <span className="text-[var(--cyan)] font-bold text-sm tracking-widest">EDGE</span>
          <span className="text-[var(--text-muted)] text-sm">FINDER</span>
          <span className="ml-1 text-[9px] text-[var(--text-muted)] border border-[var(--border-hi)] px-1 py-px">v6.1</span>
        </Link>

        {/* Nav items */}
        <div className="flex items-center gap-px flex-shrink-0">
          {NAV.map((item) => {
            const active = pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-1 px-2.5 h-9 text-[11px] font-medium tracking-wider border-b-2 transition-colors ${
                  active
                    ? "border-[var(--cyan)] text-[var(--cyan)] bg-[var(--cyan-dim)]"
                    : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--bg-overlay)]"
                }`}
              >
                <span className="text-[var(--text-muted)] text-[9px] hidden sm:inline">{item.key}</span>
                {item.label}
              </Link>
            );
          })}
        </div>

        {/* Right: status */}
        <div className="ml-auto flex items-center gap-2 flex-shrink-0">
          <span className="hidden md:flex items-center gap-1.5 text-[10px] text-[var(--text-muted)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-dot inline-block" />
            MODEL ONLINE
          </span>
          <span className="text-[10px] text-[var(--text-muted)] hidden lg:block">
            MLB · NBA · NFL · NCAAB
          </span>
        </div>
      </div>
    </header>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <html lang="en" className={`${inter.variable} ${mono.variable} h-full`}>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="theme-color" content="#000000" />
        <title>EdgeFinder — ML Sports Betting Edge Detection</title>
        <meta name="description" content="Find mathematically proven edges against sportsbook lines. XGBoost ensemble, 91 features, walk-forward validated." />
      </head>
      <body className="min-h-full flex flex-col crt">
        <TopBar pathname={pathname} />
        <main className="flex-1">{children}</main>
        {/* Mobile bottom nav */}
        <nav className="fixed bottom-0 left-0 right-0 z-50 md:hidden border-t border-[var(--border-hi)] bg-[var(--bg-panel)] safe-bottom">
          <div className="flex items-center h-12">
            {NAV.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex-1 flex flex-col items-center justify-center gap-0.5 h-full text-[9px] tracking-widest font-medium transition-colors ${
                    active ? "text-[var(--cyan)] bg-[var(--cyan-dim)]" : "text-[var(--text-muted)]"
                  }`}
                >
                  <span className="text-[8px] text-[var(--text-muted)]">{item.key}</span>
                  {item.label}
                </Link>
              );
            })}
          </div>
        </nav>
        {/* Mobile nav spacer */}
        <div className="h-12 md:hidden" />
      </body>
    </html>
  );
}
