import Link from "next/link";
import type { Metadata } from "next";
import { getAccuracy } from "@/lib/wcData";
import { pct, WCCalibBin } from "@/lib/wc";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "World Cup Model Accuracy — Validated Track Record",
  description: "How the World Cup model performs on 800+ matches across 19 tournaments it never trained on. Calibration, Brier scores, and the honest limitations.",
};

function StatCard({ label, val, vs, good, sub }: { label: string; val: string; vs?: string; good?: boolean; sub?: string }) {
  const color = good === undefined ? "var(--text-bright)" : good ? "var(--green-hi)" : "var(--red-hi)";
  return (
    <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 12, padding: "16px 14px", textAlign: "center" }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 8 }}>{label}</div>
      <div className="mono" style={{ fontWeight: 900, fontSize: 22, color }}>{val}</div>
      {vs && <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>{vs}</div>}
      {sub && <div style={{ fontSize: 10, color: "var(--text-secondary)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

/* Reliability row: predicted vs actual hit-rate. Calibrated = the two align. */
function CalibRow({ b }: { b: WCCalibBin }) {
  const gap = Math.abs(b.pred - b.actual);
  const ok = gap <= 0.06;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0" }}>
      <span className="mono" style={{ width: 70, fontSize: 12, color: "var(--text-secondary)" }}>said {pct(b.pred)}</span>
      <div style={{ flex: 1, position: "relative", height: 22, background: "var(--bg-overlay)", borderRadius: 5, overflow: "hidden" }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${b.actual * 100}%`, background: ok ? "var(--green-dim)" : "rgba(245,158,11,0.18)" }} />
        {/* predicted marker */}
        <div style={{ position: "absolute", left: `calc(${b.pred * 100}% - 1px)`, top: 0, bottom: 0, width: 2, background: "var(--accent-hi)" }} />
        <span className="mono" style={{ position: "absolute", right: 8, top: 3, fontSize: 12, fontWeight: 700, color: "var(--text-bright)" }}>
          won {pct(b.actual)}
        </span>
      </div>
      <span className="mono" style={{ width: 42, fontSize: 10, color: "var(--text-muted)", textAlign: "right" }}>n={b.n}</span>
    </div>
  );
}

export default async function AccuracyPage() {
  const a = await getAccuracy();
  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: "32px 16px 100px" }}>
      <Link href="/world-cup" style={{ fontSize: 12, color: "var(--accent-hi)", textDecoration: "none" }}>← All matches</Link>
      <h1 style={{ fontSize: 30, fontWeight: 900, letterSpacing: "-0.02em", margin: "16px 0 6px", color: "var(--text-bright)" }}>Track record</h1>
      <p style={{ fontSize: 15, color: "var(--text-secondary)", marginBottom: 8, lineHeight: 1.6 }}>
        Most picks accounts show you their wins. Here&apos;s the whole model, graded on{" "}
        {a ? `${a.n_matches} matches across ${a.n_tournaments} tournaments` : "hundreds of matches"} it{" "}
        <strong style={{ color: "var(--text-bright)" }}>never trained on</strong> — using walk-forward validation (train on the past, test on the next tournament, no leakage).
      </p>
      <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 28 }}>
        Read how it works → <Link href="/world-cup/model" style={{ color: "var(--accent-hi)", textDecoration: "none" }}>The model</Link>
      </p>

      {!a && <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 40, textAlign: "center" }}>Validation data not generated yet.</div>}

      {a && (
        <>
          {/* headline metrics */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginBottom: 14 }}>
            <StatCard label="1X2 Brier" val={a.aggregate.brier_1x2.toFixed(3)} vs={`naive ${a.aggregate.brier_naive.toFixed(3)}`} good={a.aggregate.brier_1x2 < a.aggregate.brier_naive} sub="lower = sharper" />
            <StatCard label="Log loss" val={a.aggregate.log_loss.toFixed(3)} vs={`naive ${a.aggregate.log_loss_naive.toFixed(3)}`} good={a.aggregate.log_loss < a.aggregate.log_loss_naive} />
            <StatCard label="Modal accuracy" val={pct(a.aggregate.modal_acc, 1)} sub="of matches called" />
          </div>

          {/* principles */}
          <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 12, padding: "14px 18px", marginBottom: 28 }}>
            {[
              "Win probabilities are generated without using sportsbook odds as inputs.",
              "Every projection comes from one calibrated engine — no cherry-picking.",
              "We publish the methodology and these accuracy results openly, misses included.",
            ].map((t, i) => (
              <div key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "5px 0" }}>
                <span style={{ color: "var(--green-hi)", fontWeight: 800 }}>●</span>
                <span style={{ fontSize: 13, color: "var(--text)", lineHeight: 1.5 }}>{t}</span>
              </div>
            ))}
          </div>

          {/* calibration */}
          <h2 style={{ fontSize: 18, fontWeight: 800, color: "var(--text-bright)", marginBottom: 6 }}>Is it calibrated?</h2>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 16, lineHeight: 1.6 }}>
            When the model says a team has a given chance to win, how often does it actually happen? The blue line is what we said; the bar is what really occurred. Close together = honest probabilities.
          </p>
          <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 12, padding: "12px 16px", marginBottom: 28 }}>
            {a.calibration_favorite.map((b, i) => <CalibRow key={i} b={b} />)}
          </div>

          {/* honest limitation */}
          <div style={{ background: "rgba(245,158,11,0.07)", border: "1px solid rgba(245,158,11,0.25)", borderRadius: 12, padding: "16px 18px", marginBottom: 28 }}>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.06em", color: "var(--amber)", textTransform: "uppercase", marginBottom: 8 }}>What the model is NOT good at</div>
            <p style={{ fontSize: 13, color: "var(--text)", lineHeight: 1.6, margin: 0 }}>
              On over/under 2.5 goals, the model scores a Brier of <strong className="mono">{a.aggregate.brier_ou.toFixed(3)}</strong> — <strong>worse</strong> than just guessing the base rate (<span className="mono">{a.aggregate.brier_ou_naive.toFixed(3)}</span>). International totals are close to irreducibly random. So we show projected totals for context, but <strong style={{ color: "var(--text-bright)" }}>we do not sell them as edges.</strong> Most touts would hide this. We&apos;d rather you trust the numbers we do stand behind.
            </p>
          </div>

          {/* live 2026 */}
          <h2 style={{ fontSize: 18, fontWeight: 800, color: "var(--text-bright)", marginBottom: 6 }}>Live: World Cup 2026</h2>
          <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 12, padding: "20px", marginBottom: 28, textAlign: "center" }}>
            <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>Results post here after each match day, graded automatically.</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>First matches: June 11, 2026.</div>
          </div>

          {/* per tournament */}
          <h2 style={{ fontSize: 18, fontWeight: 800, color: "var(--text-bright)", marginBottom: 12 }}>Every tournament, graded</h2>
          <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Tournament", "Matches", "Brier", "Accuracy"].map((h, i) => (
                  <th key={h} style={{ padding: "9px 12px", textAlign: i === 0 ? "left" : "right", fontSize: 9, fontWeight: 700, letterSpacing: "0.06em", color: "var(--text-muted)", textTransform: "uppercase" }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {a.per_tournament.map(t => (
                  <tr key={t.label} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "9px 12px", fontSize: 13, color: "var(--text-bright)" }}>{t.label}</td>
                    <td className="mono" style={{ padding: "9px 12px", textAlign: "right", fontSize: 12, color: "var(--text-secondary)" }}>{t.n}</td>
                    <td className="mono" style={{ padding: "9px 12px", textAlign: "right", fontSize: 12, color: t.brier_1x2 < 0.3333 ? "var(--green-hi)" : "var(--text-secondary)" }}>{t.brier_1x2.toFixed(3)}</td>
                    <td className="mono" style={{ padding: "9px 12px", textAlign: "right", fontSize: 12, color: "var(--text)" }}>{pct(t.acc, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p style={{ textAlign: "center", fontSize: 10, color: "var(--text-muted)", marginTop: 24, letterSpacing: "0.06em" }}>
            Validated {a.generated} · walk-forward, no leakage · NOT FINANCIAL ADVICE · 21+
          </p>
        </>
      )}
    </div>
  );
}
