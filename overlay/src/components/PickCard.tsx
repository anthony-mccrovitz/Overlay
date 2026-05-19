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

export function PickCard({ pick }: { pick: CustomerPick }) {
  const cls = MKT_CLASS[pick.market.toLowerCase()] || "ou";
  return (
    <div className="pick-card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span className={`mkt-badge ${cls}`}>{pick.market || "pick"}</span>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{pick.sportsbook}</span>
      </div>
      <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 4 }}>{pick.matchup}</div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text-bright)" }}>{pick.selection}</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--green-hi)" }}>{pick.odds}</div>
      </div>
      <div style={{ fontSize: 13, color: "var(--text)", lineHeight: 1.55, marginBottom: 12 }}>{pick.reasoning}</div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-muted)" }}>
        <span>Stake: <strong style={{ color: "var(--text-secondary)" }}>{pick.stake}</strong></span>
        <span style={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>{pick.result}</span>
      </div>
    </div>
  );
}
