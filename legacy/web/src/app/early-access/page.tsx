"use client";

import { useState } from "react";
import Link from "next/link";

const STRIPE_LINK = "https://buy.stripe.com/REPLACE_ME";

/* ── SVG icons ── */
function IconDatabase() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
    </svg>
  );
}
function IconTrendingUp() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>
    </svg>
  );
}
function IconLayers() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>
    </svg>
  );
}
function IconTarget() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>
    </svg>
  );
}
function IconShield() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    </svg>
  );
}
function IconGrid() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
    </svg>
  );
}

const FEATURES = [
  { Icon: IconDatabase,   title: "Full MLB slate daily",           body: "Every game. Moneyline, run line, totals, NRFI, and pitcher/batter props with model edge scores." },
  { Icon: IconTrendingUp, title: "Full NBA slate daily",           body: "Game totals, spreads, and player props — all with model win probability and edge vs. the closing line." },
  { Icon: IconLayers,     title: "Model reasoning on every pick",  body: "Not just the pick — you see the math. Win probability, implied vs. model odds, edge calculation." },
  { Icon: IconTarget,     title: "Golf major models",              body: "Monte Carlo simulation for PGA events with course-fit adjustments and full field edge rankings." },
  { Icon: IconShield,     title: "Verified public record",         body: "Every pick logged with a timestamp before tip-off. Wins and losses both counted. No cherry-picking." },
  { Icon: IconGrid,       title: "Same-game parlay builder",       body: "Highest-edge legs on the same book, automatically selected and combined with payout calculations." },
];

const PICKS_TODAY = [
  { team: "Tampa Bay Rays ML",       odds: "+142", edge: "+19.5%", book: "FanDuel",    sport: "MLB" },
  { team: "Jack Flaherty OVER 6.5K", odds: "+163", edge: "+26.9%", book: "BetRivers",  sport: "MLB" },
  { team: "MIN/SAN OVER 218.5",      odds: "-108", edge: "+8.9%",  book: "DraftKings", sport: "NBA" },
  { team: "Scottie Scheffler WIN",   odds: "+560", edge: "+9.6%",  book: "Betfair",    sport: "PGA" },
];

const SPORT_COLORS: Record<string, string> = {
  MLB: "#002D72",
  NBA: "#C9082A",
  PGA: "#1E4620",
  NHL: "#000",
};

