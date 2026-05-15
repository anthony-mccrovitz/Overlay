"use client";

import { useState } from "react";

const FREE_FEATURES = [
  { f: "1 pick per day (sample)",            avail: true  },
  { f: "Public track record",                avail: true  },
  { f: "Historical results",                  avail: true  },
  { f: "Market-open picks (full slate)",      avail: false },
  { f: "All markets: ML, RL, O/U, Props",    avail: false },
  { f: "Kelly bet sizing per pick",           avail: false },
  { f: "NRFI + pitcher props",                avail: false },
  { f: "NBA game picks",                      avail: false },
];

const PRO_FEATURES = [
  { f: "Full slate at market open",           avail: true },
  { f: "All markets: ML, RL, O/U, Props",    avail: true },
  { f: "Kelly bet sizing per pick",           avail: true },
  { f: "NRFI + pitcher props",                avail: true },
  { f: "NBA game picks",                      avail: true },
  { f: "Email pick recap each morning",       avail: true },
  { f: "Public track record",                 avail: true },
  { f: "1 pick per day (sample)",             avail: true },
];

function EmailCapture({ source = "pricing" }: { source?: string }) {
  const [email, setEmail]     = useState("");
  const [status, setStatus]   = useState<"idle" | "loading" | "done" | "error">("idle");
  const [message, setMessage] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setStatus("loading");
    try {
      const res  = await fetch("/api/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), tier: "founding", source }),
      });
      const data = await res.json();
      if (data.ok) {
        setStatus("done");
        setMessage(data.message ?? "You're on the list!");
      } else {
        setStatus("error");
        setMessage(data.error ?? "Something went wrong.");
      }
    } catch {
      setStatus("error");
      setMessage("Connection failed. Try again.");
    }
  }

  if (status === "done") {
    return (
      <div className="border border-[var(--green)] bg-[var(--green-dim)] px-4 py-4 text-center">
        <div className="text-[var(--green)] font-bold text-sm tracking-widest mb-1">YOU&apos;RE IN</div>
        <div className="text-[var(--text-secondary)] text-[11px]">{message} — we&apos;ll reach out before launch.</div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <input
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="your@email.com"
        className="bg-[var(--bg-overlay)] border border-[var(--border-hi)] px-4 py-3 text-[12px] font-mono text-[var(--text-bright)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--cyan)] transition-colors w-full"
      />
      <button
        type="submit"
        disabled={status === "loading"}
        className="border border-[var(--cyan)] text-[var(--cyan)] px-4 py-3 text-[11px] font-bold tracking-widest hover:bg-[var(--cyan)] hover:text-black transition-colors disabled:opacity-50"
      >
        {status === "loading" ? "JOINING..." : "CLAIM FOUNDING MEMBER SPOT →"}
      </button>
      {status === "error" && (
        <div className="text-[var(--red)] text-[10px]">{message}</div>
      )}
    </form>
  );
}

