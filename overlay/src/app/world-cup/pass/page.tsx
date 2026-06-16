import Link from "next/link";
import type { Metadata } from "next";
import { getMeta } from "@/lib/wcData";
import { daysToKickoff } from "@/lib/wc";
import { IconTrophy, IconBall } from "@/components/wc/Icons";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "World Cup Pass — $9 for the Whole Tournament",
  description: "Unlock every World Cup 2026 match projection, anytime-scorer prop, and edge for $9 — one payment, the whole tournament. Or go all-access for $19/mo.",
};

const WC_PASS_LINK = process.env.NEXT_PUBLIC_WC_PASS_LINK || "#";
const ALL_ACCESS_LINK = process.env.NEXT_PUBLIC_STRIPE_PAYMENT_LINK || "#";

function Check() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0, marginTop: 2 }}>
      <circle cx="12" cy="12" r="11" fill="rgba(34,197,94,0.14)" />
      <path d="M7 12.5l3 3 7-7" stroke="var(--green-hi)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Feature({ children, dim }: { children: React.ReactNode; dim?: boolean }) {
  return (
    <div style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
      <Check />
      <span style={{ fontSize: 13, color: dim ? "var(--text-secondary)" : "var(--text)", lineHeight: 1.5 }}>{children}</span>
    </div>
  );
}

export default async function PassPage() {
  const meta = await getMeta();
  const days = daysToKickoff();

  return (
    <div style={{ maxWidth: 820, margin: "0 auto", padding: "32px 16px 100px" }}>
      <Link href="/world-cup" style={{ fontSize: 12, color: "var(--accent-hi)", textDecoration: "none" }}>← All matches</Link>

      <div style={{ textAlign: "center", margin: "20px 0 36px" }}>
        <div className="mono" style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "5px 11px", borderRadius: 3, background: "var(--green-dim)", border: "1px solid rgba(34,197,94,0.3)", color: "var(--green-hi)", fontSize: 10, fontWeight: 700, letterSpacing: "0.14em", marginBottom: 18 }}>
          {days > 0 ? `${days} DAYS TO KICKOFF` : "TOURNAMENT LIVE"}
        </div>
        <h1 style={{ fontSize: 38, fontWeight: 900, letterSpacing: "-0.025em", color: "var(--text-bright)", margin: "0 0 10px" }}>
          The whole World Cup. <span style={{ color: "var(--accent)" }}>$9.</span>
        </h1>
        <p style={{ fontSize: 15, color: "var(--text-secondary)", maxWidth: 460, margin: "0 auto", lineHeight: 1.6 }}>
          One payment unlocks every match projection, anytime-scorer prop, and model edge through the final. No subscription, no auto-renew.
        </p>
      </div>

      <div className="wc-pricing-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 28 }}>
        {/* World Cup Pass */}
        <div style={{ position: "relative", background: "var(--bg-panel)", border: "1px solid rgba(18,197,138,0.4)", borderRadius: 16, overflow: "hidden" }}>
          <div style={{ height: 3, background: "linear-gradient(90deg, var(--accent), #0EA98F)" }} />
          <div style={{ padding: "22px 22px 20px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <IconTrophy size={16} color="var(--accent-hi)" />
              <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.1em", color: "var(--accent-hi)", textTransform: "uppercase" }}>World Cup Pass</span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 4 }}>
              <span style={{ fontSize: 40, fontWeight: 900, color: "var(--text-bright)", letterSpacing: "-0.03em" }}>$9</span>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>one-time</span>
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 20 }}>Full access through the final · {meta?.kickoff ?? "Jun 11"} → Jul 19</div>
            <a href={WC_PASS_LINK} className="btn-primary" style={{ display: "block", textAlign: "center", marginBottom: 20 }} target="_blank" rel="noopener noreferrer">
              Get the Pass — $9
            </a>
            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
              <Feature>All 72 group matches + knockouts, projected</Feature>
              <Feature>Anytime-scorer probabilities, every match</Feature>
              <Feature>Model-vs-market edges, sorted</Feature>
              <Feature>Golden Boot + championship simulations</Feature>
              <Feature>Altitude, host, and rest context</Feature>
            </div>
          </div>
        </div>

        {/* All-Access */}
        <div style={{ background: "var(--bg-raised)", border: "1px solid var(--border)", borderRadius: 16, overflow: "hidden" }}>
          <div style={{ padding: "22px 22px 20px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <IconBall size={16} color="var(--text-secondary)" />
              <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.1em", color: "var(--text-secondary)", textTransform: "uppercase" }}>All-Access</span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 4 }}>
              <span style={{ fontSize: 40, fontWeight: 900, color: "var(--text-bright)", letterSpacing: "-0.03em" }}>$19</span>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>/ month</span>
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 20 }}>Everything, all year · cancel anytime</div>
            <a href={ALL_ACCESS_LINK} className="btn-ghost" style={{ display: "block", textAlign: "center", marginBottom: 20 }} target="_blank" rel="noopener noreferrer">
              Go All-Access — $19/mo
            </a>
            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
              <Feature><strong style={{ color: "var(--text-bright)" }}>The World Cup Pass, included</strong></Feature>
              <Feature>Daily NBA, MLB &amp; NHL picks</Feature>
              <Feature>Every market: spreads, totals, props</Feature>
              <Feature>Full public ledger + edge scores</Feature>
              <Feature dim>Timestamped before every game</Feature>
            </div>
          </div>
        </div>
      </div>

      <p style={{ textAlign: "center", fontSize: 12, color: "var(--text-muted)", lineHeight: 1.6 }}>
        Secure checkout via Stripe · We publish our{" "}
        <Link href="/world-cup/accuracy" style={{ color: "var(--accent-hi)", textDecoration: "none" }}>full track record</Link>{" "}
        and{" "}
        <Link href="/world-cup/model" style={{ color: "var(--accent-hi)", textDecoration: "none" }}>methodology</Link>{" "}
        openly.<br />NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+
      </p>
    </div>
  );
}
