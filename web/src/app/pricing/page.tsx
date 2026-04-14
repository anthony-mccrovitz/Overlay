"use client";

import Link from "next/link";
import { useState } from "react";
import { motion } from "framer-motion";
import { Check, Zap, ArrowRight, Loader2 } from "lucide-react";

const FREE_FEATURES = [
  "Daily picks (delayed 30 min)",
  "Public track record",
  "MLB moneyline picks",
  "Kelly sizing reference",
];

const PRO_FEATURES = [
  "Picks at market open",
  "Full Kelly bet sizing",
  "All markets (ML, Run Line, O/U)",
  "Verified prediction hashes",
  "Early access to new sports",
  "Email picks recap",
];

export default function PricingPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function startTrial() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/stripe/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        setError("Something went wrong. Try again.");
        setLoading(false);
      }
    } catch {
      setError("Network error. Try again.");
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl px-4 pt-8 pb-6 md:pt-16">
      <div className="mb-10 text-center">
        <h1 className="text-2xl font-bold mb-2">Simple pricing</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Free picks daily. Pro gets you there first.
        </p>
      </div>

      <div className="space-y-3">
        {/* Free plan */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] p-6"
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="text-lg font-bold">Free</h2>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                See the model work. Picks drop 30 min after market open.
              </p>
            </div>
            <div className="text-right">
              <span className="text-3xl font-bold">$0</span>
              <span className="text-sm text-[var(--text-muted)]"> forever</span>
            </div>
          </div>
          <ul className="space-y-2 mb-5">
            {FREE_FEATURES.map((f) => (
              <li key={f} className="flex items-center gap-2 text-sm">
                <Check size={14} className="text-[var(--text-muted)]" />
                <span className="text-[var(--text-secondary)]">{f}</span>
              </li>
            ))}
          </ul>
          <Link
            href="/dashboard"
            className="flex items-center justify-center gap-2 w-full rounded-xl py-2.5 text-sm font-semibold transition-all pressable border border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--border-hover)] hover:text-white"
          >
            Get Started
            <ArrowRight size={14} />
          </Link>
        </motion.div>

        {/* Pro plan */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="rounded-2xl border border-[var(--accent)]/40 bg-[var(--bg-raised)] p-6"
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold">Pro</h2>
                <span className="inline-flex items-center gap-1 rounded-full bg-[var(--accent)] px-2 py-0.5 text-[10px] font-semibold text-black">
                  <Zap size={10} /> Popular
                </span>
              </div>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                Full access at market open. Kelly sizing. All markets.
              </p>
            </div>
            <div className="text-right">
              <span className="text-3xl font-bold">$35</span>
              <span className="text-sm text-[var(--text-muted)]">/mo</span>
            </div>
          </div>
          <ul className="space-y-2 mb-5">
            {PRO_FEATURES.map((f) => (
              <li key={f} className="flex items-center gap-2 text-sm">
                <Check size={14} className="text-[var(--accent)]" />
                <span className="text-[var(--text-secondary)]">{f}</span>
              </li>
            ))}
          </ul>
          {error && (
            <p className="text-xs text-[var(--red)] mb-3 text-center">{error}</p>
          )}
          <button
            onClick={startTrial}
            disabled={loading}
            className="flex items-center justify-center gap-2 w-full rounded-xl py-2.5 text-sm font-semibold transition-all pressable bg-[var(--accent)] text-black hover:brightness-110 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {loading ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Redirecting...
              </>
            ) : (
              <>
                Start 7-Day Free Trial
                <ArrowRight size={14} />
              </>
            )}
          </button>
        </motion.div>
      </div>

      <div className="mt-8 text-center text-xs text-[var(--text-muted)]">
        7-day free trial. Cancel anytime. No questions asked.
        <br />
        Powered by Stripe. Card required to start trial.
      </div>
    </div>
  );
}
