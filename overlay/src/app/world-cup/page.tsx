import Link from "next/link";
import type { Metadata } from "next";
import Board from "@/components/wc/Board";
import { getFixtures, getFutures, getMeta } from "@/lib/wcData";
import { pct, daysToKickoff, timeAgo } from "@/lib/wc";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "World Cup 2026 — Every Match Modeled",
  description: "Calibrated Elo + Poisson projections on all 72 World Cup 2026 group games — altitude, host edge, anytime scorers — shown honestly next to the market.",
};

const navBtn: React.CSSProperties = {
  fontSize: 12, fontWeight: 700, color: "var(--accent-hi)", textDecoration: "none",
  background: "var(--accent-dim)", border: "1px solid rgba(18,197,138,0.3)",
  borderRadius: 8, padding: "8px 14px",
};

export default async function WorldCupPage() {
  const [fixtures, futures, meta] = await Promise.all([getFixtures(), getFutures(), getMeta()]);
  const days = daysToKickoff();

  return (
    <div style={{ maxWidth: 820, margin: "0 auto", padding: "32px 16px 100px" }}>
      {/* hero */}
      <div style={{ textAlign: "center", marginBottom: 36 }}>
        <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.16em", color: "var(--green-hi)", marginBottom: 14 }}>
          {days > 0 ? `${days} DAYS TO KICKOFF` : "● LIVE — TOURNAMENT IN PROGRESS"}
        </div>
        <h1 style={{ fontSize: "clamp(30px,6vw,46px)", fontWeight: 900, lineHeight: 1.05, letterSpacing: "-0.03em", marginBottom: 14, color: "var(--text-bright)" }}>
          World Cup 2026<br />
          <span style={{ color: "var(--accent)" }}>every match, modeled.</span>
        </h1>
        <p style={{ fontSize: 15, color: "var(--text-secondary)", lineHeight: 1.6, maxWidth: 470, margin: "0 auto" }}>
          Calibrated Elo + Poisson projections on all 72 group games — altitude, host edge, and anytime scorers baked in. Shown honestly next to the market.
        </p>
        {meta?.generated && (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 7, marginTop: 14, padding: "5px 11px", borderRadius: 999, background: "var(--bg-panel)", border: "1px solid var(--border)" }}>
            <span style={{ width: 6, height: 6, borderRadius: 999, background: "var(--green-hi)", boxShadow: "0 0 6px var(--green-hi)" }} />
            <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
              Live odds · updated <strong style={{ color: "var(--text-bright)" }}>{timeAgo(meta.generated)}</strong>
            </span>
            <Link href="/world-cup/model" style={{ fontSize: 11, color: "var(--accent-hi)", textDecoration: "none" }}>how it works →</Link>
          </div>
        )}
        <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 20, flexWrap: "wrap" }}>
          <Link href="/world-cup/pass" style={{ ...navBtn, background: "var(--accent)", color: "#04130C", border: "1px solid var(--accent)" }}>Get the Pass — $9</Link>
          <Link href="/world-cup/futures" style={navBtn}>Championship odds →</Link>
          <Link href="/world-cup/scorers" style={navBtn}>Golden Boot →</Link>
          <Link href="/world-cup/groups" style={navBtn}>Group standings →</Link>
          <Link href="/world-cup/accuracy" style={navBtn}>Track record →</Link>
          <Link href="/world-cup/model" style={navBtn}>How it works →</Link>
        </div>
      </div>

      {/* futures strip */}
      {futures && (
        <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 16, padding: "16px 18px", marginBottom: 28 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <span style={{ fontWeight: 700, fontSize: 13, color: "var(--text-bright)" }}>Title favorites</span>
            <Link href="/world-cup/futures" style={{ fontSize: 11, color: "var(--accent-hi)", textDecoration: "none" }}>full table →</Link>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(110px,1fr))", gap: 10 }}>
            {futures.teams.slice(0, 6).map(t => (
              <div key={t.team} style={{ background: "var(--bg-raised)", borderRadius: 10, padding: "12px 10px" }}>
                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6, color: "var(--text-bright)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.team}</div>
                <div className="mono" style={{ fontWeight: 900, fontSize: 20, color: "var(--accent-hi)" }}>{pct(t.blend)}</div>
                <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: 3 }}>model {pct(t.model)} · mkt {t.market != null ? pct(t.market) : "—"}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* board */}
      {fixtures && fixtures.length > 0
        ? <Board fixtures={fixtures} />
        : <div style={{ color: "var(--text-muted)", fontSize: 13, textAlign: "center", padding: 40 }}>
            Projections not generated yet. Run <code>python3 chef.py wc</code>.
          </div>}

      <p style={{ textAlign: "center", fontSize: 10, color: "var(--text-muted)", marginTop: 36, letterSpacing: "0.06em" }}>
        {meta && `Model fitted ${meta.model_fitted_on} · ${meta.n_sims.toLocaleString()} simulations · ${meta.n_priced}/72 priced`}
        <br />NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+
      </p>
    </div>
  );
}
