"use client";

import { Inter, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Home,
  Trophy,
  Zap,
  CreditCard,
  Activity,
  Menu,
  X,
} from "lucide-react";
import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import "./globals.css";

const sans = Inter({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = JetBrains_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const NAV = [
  { href: "/", label: "Home", icon: Home, mobileOnly: true },
  { href: "/dashboard", label: "Picks", icon: Zap, mobileOnly: false },
  { href: "/paper-trade", label: "Validate", icon: Activity, mobileOnly: false },
  { href: "/record", label: "Record", icon: Trophy, mobileOnly: false },
  { href: "/pricing", label: "Pricing", icon: CreditCard, mobileOnly: true },
];

function DesktopNav({ pathname }: { pathname: string }) {
  return (
    <nav className="hidden md:block border-b border-[var(--border)] bg-[var(--bg-raised)]/80 backdrop-blur-xl sticky top-0 z-50">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-1.5 font-bold text-base tracking-tight">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--accent)] text-black text-xs font-black">
            E
          </div>
          <span>Edge<span className="text-[var(--accent)]">Finder</span></span>
        </Link>
        <div className="flex items-center gap-1">
          {NAV.filter((n) => !n.mobileOnly).map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  active
                    ? "bg-[var(--accent-dim)] text-[var(--accent)]"
                    : "text-[var(--text-secondary)] hover:text-white hover:bg-[var(--bg-overlay)]"
                }`}
              >
                <item.icon size={15} />
                {item.label}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}

function MobileNav({ pathname }: { pathname: string }) {
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 md:hidden border-t border-[var(--border)] bg-[var(--bg-raised)]/95 backdrop-blur-xl safe-bottom">
      <div className="flex items-center justify-around h-16 max-w-lg mx-auto">
        {NAV.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex flex-col items-center gap-0.5 px-3 py-1 rounded-xl transition-colors pressable ${
                active ? "text-[var(--accent)]" : "text-[var(--text-muted)]"
              }`}
            >
              <item.icon size={20} strokeWidth={active ? 2.5 : 1.5} />
              <span className="text-[10px] font-medium">{item.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} h-full antialiased`}>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="theme-color" content="#09090b" />
        <title>EdgeFinder — AI Sports Betting Edge Detection</title>
        <meta
          name="description"
          content="Find mathematically proven edges against sportsbook lines using ML models with verified track records."
        />
      </head>
      <body className="min-h-full flex flex-col">
        <DesktopNav pathname={pathname} />
        <main className="flex-1 pb-20 md:pb-0">{children}</main>
        <MobileNav pathname={pathname} />
      </body>
    </html>
  );
}
