import Link from "next/link";
import type { Metadata } from "next";
import { getGroups } from "@/lib/wcData";
import { pct } from "@/lib/wc";
import { Flag } from "@/components/wc/Flag";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "World Cup 2026 Group Standings — Advance Probabilities",
  description: "Simulated probability each team advances from its World Cup 2026 group to the knockout round.",
};

export default async function GroupsPage() {
  const g = await getGroups();
  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "32px 16px 100px" }}>
      <Link href="/world-cup" style={{ fontSize: 12, color: "var(--accent-hi)", textDecoration: "none" }}>← All matches</Link>
      <h1 style={{ fontSize: 30, fontWeight: 900, letterSpacing: "-0.02em", margin: "16px 0 6px", color: "var(--text-bright)" }}>Group standings</h1>
      <p style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 28 }}>
        Probability each team advances to the knockout round (top 2 + best thirds), from the bracket simulation.
      </p>
      {!g && <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 40, textAlign: "center" }}>Not generated yet.</div>}
      {g && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(240px,1fr))", gap: 14 }}>
          {Object.entries(g).sort(([a], [b]) => a.localeCompare(b)).map(([letter, rows]) => (
            <div key={letter} style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden" }}>
              <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", fontWeight: 800, fontSize: 13, color: "var(--text-bright)" }}>Group {letter}</div>
              {rows.map((r, i) => (
                <div key={r.team} style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "9px 14px",
                  borderBottom: i < rows.length - 1 ? "1px solid var(--border)" : "none",
                  background: i < 2 ? "var(--green-dim)" : "transparent",
                }}>
                  <span style={{ width: 14, fontSize: 11, fontWeight: 700, color: i < 2 ? "var(--green-hi)" : "var(--text-muted)" }}>{i + 1}</span>
                  <Flag team={r.team} size={14} />
                  <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: "var(--text-bright)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.team}</span>
                  <span className="mono" style={{ fontSize: 10, color: "var(--text-muted)" }}>{r.elo}</span>
                  <span className="mono" style={{ width: 42, textAlign: "right", fontSize: 13, fontWeight: 800, color: r.advance >= 0.5 ? "var(--green-hi)" : "var(--text-secondary)" }}>{pct(r.advance)}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
