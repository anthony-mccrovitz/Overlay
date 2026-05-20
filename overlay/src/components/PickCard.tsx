import type { CustomerPick } from "@/lib/feed";

const MKT_CLASS: Record<string, string> = {
  moneyline: "ml",
  ml: "ml",
  spread: "rl",
  runline: "rl",
  run_line: "rl",
  puckline: "rl",
  total: "ou",
  totals: "ou",
  prop: "prop",
  nrfi: "nrfi",
};

const MKT_LABEL: Record<string, string> = {
  moneyline: "MONEYLINE",
  ml: "MONEYLINE",
  spread: "SPREAD",
  runline: "RUN LINE",
  run_line: "RUN LINE",
  puckline: "PUCK LINE",
  total: "TOTAL",
  totals: "TOTAL",
  prop: "PROP",
  nrfi: "NRFI",
};

export function PickCard({ pick }: { pick: CustomerPick }) {
  const key = (pick.market || "").toLowerCase();
  const cls = MKT_CLASS[key] || "ou";
  const label = MKT_LABEL[key] || (pick.market || "PICK").toUpperCase();
  const result = (pick.result || "pending").toLowerCase();
  const resultColor =
    result === "win" ? "var(--green-hi)" :
    result === "loss" ? "var(--red-hi)" :
    result === "push" ? "var(--text-secondary)" :
    "var(--text-muted)";

  return (
    <div className={`pick-card ${cls}`}>
      <div className="pc-head">
        <span className={`mkt-badge ${cls}`}>{label}</span>
        <span className="mono" style={{ fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.08em" }}>
          {pick.sportsbook ? pick.sportsbook.toUpperCase() : ""}
        </span>
      </div>

      <div className="pc-body">
        <div style={{ fontSize: 11, color: "var(--text-muted)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 6 }}>
          {pick.matchup}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 14 }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--text-bright)", letterSpacing: "-0.01em", lineHeight: 1.15 }}>
            {pick.selection}
          </div>
          <div className="odds-chip">{pick.odds}</div>
        </div>
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.55 }}>
          {pick.reasoning}
        </div>
      </div>

      <div className="pc-foot">
        <span className="mono" style={{ letterSpacing: "0.06em" }}>
          STAKE <strong style={{ color: "var(--text-secondary)", marginLeft: 4 }}>{pick.stake}</strong>
        </span>
        <span className="mono" style={{ color: resultColor, fontWeight: 700, letterSpacing: "0.08em" }}>
          {result.toUpperCase()}
        </span>
      </div>
    </div>
  );
}
