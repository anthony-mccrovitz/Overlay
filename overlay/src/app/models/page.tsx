import { redirect } from "next/navigation";
import { getSession, isAllowlisted } from "@/lib/session";
import { readFeed, type ModelRow } from "@/lib/feed";
import { SubscribeButton } from "@/components/SubscribeButton";

export const dynamic = "force-dynamic";

type Tier = "t1" | "t2" | "shadow" | "paused";

const TIER_META: Record<Tier, { label: string; sub: string; accent: string; chipBg: string; chipBorder: string }> = {
  t1: {
    label: "Tier 1 — Proven",
    sub: "Peer-reviewed academic or documented professional results.",
    accent: "var(--green-hi)",
    chipBg: "rgba(34,210,122,0.10)",
    chipBorder: "rgba(34,210,122,0.35)",
  },
  t2: {
    label: "Tier 2 — Theoretically sound",
    sub: "Strong practitioner backing, mechanically defensible. Smaller stake.",
    accent: "var(--accent-hi)",
    chipBg: "rgba(45,127,255,0.10)",
    chipBorder: "rgba(45,127,255,0.35)",
  },
  shadow: {
    label: "Shadow — Tracking only",
    sub: "Building sample size or under rebuild. Not yet on the public card.",
    accent: "#F59E0B",
    chipBg: "rgba(245,158,11,0.10)",
    chipBorder: "rgba(245,158,11,0.35)",
  },
  paused: {
    label: "Paused — Research says don't bet",
    sub: "High vig, no documented edge, or persistent losses. Shown for transparency.",
    accent: "var(--text-muted)",
    chipBg: "var(--bg-raised)",
    chipBorder: "var(--border)",
  },
};

export default async function ModelsPage() {
  const session = getSession();
  if (!session?.email) redirect("/login");
  if (!isAllowlisted(session.email)) {
    return (
      <div style={{ maxWidth: 520, margin: "80px auto", textAlign: "center", padding: "0 20px" }}>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--text-bright)", marginBottom: 12 }}>
          Subscriber access
        </h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: 20 }}>
          The live model book is for founding members only. Subscribe to unlock.
        </p>
        <SubscribeButton />
      </div>
    );
  }

  const feed = await readFeed();
  const models = feed?.models || [];

  const grouped: Record<Tier, ModelRow[]> = { t1: [], t2: [], shadow: [], paused: [] };
  for (const m of models) {
    const t = (m.tier || "shadow") as Tier;
    (grouped[t] ||= []).push(m);
  }

  const liveCount = grouped.t1.length + grouped.t2.length;
  const totalProfit = [...grouped.t1, ...grouped.t2].reduce((s, m) => s + m.profit, 0);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "32px 24px", display: "flex", flexDirection: "column", gap: 28 }}>
      <div>
        <div className="eyebrow">The book</div>
        <h1 style={{ fontSize: 30, fontWeight: 800, color: "var(--text-bright)", margin: "6px 0 0", letterSpacing: "-0.015em" }}>
          Live model performance
        </h1>
        <p style={{ color: "var(--text-secondary)", marginTop: 8, maxWidth: 700, fontSize: 14 }}>
          Every model is grouped by research tier. Tier 1 is what the research literature
          and our own CLV say works. Tier 2 has practitioner backing. Shadow is tracked-only.
          Paused models are kept visible so you can see what we deliberately stopped — and why.
        </p>
      </div>

      <div className="grid-4">
        <Kpi label="Active card markets" value={String(liveCount)} color="var(--accent-hi)" />
        <Kpi label="Tracked (shadow)" value={String(grouped.shadow.length)} />
        <Kpi label="Paused" value={String(grouped.paused.length)} color="var(--text-muted)" />
        <Kpi
          label="T1+T2 profit"
          value={`${totalProfit >= 0 ? "+" : ""}${totalProfit.toFixed(2)}U`}
          color={totalProfit >= 0 ? "var(--green-hi)" : "var(--red-hi)"}
        />
      </div>

      {(["t1", "t2", "shadow", "paused"] as Tier[]).map((t) =>
        grouped[t].length > 0 ? <TierSection key={t} tier={t} rows={grouped[t]} /> : null
      )}

      {feed?.upcoming_models && feed.upcoming_models.length > 0 && (
        <section style={{ marginTop: 8 }}>
          <div style={{ marginBottom: 14 }}>
            <div className="eyebrow">On deck</div>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: "var(--text-bright)", margin: "4px 0 0" }}>
              Coming soon to the book
            </h2>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
            {feed.upcoming_models.map((m, i) => (
              <div key={i} className="panel" style={{ padding: 14 }}>
                <div className="eyebrow" style={{ color: "var(--accent-hi)" }}>{m.sport.toUpperCase()}</div>
                <div style={{ fontSize: 15, fontWeight: 700, color: "var(--text-bright)", margin: "6px 0" }}>{m.label}</div>
                <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8 }}>{m.teaser}</div>
                <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>ETA · {m.eta}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      <div
        style={{
          padding: "14px 16px",
          background: "var(--bg-raised)",
          borderRadius: 4,
          border: "1px solid var(--border)",
          fontSize: 12,
          color: "var(--text-muted)",
          lineHeight: 1.6,
        }}
      >
        <strong style={{ color: "var(--text-secondary)" }}>How this works:</strong> Tiering is set
        by research — not vibes. Tier 1 promotion requires ≥30 settled picks, positive ROI, and
        non-negative CLV. Demotion triggers if ROI drops below 0% on a rolling 60-pick window.
      </div>
    </div>
  );
}

