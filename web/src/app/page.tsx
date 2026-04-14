"use client";

import Link from "next/link";

const METRICS = [
  { key: "MODEL_ACCURACY",    val: "61.6%",    note: "2025 held-out test set" },
  { key: "HIGH_CONF_ACC",     val: "61.6%",    note: "XGBoost v6, 91 features" },
  { key: "SEASONS_PROFITABLE",val: "12 / 12",  note: "Walk-forward validated" },
  { key: "TRAINING_CORPUS",   val: "37,000+",  note: "Games, 2008–2024 seasons" },
];

const STACK = [
  { layer: "PRIMARY",    algo: "XGBoost v6",      detail: "91 features — team stats, pitcher form, park factors, weather, BvP" },
  { layer: "SECONDARY",  algo: "Pythagorean",     detail: "Run-differential projection, home/away splits" },
  { layer: "CALIBRATION",algo: "Isotonic Reg",    detail: "Probability calibration, no overconfidence" },
  { layer: "SIZING",     algo: "Quarter-Kelly",   detail: "Risk-adjusted bet sizing from model edge" },
];

const PROOF = [
  { claim: "Walk-forward CV",       detail: "Expanding training window. Model only sees data it had at prediction time. No look-ahead." },
  { claim: "SHA-256 pre-commitment",detail: "Every pick hashed before game starts. Track record mathematically impossible to backfill." },
  { claim: "CLV tracked",           detail: "Closing line value measured. Industry gold standard for real edge vs noise." },
  { claim: "Losses published",      detail: "Every losing week in the public record. No cherry-picking." },
];

