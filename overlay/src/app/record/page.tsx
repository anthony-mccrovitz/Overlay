import { readFeed } from "@/lib/feed";

export const dynamic = "force-dynamic";

export default async function RecordPage() {
  const feed = await readFeed();
  const r = feed?.record;

  if (!r) {
    return <p style={{ color: "var(--text-secondary)" }}>Record will appear here once stats are available.</p>;
  }

  const wlt = r.pushes ? `${r.wins}–${r.losses}–${r.pushes}` : `${r.wins}–${r.losses}`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 32 }}>
      <div>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--text-bright)", margin: 0 }}>
          The public record
        </h1>
        <p style={{ fontSize: 14, color: "var(--text-secondary)", marginTop: 8, maxWidth: 600 }}>
          Every card pick is logged the moment it&apos;s posted and graded the moment it settles.
          No edits, no removals. This is the full ledger.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16 }}>
        <StatCard label="Settled picks" value={String(r.settled)} />
        <StatCard label="Record" value={wlt} />
        <StatCard
          label="Units"
          value={`${r.units >= 0 ? "+" : ""}${r.units.toFixed(2)}u`}
          color={r.units >= 0 ? "var(--green-hi)" : "var(--red)"}
        />
        <StatCard
          label="ROI"
          value={`${r.roi_pct >= 0 ? "+" : ""}${r.roi_pct.toFixed(2)}%`}
          color={r.roi_pct >= 0 ? "var(--green-hi)" : "var(--red)"}
        />
        <StatCard
          label="Streak"
          value={r.streak > 0 ? `W${r.streak}` : r.streak < 0 ? `L${Math.abs(r.streak)}` : "—"}
        />
      </div>

      <p style={{ fontSize: 12, color: "var(--text-muted)" }}>
        Stats updated: {new Date(feed!.updated_at).toLocaleString()}
      </p>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="stat-card">
      <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: color || "var(--text-bright)", marginTop: 6 }}>{value}</div>
    </div>
  );
}
