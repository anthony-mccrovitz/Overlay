import type { RecentPick } from "@/lib/feed";

export function RecentPicksTable({ rows }: { rows: RecentPick[] }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div className="panel" style={{ overflow: "hidden" }}>
      <div
        style={{
          padding: "18px 20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-bright)" }}>Recent picks</div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
            The last {rows.length} settled card plays. The losses stay in.
          </div>
        </div>
        <div className="label-muted">Auto-logged from the model</div>
      </div>
      <div className="scroll-x">
      <table className="ledger">
        <thead>
          <tr>
            <th>Date</th>
            <th>Matchup</th>
            <th>Pick</th>
            <th>Odds</th>
            <th>Result</th>
            <th style={{ textAlign: "right" }}>P/L</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const win = r.result === "WIN";
            const loss = r.result === "LOSS";
            return (
              <tr key={i}>
                <td className="mono" style={{ color: "var(--text-secondary)" }}>{formatDate(r.date)}</td>
                <td className="mono">{r.matchup}</td>
                <td className="mono" style={{ color: "var(--text-bright)" }}>{r.pick}</td>
                <td className="mono">{r.odds}</td>
                <td>
                  <span className={`chip ${win ? "chip-win" : loss ? "chip-loss" : "chip-push"}`}>{r.result}</span>
                </td>
                <td className={`mono ${r.pl >= 0 ? "pos" : "neg"}`} style={{ textAlign: "right", fontWeight: 700 }}>
                  {r.pl >= 0 ? "+" : ""}{r.pl.toFixed(1)}U
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "2-digit" }).toUpperCase();
  } catch {
    return iso;
  }
}
