"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  BarChart3,
  Shield,
  Zap,
  TrendingUp,
  ArrowRight,
  CheckCircle2,
  Brain,
  Eye,
} from "lucide-react";

const PROOF = [
  { value: "61.6%", label: "MLB accuracy", sub: "2025 held-out test" },
  { value: "61.6%", label: "High-conf picks", sub: "v6 model, 91 features" },
  { value: "12/12", label: "Winning seasons", sub: "Walk-forward validated" },
  { value: "37K+", label: "Games trained on", sub: "2008-2024 seasons" },
];

const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.08, duration: 0.5 },
  }),
};

export default function Home() {
  return (
    <div className="flex flex-col">
      {/* Hero — tight, no fluff */}
      <section className="mx-auto flex max-w-2xl flex-col items-center px-4 pt-16 pb-12 md:pt-24 md:pb-16 text-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4 }}
        >
          <div className="inline-flex items-center gap-1.5 rounded-full bg-[var(--accent-dim)] border border-[var(--accent)]/20 px-3 py-1 text-xs font-medium text-[var(--accent)] mb-6">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] live-dot" />
            Live picks available
          </div>
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, duration: 0.5 }}
          className="mb-4 text-4xl md:text-5xl font-bold leading-[1.1] tracking-tight"
        >
          ML models that find
          <br />
          <span className="text-[var(--accent)]">betting edges.</span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, duration: 0.5 }}
          className="mb-8 max-w-lg text-base text-[var(--text-secondary)] leading-relaxed"
        >
          XGBoost trained on 37,000+ games. Walk-forward validated across 12 seasons.
          Every prediction hashed before the game starts.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, duration: 0.5 }}
          className="flex flex-col sm:flex-row gap-3"
        >
          <Link
            href="/dashboard"
            className="flex items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-6 py-3 text-sm font-semibold text-black transition-all hover:brightness-110 pressable"
          >
            View Today&apos;s Picks
            <ArrowRight size={16} />
          </Link>
          <Link
            href="/record"
            className="flex items-center justify-center gap-2 rounded-xl border border-[var(--border)] px-6 py-3 text-sm font-semibold transition-colors hover:border-[var(--border-hover)] hover:bg-[var(--bg-raised)] pressable"
          >
            See Track Record
          </Link>
        </motion.div>
      </section>

      {/* Proof grid */}
      <section className="mx-auto max-w-2xl px-4 pb-16 w-full">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {PROOF.map((s, i) => (
            <motion.div
              key={s.label}
              custom={i}
              initial="hidden"
              animate="visible"
              variants={fadeUp}
              className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] p-4 text-center"
            >
              <div className="text-2xl md:text-3xl font-bold text-[var(--accent)] font-mono">
                {s.value}
              </div>
              <div className="mt-1 text-xs font-medium">{s.label}</div>
              <div className="mt-0.5 text-[10px] text-[var(--text-muted)]">{s.sub}</div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* How it works — minimal */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto max-w-2xl px-4 py-16">
          <h2 className="text-xl font-bold mb-8 text-center">How it works</h2>
          <div className="space-y-4">
            {[
              {
                icon: Brain,
                title: "Model predicts every game",
                desc: "XGBoost + ensemble trained on 37,000+ games. Team stats, pitcher recent form, batter vs pitcher history, park factors, weather — 91 features. Walk-forward validated, no look-ahead bias.",
              },
              {
                icon: Eye,
                title: "Compares to sportsbook lines",
                desc: "Scans 12+ books in real-time. When our model\'s probability disagrees with the market\'s implied probability, that\'s an edge.",
              },
              {
                icon: Zap,
                title: "Surfaces value bets with sizing",
                desc: "Kelly criterion sizes each bet based on edge size and your bankroll. You see exactly what to bet, where, and how much.",
              },
            ].map((item, i) => (
              <motion.div
                key={item.title}
                custom={i}
                initial="hidden"
                animate="visible"
                variants={fadeUp}
                className="flex gap-4 p-4 rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)]"
              >
                <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-[var(--accent-dim)] flex items-center justify-center">
                  <item.icon size={20} className="text-[var(--accent)]" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold mb-0.5">{item.title}</h3>
                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{item.desc}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Why different */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto max-w-2xl px-4 py-16">
          <h2 className="text-xl font-bold mb-8 text-center">Why this isn&apos;t another tout</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {[
              {
                icon: Shield,
                title: "Cryptographically verified",
                desc: "Predictions hashed before games. Our record is mathematically impossible to fake.",
              },
              {
                icon: BarChart3,
                title: "Walk-forward validated",
                desc: "Not cherrypicked backtests. Expanding-window CV across 12 seasons, tested on held-out 2025.",
              },
              {
                icon: TrendingUp,
                title: "Closing line value tracked",
                desc: "We track if picks beat where the line closes — the gold standard proof of real edge.",
              },
              {
                icon: CheckCircle2,
                title: "Transparent P&L",
                desc: "Every pick, every result, every dollar. Bad weeks included. No hidden losses.",
              },
            ].map((item, i) => (
              <motion.div
                key={item.title}
                custom={i}
                initial="hidden"
                animate="visible"
                variants={fadeUp}
                className="flex gap-3 p-4 rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)]"
              >
                <item.icon size={18} className="text-[var(--accent)] flex-shrink-0 mt-0.5" />
                <div>
                  <h3 className="text-sm font-semibold mb-0.5">{item.title}</h3>
                  <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">{item.desc}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-[var(--border)] bg-[var(--bg-raised)]">
        <div className="mx-auto max-w-2xl px-4 py-12 text-center">
          <h2 className="text-xl font-bold mb-2">Free picks every day.</h2>
          <p className="text-sm text-[var(--text-secondary)] mb-6">
            Upgrade for market-open access and Kelly sizing.
          </p>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-6 py-3 text-sm font-semibold text-black transition-all hover:brightness-110 pressable"
          >
            Get Started
            <ArrowRight size={16} />
          </Link>
        </div>
      </section>
    </div>
  );
}
