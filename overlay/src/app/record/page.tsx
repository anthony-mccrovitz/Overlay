import { readFeed } from "@/lib/feed";
import { EquityCurve } from "@/components/EquityCurve";
import { RecentPicksTable } from "@/components/RecentPicksTable";

export const dynamic = "force-dynamic";

export default async function RecordPage() {
  const feed = await readFeed();
  const r = feed?.record;

  if (!r || !feed) {
    return (
      <div style={containerStyle}>
        <p style={{ color: "var(--text-secondary)" }}>Record will appear here once stats are available.</p>
      </div>
    );
  }

  const wlt = r.pushes ? `${r.wins}–${r.losses}–${r.pushes}` : `${r.wins}–${r.losses}`;

  return (
    <div style={containerStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
        <div>
          <div className="eyebrow">The ledger</div>
          <h1 style={{ fontSize: 30, fontWeight: 800, color: "var(--text-bright)", margin: "6px 0 0", letterSpacing: "-0.015em" }}>
            The public record
          </h1>
          <p style={{ fontSize: 14, color: "var(--text-secondary)", marginTop: 10, maxWidth: 620 }}>
            Every card pick is logged the moment it&apos;s posted and graded the moment it settles.
            No edits, no removals. The losses stay in.
          </p>
        </div>
        <div className="label-muted" style={{ alignSelf: "center" }}>
          updated {new Date(feed.updated_at).toLocaleString()}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12 }}>
        <StatCard label="Settled picks" value={String(r.settled)} />
        <StatCard label="Record" value={wlt} />
        <StatCard
          label="Units"
          value={`${r.units >= 0 ? "+" : ""}${r.units.toFixed(2)}U`}
          color={r.units >= 0 ? "var(--green-hi)" : "var(--red-hi)"}
        />
        <StatCard
          label="ROI / stake"
          value={`${r.roi_pct >= 0 ? "+" : ""}${r.roi_pct.toFixed(2)}%`}
          color={r.roi_pct >= 0 ? "var(--green-hi)" : "var(--red-hi)"}
        />
        <StatCard
          label="Win rate"
          value={`${r.win_rate_pct.toFixed(1)}%`}
        />
        <StatCard
          label="Streak"
          value={r.streak > 0 ? `W${r.streak}` : r.streak < 0 ? `L${Math.abs(r.streak)}` : "—"}
          color={r.streak > 0 ? "var(--green-hi)" : r.streak < 0 ? "var(--red-hi)" : "var(--text-bright)"}
        />
      </div>

      <section>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 10 }}>
          <div>
            <div className="eyebrow">Cumulative equity</div>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: "var(--text-bright)", margin: "4px 0 0" }}>
              Units over time
            </h2>
          </div>
          <div className={`mono ${r.units >= 0 ? "pos" : "neg"}`} style={{ fontSize: 22, fontWeight: 800 }}>
            {r.units >= 0 ? "+" : ""}{r.units.toFixed(2)}U
          </div>
        </div>
        <div className="panel" style={{ padding: 8 }}>
          <EquityCurve data={feed.equity_curve} />
        </div>
      </section>

      <RecentPicksTable rows={feed.recent_picks} />
    </div>
  );
}

const containerStyle: React.CSSProperties = {
  maxWidth: 1100,
  margin: "0 auto",
  padding: "32px 24px",
  display: "flex",
  flexDirection: "column",
  gap: 28,
};

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="panel" style={{ padding: "14px 18px" }}>
      <div className="label-muted">{label}</div>
      <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: color || "var(--text-bright)", marginTop: 4 }}>
        {value}
      </div>
    </div>
  );
}
