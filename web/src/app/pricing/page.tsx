"use client";

import Link from "next/link";
import { useState } from "react";

const FREE_FEATURES = [
  { f: "Daily picks (30 min delay)",      avail: true  },
  { f: "Public track record",              avail: true  },
  { f: "MLB moneyline picks",              avail: true  },
  { f: "Market-open access",               avail: false },
  { f: "Full Kelly bet sizing",            avail: false },
  { f: "All markets (ML, RL, O/U, Props)", avail: false },
  { f: "Verified prediction hashes",       avail: false },
];

const PRO_FEATURES = [
  { f: "Picks at market open",             avail: true },
  { f: "Full Kelly bet sizing",            avail: true },
  { f: "All markets (ML, RL, O/U, Props)", avail: true },
  { f: "Verified prediction hashes",       avail: true },
  { f: "Early access to new sports",       avail: true },
  { f: "Email picks recap",                avail: true },
  { f: "Daily picks (30 min delay)",       avail: true },
];

export default function PricingPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");

  async function startTrial() {
    setLoading(true);
    setError("");
    try {
      const res  = await fetch("/api/stripe/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        setError("CHECKOUT_ERROR: Failed to create session. Retry.");
        setLoading(false);
      }
    } catch {
      setError("NETWORK_ERROR: Connection failed. Retry.");
      setLoading(false);
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-3 py-4 space-y-px">

      {/* Header */}
      <div className="border border-[var(--border-hi)] bg-[var(--bg-panel)] px-4 py-3 flex items-center justify-between">
        <div>
          <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-0.5">EDGEFINDER</div>
          <div className="text-sm font-bold text-[var(--text-bright)]">ACCESS TIERS</div>
        </div>
        <div className="text-[9px] text-[var(--text-muted)]">7-DAY FREE TRIAL ON PRO</div>
      </div>

      {/* Comparison table */}
      <div className="border border-[var(--border-hi)]">
        <div className="panel-header">
          <span className="text-[10px] font-bold tracking-widest text-[var(--amber)]">▌ FEATURE COMPARISON</span>
        </div>

        {/* Column headers */}
        <div className="grid grid-cols-3 border-b border-[var(--border-hi)]">
          <div className="px-4 py-3 border-r border-[var(--border-hi)]">
            <div className="text-[9px] text-[var(--text-muted)] tracking-widest">FEATURE</div>
          </div>
          <div className="px-4 py-3 border-r border-[var(--border-hi)] text-center">
            <div className="text-[10px] font-bold text-[var(--text-secondary)] tracking-wider">FREE</div>
            <div className="text-[9px] text-[var(--text-muted)]">$0 / mo</div>
          </div>
          <div className="px-4 py-3 text-center bg-[var(--cyan-dim)]">
            <div className="text-[10px] font-bold text-[var(--cyan)] tracking-wider">PRO</div>
            <div className="text-[9px] text-[var(--text-muted)]">$35 / mo</div>
          </div>
        </div>

        {/* Feature rows */}
        {FREE_FEATURES.map((item, i) => (
          <div key={i} className="grid grid-cols-3 border-b border-[var(--border)] last:border-b-0 t-row">
            <div className="px-4 py-2.5 border-r border-[var(--border-hi)]">
              <span className="text-[11px] text-[var(--text-secondary)]">{item.f}</span>
            </div>
            <div className="px-4 py-2.5 border-r border-[var(--border-hi)] text-center">
              <span className={`text-sm font-bold ${item.avail ? "text-[var(--green)]" : "text-[var(--text-muted)]"}`}>
                {item.avail ? "■" : "·"}
              </span>
            </div>
            <div className="px-4 py-2.5 text-center bg-[var(--cyan-dim)]">
              <span className="text-sm font-bold text-[var(--green)]">■</span>
            </div>
          </div>
        ))}
      </div>

      {/* Pricing panels */}
      <div className="grid grid-cols-1 sm:grid-cols-2 border border-[var(--border-hi)]">

        {/* Free */}
        <div className="border-r border-[var(--border-hi)] p-5">
          <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">TIER_01</div>
          <div className="text-xl font-bold text-[var(--text-bright)]">FREE</div>
          <div className="text-2xl font-bold font-mono text-[var(--text-secondary)] mt-1">$0</div>
          <div className="text-[9px] text-[var(--text-muted)] mb-4">PERPETUAL ACCESS</div>
          <Link
            href="/dashboard"
            className="block text-center border border-[var(--border-hi)] text-[var(--text-secondary)] px-4 py-2.5 text-[11px] font-semibold tracking-widest hover:border-[var(--border-hi)] hover:text-[var(--text)] hover:bg-[var(--bg-overlay)] transition-colors pressable"
          >
            [ENTER TERMINAL]
          </Link>
        </div>

        {/* Pro */}
        <div className="p-5 bg-[var(--cyan-dim)]">
          <div className="text-[9px] text-[var(--cyan)] tracking-widest mb-1 font-semibold">TIER_02 · RECOMMENDED</div>
          <div className="text-xl font-bold text-[var(--text-bright)]">PRO</div>
          <div className="text-2xl font-bold font-mono text-[var(--cyan)] mt-1">$35</div>
          <div className="text-[9px] text-[var(--text-muted)] mb-4">PER MONTH · 7-DAY FREE TRIAL</div>
          {error && (
            <div className="text-[10px] text-[var(--red)] font-mono mb-2 border border-[var(--red)]/30 px-2 py-1 bg-[var(--red-dim)]">
              {error}
            </div>
          )}
          <button
            onClick={startTrial}
            disabled={loading}
            className="w-full border border-[var(--cyan)] text-[var(--cyan)] px-4 py-2.5 text-[11px] font-semibold tracking-widest hover:bg-[var(--cyan)] hover:text-black transition-colors pressable disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? "REDIRECTING..." : "[START FREE TRIAL]"}
          </button>
        </div>
      </div>

      {/* Footer note */}
      <div className="border border-[var(--border-hi)] bg-[var(--bg-panel)] px-4 py-3">
        <div className="text-[9px] text-[var(--text-muted)] tracking-wider text-center">
          POWERED BY STRIPE · 7-DAY FREE TRIAL · CANCEL ANYTIME · NO QUESTIONS ASKED · NOT FINANCIAL ADVICE · 21+
        </div>
      </div>

    </div>
  );
}