export default function PricingPage() {
  return (
    <div className="max-w-4xl mx-auto px-3 py-4 space-y-3 pb-20 md:pb-6">

      {/* Header */}
      <div className="border border-[var(--border-hi)] bg-[var(--bg-panel)] px-4 py-4">
        <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">CHEFTONYMEETS AI · PRICING</div>
        <div className="text-xl font-bold text-[var(--text-bright)] mb-1">Simple, transparent access.</div>
        <div className="text-[11px] text-[var(--text-secondary)]">
          Free tier always available. Pro founding members lock in $9/mo for life — no credit card until we launch billing.
        </div>
      </div>

      {/* Founding member callout */}
      <div className="border border-[var(--amber)] bg-[var(--amber-dim)] px-4 py-4">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[9px] font-bold tracking-widest text-[var(--amber)]">FOUNDING MEMBER — LIMITED SPOTS</span>
        </div>
        <div className="text-[var(--text-bright)] font-bold text-base mb-1">
          Lock in $9/mo forever before we go public at $35/mo.
        </div>
        <div className="text-[11px] text-[var(--text-secondary)] mb-3">
          Sign up with your email now. No payment info required — we&apos;ll reach out when billing opens. Your rate is locked as long as you stay subscribed.
        </div>
        <EmailCapture source="pricing-founding" />
      </div>

      {/* Feature comparison */}
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
            <div className="text-[9px] text-[var(--text-muted)]">$0 / mo · always</div>
          </div>
          <div className="px-4 py-3 text-center bg-[var(--cyan-dim)]">
            <div className="text-[10px] font-bold text-[var(--cyan)] tracking-wider">PRO</div>
            <div className="text-[9px] text-[var(--amber)]">$9/mo founding · $35 after</div>
          </div>
        </div>

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

      {/* Tier panels */}
      <div className="grid grid-cols-1 sm:grid-cols-2 border border-[var(--border-hi)]">

        {/* Free */}
        <div className="border-b sm:border-b-0 sm:border-r border-[var(--border-hi)] p-5">
          <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">TIER_01</div>
          <div className="text-xl font-bold text-[var(--text-bright)]">FREE</div>
          <div className="text-2xl font-bold font-mono text-[var(--text-secondary)] mt-1">$0</div>
          <div className="text-[9px] text-[var(--text-muted)] mb-4">NO SIGNUP REQUIRED</div>
          <ul className="space-y-1.5 mb-5">
            {FREE_FEATURES.filter(f => f.avail).map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-[11px] text-[var(--text-secondary)]">
                <span className="text-[var(--green)] mt-0.5 flex-shrink-0">■</span> {f.f}
              </li>
            ))}
          </ul>
          <a
            href="/"
            className="block text-center border border-[var(--border-hi)] text-[var(--text-secondary)] px-4 py-2.5 text-[11px] font-semibold tracking-widest hover:text-[var(--text)] hover:bg-[var(--bg-overlay)] transition-colors"
          >
            [START FREE]
          </a>
        </div>

        {/* Pro / Founding */}
        <div className="p-5 bg-[var(--cyan-dim)]">
          <div className="text-[9px] text-[var(--cyan)] tracking-widest mb-1 font-semibold">TIER_02 · FOUNDING MEMBER</div>
          <div className="text-xl font-bold text-[var(--text-bright)]">PRO</div>
          <div className="flex items-baseline gap-2 mt-1">
            <span className="text-2xl font-bold font-mono text-[var(--amber)]">$9</span>
            <span className="text-[var(--text-muted)] text-[11px]">/ mo founding · $35 after launch</span>
          </div>
          <div className="text-[9px] text-[var(--amber)] tracking-widest mb-4 font-bold">LIFETIME RATE · LOCK IT IN NOW</div>
          <ul className="space-y-1.5 mb-5">
            {PRO_FEATURES.slice(0, 5).map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-[11px] text-[var(--text-secondary)]">
                <span className="text-[var(--green)] mt-0.5 flex-shrink-0">■</span> {f.f}
              </li>
            ))}
          </ul>
          <EmailCapture source="pricing-pro-panel" />
        </div>
      </div>

      {/* FAQ */}
      <div className="border border-[var(--border-hi)]">
        <div className="panel-header">
          <span className="text-[10px] font-bold tracking-widest text-[var(--text-muted)]">▌ FAQ</span>
        </div>
        {[
          { q: "When does billing start?", a: "Not yet. Email signup puts you on the founding member list. We'll reach out before billing opens — no surprises." },
          { q: "What does $9/mo get me?", a: "Full access forever at the founding rate: every pick across MLB and NBA, all markets (ML, spread, totals, NRFI, props), Kelly sizing, and email recaps." },
          { q: "What if I cancel?", a: "Cancel anytime. If you re-subscribe after launch, you'll pay the public rate ($35/mo). The founding rate is a one-time lock." },
          { q: "Is the track record real?", a: "Yes. Every pick is logged with a timestamp before game time. Results are graded automatically. No cherry-picking, no retroactive edits." },
        ].map(({ q, a }, i) => (
          <div key={i} className="border-b border-[var(--border)] last:border-0 px-4 py-3">
            <div className="text-[11px] font-bold text-[var(--text-bright)] mb-1">{q}</div>
            <div className="text-[11px] text-[var(--text-secondary)] leading-relaxed">{a}</div>
          </div>
        ))}
      </div>

      <div className="text-[9px] text-[var(--text-muted)] text-center py-2 tracking-wider">
        NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+ · NO PAYMENT INFO REQUIRED AT SIGNUP
      </div>
    </div>
  );
}
