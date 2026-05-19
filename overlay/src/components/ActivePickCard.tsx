import type { CustomerPick } from "@/lib/feed";

export function ActivePickCard({
  pick,
  sport,
}: {
  pick: CustomerPick;
  sport: string;
}) {
  return (
    <div className="panel panel-hi" style={{ overflow: "hidden" }}>
      <div
        style={{
          background: "var(--accent)",
          padding: "8px 14px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          color: "white",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.1em",
        }}
      >
        <span>ACTIVE PICK · LOCKED TODAY</span>
        <span style={{ opacity: 0.75 }}>#{Math.floor(Math.random() * 8999 + 1000)}-X</span>
      </div>
      <div style={{ padding: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            marginBottom: 6,
          }}
        >
          <div>
            <div style={{ fontSize: 26, fontWeight: 800, color: "var(--text-bright)", letterSpacing: "-0.01em" }}>
              {pick.matchup}
            </div>
            <div className="label-muted" style={{ marginTop: 4 }}>
              {sport} · {pick.sportsbook}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="label-muted">Pick</div>
            <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: "var(--text-bright)", marginTop: 2 }}>
              {pick.selection}
            </div>
          </div>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            gap: 16,
            marginTop: 20,
            paddingTop: 16,
            borderTop: "1px solid var(--border)",
          }}
        >
          <Stat label="Odds" value={pick.odds} />
          <Stat label="Stake" value={pick.stake.replace("u", "U")} />
          <Stat label="Book" value={pick.sportsbook} mono={false} />
        </div>
        <div style={{ marginTop: 20 }}>
          <div className="label-muted" style={{ marginBottom: 6 }}>Model readout</div>
          <p style={{ fontSize: 13, color: "var(--text)", lineHeight: 1.55, margin: 0 }}>
            <span className="mono" style={{ color: "var(--accent)", fontSize: 11, fontWeight: 700, marginRight: 6 }}>
              [ENSEMBLE]
            </span>
            {pick.reasoning}
          </p>
        </div>
        <a
          href={process.env.NEXT_PUBLIC_STRIPE_PAYMENT_LINK || "#pricing"}
          className="btn-primary"
          style={{ marginTop: 22, width: "100%", padding: "14px 16px" }}
          target="_blank"
          rel="noopener noreferrer"
        >
          UNLOCK TODAY&apos;S PICKS
        </a>
      </div>
    </div>
  );
}

function Stat({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="label-muted">{label}</div>
      <div
        className={mono ? "mono" : ""}
        style={{
          fontSize: 16,
          fontWeight: 700,
          color: "var(--text-bright)",
          marginTop: 4,
        }}
      >
        {value}
      </div>
    </div>
  );
}
