import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions, isAllowlisted } from "@/lib/auth";
import { readFeed } from "@/lib/feed";
import { SubscribeButton } from "@/components/SubscribeButton";

export const dynamic = "force-dynamic";

export default async function ModelsPage() {
  const session = await getServerSession(authOptions);
  if (!session?.user?.email) redirect("/login");
  if (!isAllowlisted(session.user.email)) {
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

  const sportOrder = ["NBA", "MLB"];
  const grouped: Record<string, typeof models> = {};
  for (const m of models) (grouped[m.sport] ||= []).push(m);

  const totalProfit = models.reduce((s, m) => s + m.profit, 0);
  const totalWins = models.reduce((s, m) => s + m.wins, 0);
  const totalLosses = models.reduce((s, m) => s + m.losses, 0);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "32px 24px", display: "flex", flexDirection: "column", gap: 28 }}>
      <div>
        <div className="eyebrow">The book</div>
        <h1 style={{ fontSize: 30, fontWeight: 800, color: "var(--text-bright)", margin: "6px 0 0", letterSpacing: "-0.015em" }}>
          Live model performance
        </h1>
        <p style={{ color: "var(--text-secondary)", marginTop: 8, maxWidth: 600, fontSize: 14 }}>
          Each row is an independent strategy in the ensemble. Settled card picks only — every loss
          is on the board.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <Kpi label="Total record" value={`${totalWins}–${totalLosses}`} />
        <Kpi
          label="Total profit"
          value={`${totalProfit >= 0 ? "+" : ""}${totalProfit.toFixed(2)}U`}
          color={totalProfit >= 0 ? "var(--green-hi)" : "var(--red-hi)"}
        />
        <Kpi label="Live models" value={String(models.length)} color="var(--accent-hi)" />
        <Kpi
          label="Profitable"
          value={String(models.filter((m) => m.profit > 0).length) + ` / ${models.length}`}
        />
      </div>

      {sportOrder.filter((s) => grouped[s]?.length).map((sport) => (
        <div key={sport} className="panel" style={{ overflow: "hidden" }}>
          <div
            style={{
              padding: "14px 20px",
              borderBottom: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
              gap: 10,
              background: "rgba(45,127,255,0.04)",
            }}
          >
            <span className="mono" style={{ color: "var(--accent-hi)", fontSize: 12, fontWeight: 800, letterSpacing: "0.12em" }}>
              [{sport}]
            </span>
            <span style={{ color: "var(--text-bright)", fontWeight: 700, fontSize: 14 }}>
              {grouped[sport].length} model{grouped[sport].length === 1 ? "" : "s"}
            </span>
          </div>
          <table className="ledger">
            <thead>
              <tr>
                <th>Model</th>
                <th>Status</th>
                <th style={{ textAlign: "right" }}>Record</th>
                <th style={{ textAlign: "right" }}>Win%</th>
                <th style={{ textAlign: "right" }}>ROI</th>
                <th style={{ textAlign: "right" }}>Profit</th>
                <th style={{ textAlign: "right" }}>Pending</th>
              </tr>
            </thead>
            <tbody>
              {grouped[sport].map((m) => (
                <tr key={m.key}>
                  <td style={{ color: "var(--text-bright)", fontWeight: 600 }}>{m.market_label}</td>
                  <td>
                    <span className="chip chip-win" style={{ background: "rgba(34,197,94,0.10)" }}>
                      <span
                        style={{
                          width: 5,
                          height: 5,
                          borderRadius: 999,
                          background: "var(--green-hi)",
                          display: "inline-block",
                          marginRight: 5,
                        }}
                      />
                      LIVE
                    </span>
                  </td>
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
                  <td className={`mono ${m.profit >= 0 ? "pos" : "neg"}`} style={{ textAlign: "right", fontWeight: 700 }}>
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
      ))}

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
        <strong style={{ color: "var(--text-secondary)" }}>How this works:</strong> Every model
        breaks out by sport × market. We post the card pick the moment a model finds a +EV edge —
        win or lose, it lands in this table. Profitable strategies stay; chronic losers get retired.
      </div>
    </div>
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