export default function Home() {
  const now = new Date();
  const ts = now.toISOString().replace("T", " ").slice(0, 19) + " UTC";

  return (
    <div className="min-h-[calc(100vh-36px)] flex flex-col">
      {/* ── Terminal header ── */}
      <div className="border-b border-[var(--border-hi)] bg-[var(--bg-panel)]">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div>
            <div className="text-[10px] text-[var(--text-muted)] tracking-widest mb-1">
              EDGEFINDER TERMINAL — ML SPORTS BETTING EDGE DETECTION SYSTEM
            </div>
            <div className="text-xl sm:text-2xl font-bold tracking-tight text-[var(--text-bright)]">
              Find the edge.<span className="text-[var(--cyan)]"> Beat the book.</span>
              <span className="cursor ml-1" />
            </div>
          </div>
          <div className="hidden md:block text-right text-[10px] text-[var(--text-muted)]">
            <div>SYS TIME: {ts}</div>
            <div className="mt-1 flex items-center gap-1.5 justify-end">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-dot inline-block" />
              <span className="text-[var(--green)]">ALL SYSTEMS NOMINAL</span>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 py-6 w-full flex-1 flex flex-col gap-6">

        {/* ── Performance metrics ── */}
        <section>
          <div className="panel-header rounded-sm mb-0 border border-[var(--border-hi)] border-b-0">
            <span className="text-[10px] tracking-widest text-[var(--cyan)] font-semibold">PERFORMANCE METRICS</span>
            <span className="ml-auto text-[9px] text-[var(--text-muted)]">WALK-FORWARD VALIDATED</span>
          </div>
          <div className="border border-[var(--border-hi)] divide-y divide-[var(--border)]">
            {METRICS.map((m) => (
              <div key={m.key} className="flex items-center justify-between px-3 py-2.5 hover:bg-[var(--bg-overlay)] transition-colors">
                <span className="text-[11px] text-[var(--text-secondary)] tracking-wider font-medium">{m.key}</span>
                <div className="flex items-center gap-4">
                  <span className="text-[11px] text-[var(--text-muted)] hidden sm:block">{m.note}</span>
                  <span className="font-bold text-sm text-[var(--green)] font-mono tabular-nums min-w-[60px] text-right">{m.val}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ── Model stack + proof side by side ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

          {/* Model stack */}
          <section>
            <div className="panel-header rounded-sm border border-[var(--border-hi)] border-b-0">
              <span className="text-[10px] tracking-widest text-[var(--amber)] font-semibold">MODEL STACK</span>
            </div>
            <div className="border border-[var(--border-hi)] divide-y divide-[var(--border)]">
              {STACK.map((s) => (
                <div key={s.layer} className="px-3 py-2.5 hover:bg-[var(--bg-overlay)] transition-colors">
                  <div className="flex items-center gap-3 mb-0.5">
                    <span className="text-[9px] text-[var(--text-muted)] tracking-widest w-20 flex-shrink-0">{s.layer}</span>
                    <span className="text-xs text-[var(--cyan)] font-semibold">{s.algo}</span>
                  </div>
                  <div className="text-[10px] text-[var(--text-secondary)] pl-[5.75rem]">{s.detail}</div>
                </div>
              ))}
            </div>
          </section>

          {/* Verification */}
          <section>
            <div className="panel-header rounded-sm border border-[var(--border-hi)] border-b-0">
              <span className="text-[10px] tracking-widest text-[var(--green)] font-semibold">VERIFICATION PROTOCOL</span>
            </div>
            <div className="border border-[var(--border-hi)] divide-y divide-[var(--border)]">
              {PROOF.map((p) => (
                <div key={p.claim} className="px-3 py-2.5 hover:bg-[var(--bg-overlay)] transition-colors">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-[var(--green)] text-[10px]">■</span>
                    <span className="text-xs text-[var(--text-bright)] font-medium">{p.claim}</span>
                  </div>
                  <div className="text-[10px] text-[var(--text-secondary)] pl-4">{p.detail}</div>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* ── Data sources ── */}
        <section>
          <div className="panel-header rounded-sm border border-[var(--border-hi)] border-b-0">
            <span className="text-[10px] tracking-widest text-[var(--blue)] font-semibold">DATA SOURCES</span>
          </div>
          <div className="border border-[var(--border-hi)] grid grid-cols-2 sm:grid-cols-4 divide-x divide-[var(--border)]">
            {[
              { src: "MLB STATS API",  type: "REAL-TIME" },
              { src: "ODDS API",       type: "12+ BOOKS" },
              { src: "OPENWEATHERMAP",type: "PARK/WEATHER" },
              { src: "RETROSHEET",    type: "2008–2024" },
            ].map((d) => (
              <div key={d.src} className="px-3 py-3 text-center">
                <div className="text-[10px] text-[var(--text-secondary)] font-medium">{d.src}</div>
                <div className="text-[9px] text-[var(--text-muted)] mt-0.5 tracking-wider">{d.type}</div>
              </div>
            ))}
          </div>
        </section>

        {/* ── CTA ── */}
        <section className="border border-[var(--border-hi)] bg-[var(--bg-panel)]">
          <div className="px-4 py-5 flex flex-col sm:flex-row items-center gap-3 sm:gap-4">
            <div className="text-[11px] text-[var(--text-muted)] hidden sm:block">&gt;_</div>
            <div className="text-sm text-[var(--text-secondary)] text-center sm:text-left">
              Free picks every day. Pro unlocks market-open access and full Kelly sizing.
            </div>
            <div className="flex items-center gap-2 ml-auto">
              <Link
                href="/dashboard"
                className="border border-[var(--cyan)] text-[var(--cyan)] px-4 py-2 text-[11px] font-semibold tracking-widest hover:bg-[var(--cyan-dim)] transition-colors pressable"
              >
                [F1] ENTER TERMINAL
              </Link>
              <Link
                href="/record"
                className="border border-[var(--border-hi)] text-[var(--text-secondary)] px-4 py-2 text-[11px] font-semibold tracking-widest hover:border-[var(--border-hi)] hover:text-[var(--text)] hover:bg-[var(--bg-overlay)] transition-colors pressable"
              >
                [F2] TRACK RECORD
              </Link>
            </div>
          </div>
        </section>

        {/* ── Footer ── */}
        <div className="text-[9px] text-[var(--text-muted)] text-center pb-2 tracking-wider">
          EDGEFINDER v6.1 · NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+
        </div>
      </div>
    </div>
  );
}