export default function EarlyAccess() {
  const [copied, setCopied] = useState(false);
  void copied; void setCopied;

  return (
    <div style={{ fontFamily: "'Inter', -apple-system, sans-serif", background: "#06080f", minHeight: "100vh", color: "#fff" }}>

      {/* Nav */}
      <div style={{ borderBottom: "1px solid rgba(255,255,255,0.07)", padding: "14px 24px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Link href="/" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
          <div style={{ width: 28, height: 28, borderRadius: 7, background: "linear-gradient(135deg, #6366f1, #8b5cf6)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, color: "#fff", fontWeight: 900 }}>
            ◈
          </div>
          <span style={{ fontWeight: 800, fontSize: 16, color: "#f1f5f9", letterSpacing: "-0.02em" }}>Overlay</span>
        </Link>
        <div style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", letterSpacing: "0.12em", textTransform: "uppercase" }}>Early Access</div>
      </div>

      <div style={{ maxWidth: 680, margin: "0 auto", padding: "44px 24px 80px" }}>

        {/* Hero */}
        <div style={{ textAlign: "center", marginBottom: 48 }}>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            background: "rgba(99,102,241,0.12)", border: "1px solid rgba(99,102,241,0.35)",
            borderRadius: 999, padding: "5px 14px", marginBottom: 20,
          }}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="#818cf8" style={{ flexShrink: 0 }}>
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
            </svg>
            <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.12em", color: "#818cf8", textTransform: "uppercase" }}>Early Access — Limited Spots</span>
          </div>

          <h1 style={{ fontSize: "clamp(32px, 6vw, 50px)", fontWeight: 900, lineHeight: 1.06, letterSpacing: "-0.03em", margin: "0 0 16px" }}>
            Find the overlay<br />
            <span style={{ background: "linear-gradient(90deg, #6366f1, #8b5cf6, #06b6d4)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
              every single day.
            </span>
          </h1>

          <p style={{ fontSize: 16, color: "rgba(255,255,255,0.5)", lineHeight: 1.65, maxWidth: 460, margin: "0 auto 32px" }}>
            AI-powered edge detection across MLB, NBA, and golf. Full model output daily — every pick, every market, with the math behind it.
          </p>

          <a href={STRIPE_LINK} style={{
            display: "inline-block",
            background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
            color: "#fff", fontWeight: 800, fontSize: 15,
            letterSpacing: "0.03em", padding: "15px 40px",
            borderRadius: 12, textDecoration: "none",
            boxShadow: "0 0 40px rgba(99,102,241,0.4)",
            marginBottom: 12,
          }}>
            Join Early Access — $29/month
          </a>
          <div style={{ fontSize: 11, color: "rgba(255,255,255,0.3)" }}>
            Cancel anytime. Price locks in at $29 — goes up at public launch.
          </div>
        </div>

        {/* Today's picks sample */}
        <div style={{
          background: "rgba(255,255,255,0.02)",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: 16, overflow: "hidden", marginBottom: 32,
        }}>
          <div style={{
            padding: "13px 20px", borderBottom: "1px solid rgba(255,255,255,0.07)",
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span style={{ fontWeight: 700, fontSize: 13 }}>Today&apos;s Model Output</span>
            <span style={{
              fontSize: 10, color: "rgba(255,255,255,0.3)",
              background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 999, padding: "3px 10px",
            }}>May 12, 2026</span>
          </div>

          {PICKS_TODAY.map((p, i) => (
            <div key={i} style={{
              padding: "13px 20px",
              borderBottom: i < PICKS_TODAY.length - 1 ? "1px solid rgba(255,255,255,0.05)" : "none",
              display: "flex", alignItems: "center", gap: 12,
            }}>
              <div style={{
                padding: "3px 7px", borderRadius: 5, flexShrink: 0,
                background: SPORT_COLORS[p.sport] ?? "#334155",
                fontSize: 9, fontWeight: 900, color: "#fff", letterSpacing: "0.06em",
              }}>{p.sport}</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{p.team}</div>
                <div style={{ fontSize: 11, color: "rgba(255,255,255,0.4)", marginTop: 2 }}>{p.odds} · {p.book}</div>
              </div>
              <div style={{
                background: "rgba(0,229,157,0.1)", border: "1px solid rgba(0,229,157,0.25)",
                color: "#00e59d", fontWeight: 800, fontSize: 11,
                padding: "3px 10px", borderRadius: 999, flexShrink: 0,
              }}>{p.edge} edge</div>
            </div>
          ))}

          <div style={{
            padding: "11px 20px", background: "rgba(99,102,241,0.05)",
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span style={{ fontSize: 11, color: "rgba(255,255,255,0.3)" }}>+ props, parlays, NRFI, full slate</span>
            <span style={{ fontSize: 11, color: "#818cf8", fontWeight: 700 }}>Subscribers only</span>
          </div>
        </div>

        {/* Features grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 40 }}>
          {FEATURES.map(({ Icon, title, body }, i) => (
            <div key={i} style={{
              background: "rgba(255,255,255,0.025)",
              border: "1px solid rgba(255,255,255,0.07)",
              borderRadius: 12, padding: "18px 16px",
            }}>
              <div style={{ color: "#6366f1", marginBottom: 10 }}><Icon /></div>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>{title}</div>
              <div style={{ fontSize: 12, color: "rgba(255,255,255,0.4)", lineHeight: 1.65 }}>{body}</div>
            </div>
          ))}
        </div>

        {/* Verified record */}
        <div style={{
          background: "rgba(255,255,255,0.02)",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: 16, padding: "24px", marginBottom: 32, textAlign: "center",
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.12em", color: "rgba(255,255,255,0.3)", textTransform: "uppercase", marginBottom: 16 }}>
            Verified 2025–26 Season Record
          </div>
          <div style={{ display: "flex", justifyContent: "center", gap: 40 }}>
            {[
              { label: "Overall",    val: "20-16", sub: "55.6% win rate" },
              { label: "Totals",     val: "6-1",   sub: "85.7% win rate" },
              { label: "Moneyline",  val: "11-7",  sub: "61.1% win rate" },
            ].map((s, i) => (
              <div key={i}>
                <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.08em" }}>{s.label}</div>
                <div style={{ fontWeight: 900, fontSize: 24, letterSpacing: "-0.02em", color: "#00e59d" }}>{s.val}</div>
                <div style={{ fontSize: 11, color: "rgba(255,255,255,0.35)", marginTop: 2 }}>{s.sub}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.2)", marginTop: 16 }}>
            All picks logged with timestamps before first pitch. card_pick=true only. No retroactive changes.
          </div>
        </div>

        {/* Bottom CTA */}
        <div style={{
          textAlign: "center",
          background: "linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.06))",
          border: "1px solid rgba(99,102,241,0.25)",
          borderRadius: 20, padding: "36px 24px",
        }}>
          <h2 style={{ fontSize: 24, fontWeight: 900, letterSpacing: "-0.02em", marginBottom: 8 }}>Ready to find the overlay?</h2>
          <p style={{ color: "rgba(255,255,255,0.45)", fontSize: 14, marginBottom: 24 }}>$29/month early access. Full slate. Every sport. Every day.</p>
          <a href={STRIPE_LINK} style={{
            display: "inline-block",
            background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
            color: "#fff", fontWeight: 800, fontSize: 15,
            letterSpacing: "0.03em", padding: "15px 40px",
            borderRadius: 12, textDecoration: "none",
            boxShadow: "0 0 40px rgba(99,102,241,0.3)",
          }}>
            Get Early Access — $29/mo
          </a>
          <div style={{ fontSize: 11, color: "rgba(255,255,255,0.2)", marginTop: 12 }}>
            Cancel anytime · Powered by Stripe · Secure checkout
          </div>
        </div>

        <p style={{ textAlign: "center", fontSize: 10, color: "rgba(255,255,255,0.15)", marginTop: 32, letterSpacing: "0.08em" }}>
          NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+ · RESULTS IN UNITS (1u = 1 UNIT STAKED FLAT)
        </p>
      </div>
    </div>
  );
}
