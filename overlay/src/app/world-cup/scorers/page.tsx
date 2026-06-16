import Link from "next/link";
import type { Metadata } from "next";
import { getGoldenBoot } from "@/lib/wcData";
import { Flag } from "@/components/wc/Flag";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "World Cup 2026 Golden Boot Race — Projected Top Scorers",
  description: "Projected tournament goals for World Cup 2026 — recency-weighted goal share × team expected goals × bracket depth.",
};

export default async function ScorersPage() {
  const g = await getGoldenBoot();
  const max = g?.players[0]?.exp_goals ?? 1;
  return (
    <div style={{ maxWidth: 680, margin: "0 auto", padding: "32px 16px 100px" }}>
      <Link href="/world-cup" style={{ fontSize: 12, color: "var(--accent-hi)", textDecoration: "none" }}>← All matches</Link>
      <h1 style={{ fontSize: 30, fontWeight: 900, letterSpacing: "-0.02em", margin: "16px 0 6px", color: "var(--text-bright)" }}>Golden Boot race</h1>
      <p style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 28 }}>
        Projected tournament goals — each player&apos;s recency-weighted share of their nation&apos;s goals × team expected goals × how deep the bracket sim sends them.
      </p>
      {!g && <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 40, textAlign: "center" }}>Not generated yet.</div>}
      {g && (
        <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 14, overflow: "hidden" }}>
          {g.players.map((p, i) => (
            <div key={p.player + p.team} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 16px", borderBottom: i < g.players.length - 1 ? "1px solid var(--border)" : "none" }}>
              <span className="mono" style={{ width: 20, fontSize: 13, fontWeight: 800, color: i < 3 ? "var(--amber)" : "var(--text-muted)" }}>{i + 1}</span>
              <Flag team={p.team} size={18} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-bright)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.player}</div>
                <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{p.team}</div>
              </div>
              <div style={{ width: 120, height: 8, background: "var(--bg-overlay)", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ width: `${(p.exp_goals / max) * 100}%`, height: "100%", background: "var(--amber)" }} />
              </div>
              <span className="mono" style={{ width: 44, textAlign: "right", fontSize: 14, fontWeight: 800, color: "var(--text-bright)" }}>{p.exp_goals.toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}
      <p style={{ textAlign: "center", fontSize: 10, color: "var(--text-muted)", marginTop: 24, letterSpacing: "0.06em" }}>NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+</p>
    </div>
  );
}