function TierSection({ tier, rows }: { tier: Tier; rows: ModelRow[] }) {
  const meta = TIER_META[tier];
  return (
    <section>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 800, color: meta.accent, margin: 0, letterSpacing: "-0.01em" }}>
            {meta.label}
          </h2>
          <p style={{ color: "var(--text-secondary)", margin: "4px 0 0", fontSize: 12 }}>{meta.sub}</p>
        </div>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", letterSpacing: "0.1em" }}>
          {rows.length} MODEL{rows.length === 1 ? "" : "S"}
        </span>
      </div>

      <div className="panel scroll-x" style={{ overflow: "hidden" }}>
        <table className="ledger">
          <thead>
            <tr>
              <th>Model</th>
              <th>Sport</th>
              <th style={{ textAlign: "right" }}>N</th>
              <th style={{ textAlign: "right" }}>Record</th>
              <th style={{ textAlign: "right" }}>Win%</th>
              <th style={{ textAlign: "right" }}>ROI</th>
              <th style={{ textAlign: "right" }}>Profit</th>
              <th style={{ textAlign: "right" }}>Pending</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.key}>
                <td style={{ color: "var(--text-bright)", fontWeight: 600 }}>{m.label}</td>
                <td className="mono" style={{ color: "var(--text-secondary)", fontSize: 11, letterSpacing: "0.06em" }}>
                  {m.sport}
                </td>
                <td className="mono" style={{ textAlign: "right" }}>{m.settled}</td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {m.settled > 0
                    ? `${m.wins}–${m.losses}${m.pushes > 0 ? `–${m.pushes}` : ""}`
                    : "—"}
                </td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {m.win_rate === null ? (
                    <span style={{ color: "var(--text-muted)" }}>—</span>
                  ) : (
                    <span style={{ color: m.win_rate >= 52.4 ? "var(--green-hi)" : "var(--text-secondary)" }}>
                      {m.win_rate.toFixed(1)}%
                    </span>
                  )}
                </td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {m.roi === null ? (
                    <span style={{ color: "var(--text-muted)" }}>—</span>
                  ) : (
                    <span className={m.roi >= 0 ? "pos" : "neg"} style={{ fontWeight: 700 }}>
                      {m.roi >= 0 ? "+" : ""}
                      {m.roi.toFixed(1)}%
                    </span>
                  )}
                </td>
                <td
                  className={`mono ${m.profit >= 0 ? "pos" : "neg"}`}
                  style={{ textAlign: "right", fontWeight: 700 }}
                >
                  {m.settled > 0 ? `${m.profit >= 0 ? "+" : ""}${m.profit.toFixed(1)}U` : "—"}
                </td>
                <td className="mono" style={{ textAlign: "right", color: "var(--text-muted)" }}>
                  {m.pending > 0 ? m.pending : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Kpi({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="panel" style={{ padding: "14px 18px" }}>
      <div className="label-muted">{label}</div>
      <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: color || "var(--text-bright)", marginTop: 4 }}>
        {value}
      </div>
    </div>
  );
}
