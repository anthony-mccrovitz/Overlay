import Link from "next/link";
import type { Metadata } from "next";
import { getFutures } from "@/lib/wcData";
import { pct, WCFuturesRow } from "@/lib/wc";
import { Flag } from "@/components/wc/Flag";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "World Cup 2026 Championship Odds — Model vs Market",
  description: "Monte Carlo championship odds for World Cup 2026, blended with the de-vigged market. See where the model disagrees with Vegas.",
};

function Disagree({ title, rows, tone }: { title: string; rows: WCFuturesRow[]; tone: "up" | "down" }) {
  const c = tone === "up" ? "var(--green-hi)" : "var(--red-hi)";
  return (
    <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 12, padding: "14px 16px" }}>
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.06em", color: "var(--text-secondary)", textTransform: "uppercase", marginBottom: 12 }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rows.slice(0, 4).map(r => (
          <div key={r.team} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-bright)", display: "inline-flex", alignItems: "center", gap: 7 }}><Flag team={r.team} size={13} /> {r.team}</span>
            <span className="mono" style={{ fontSize: 12, fontWeight: 800, color: c }}>{r.edge_pp! > 0 ? "+" : ""}{r.edge_pp}pp</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default async function FuturesPage() {
  const f = await getFutures();
  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: "32px 16px 100px" }}>
      <Link href="/world-cup" style={{ fontSize: 12, color: "var(--accent-hi)", textDecoration: "none" }}>← All matches</Link>
      <h1 style={{ fontSize: 30, fontWeight: 900, letterSpacing: "-0.02em", margin: "16px 0 6px", color: "var(--text-bright)" }}>Championship odds</h1>
      <p style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 28 }}>
        {f ? `Model run over ${f.n_sims.toLocaleString()} full-bracket simulations, blended with the de-vigged market. Blend = ${pct(f.blend_model_weight)} model.` : "Not generated yet."}
      </p>

      {f && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 28 }}>
            <Disagree title="Model loves more than Vegas" rows={f.disagreements.model_higher} tone="up" />
            <Disagree title="Model fades vs Vegas" rows={f.disagreements.model_lower} tone="down" />
          </div>
          <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 14, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Team", "Model", "Vegas", "Blend", "Final%", "Advance"].map((h, i) => (
                  <th key={h} style={{ padding: "10px 12px", textAlign: i === 0 ? "left" : "right", fontSize: 9, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)", textTransform: "uppercase" }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {f.teams.filter(t => t.blend >= 0.003).map(t => (
                  <tr key={t.team} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "10px 12px", fontSize: 13, fontWeight: 600, color: "var(--text-bright)" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><Flag team={t.team} size={14} /> {t.team}</span>
                    </td>
                    <td className="mono" style={{ padding: "10px 12px", textAlign: "right", fontSize: 12, color: "var(--text)" }}>{pct(t.model, 1)}</td>
                    <td className="mono" style={{ padding: "10px 12px", textAlign: "right", fontSize: 12, color: "var(--text-secondary)" }}>{t.market != null ? pct(t.market, 1) : "—"}</td>
                    <td className="mono" style={{ padding: "10px 12px", textAlign: "right", fontSize: 13, fontWeight: 800, color: "var(--accent-hi)" }}>{pct(t.blend, 1)}</td>
                    <td className="mono" style={{ padding: "10px 12px", textAlign: "right", fontSize: 12, color: "var(--text-secondary)" }}>{pct(t.reach_final, 1)}</td>
                    <td className="mono" style={{ padding: "10px 12px", textAlign: "right", fontSize: 12, color: "var(--text-secondary)" }}>{pct(t.advance, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ textAlign: "center", fontSize: 10, color: "var(--text-muted)", marginTop: 24, letterSpacing: "0.06em" }}>NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+</p>
        </>
      )}
    </div>
  );
}
