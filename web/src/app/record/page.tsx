"use client";

import { useEffect, useState } from "react";

interface Summary {
  total_picks: number;
  settled: number;
  pending: number;
  wins: number;
  losses: number;
  pushes: number;
  win_rate: number;
  units_profit: number;
  roi: number;
  streak: number;
}

interface MarketStats {
  wins: number;
  losses: number;
  pushes: number;
  win_rate: number;
  units_profit: number;
  roi: number;
  total: number;
  pending: number;
}

interface SportStats {
  wins: number;
  losses: number;
  win_rate: number;
  units_profit: number;
  roi: number;
  settled: number;
  pending: number;
}

interface AlgoEntry {
  status: string; // "live" | "incubating" | "retired"
  tier: string;   // "t1" | "t2" | "shadow" | "paused"
  label: string;
}

interface RecentPick {
  date: string | null;
  sport: string | null;
  market: string | null;
  team: string | null;
  matchup: string | null;
  odds: number | null;
  result: string | null;
  profit: number | null;
  edge_pct: number | null;
}

interface StatsData {
  updated_at: string | null;
  summary: Summary;
  by_market: Record<string, MarketStats>;
  by_sport: Record<string, SportStats>;
  algo_status: Record<string, AlgoEntry>;
  backtest_mlb: { season: number; accuracy: number; high_conf: number; games: number }[];
  recent_picks: RecentPick[];
}

// ── Display helpers ────────────────────────────────────────────────────────────

const SPORT_LABELS: Record<string, string> = {
  mlb: "MLB",
  nba: "NBA",
  nhl: "NHL",
  baseball_mlb: "MLB",
  basketball_nba: "NBA",
  basketball_wnba: "WNBA",
  icehockey_nhl: "NHL",
  soccer_spain_la_liga: "Soccer · La Liga",
  soccer_italy_serie_a: "Soccer · Serie A",
  soccer_germany_bundesliga: "Soccer · Bundesliga",
  soccer_france_ligue_one: "Soccer · Ligue 1",
  soccer_usa_mls: "Soccer · MLS",
  soccer_conmebol_copa_libertadores: "Soccer · Copa Lib",
  tennis_atp_french_open: "Tennis · French Open",
  tennis_atp_us_open: "Tennis · US Open",
  mma_mixed_martial_arts: "MMA / UFC",
};

const MARKET_LABELS: Record<string, string> = {
  moneyline: "Moneyline",
  spread: "Spread",
  total: "Game Total",
  f5_total: "F5 Total",
  nrfi: "NRFI",
  prop: "Props",
  puck_line: "Puck Line",
  pitcher_strikeouts: "Pitcher Ks",
  player_points: "Player Points",
  player_rebounds: "Player Rebounds",
  player_assists: "Player Assists",
  player_goals: "Player Goals",
  player_shots_on_goal: "Shots on Goal",
  outright: "Outright Winner",
};

function sportLabel(s: string) { return SPORT_LABELS[s] ?? s.replace(/_/g, " ").toUpperCase(); }
function marketLabel(m: string) { return MARKET_LABELS[m] ?? m.replace(/_/g, " "); }

function algoKey(sport: string, market: string) {
  // normalize to match models.py keys e.g. "nba_total"
  const s = sport.replace("baseball_", "").replace("basketball_", "").replace("icehockey_", "");
  return `${s}_${market}`;
}

const TIER_STYLES: Record<string, string> = {
  t1:     "text-[var(--cyan)]   border-[var(--indigo)]/40 bg-[var(--indigo)]/10",
  t2:     "text-[var(--amber)]  border-[var(--amber)]/40  bg-[var(--amber)]/10",
  shadow: "text-[var(--text-muted)] border-[var(--border-hi)] bg-[var(--bg-overlay)]",
  paused: "text-[var(--red)]    border-[var(--red)]/40    bg-[var(--red)]/10",
};

const TIER_LABELS: Record<string, string> = {
  t1:     "T1 PROVEN",
  t2:     "T2 SOUND",
  shadow: "SHADOW",
  paused: "PAUSED",
};

function TierBadge({ tier }: { tier: string }) {
  return (
    <span className={`text-[7px] font-bold tracking-widest px-1.5 py-px border rounded ${TIER_STYLES[tier] ?? TIER_STYLES.shadow}`}>
      {TIER_LABELS[tier] ?? tier.toUpperCase()}
    </span>
  );
}

function StatCell({ label, value, sub, color = "text-[var(--cyan)]" }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="px-4 py-3">
      <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">{label}</div>
      <div className={`text-base font-bold font-mono ${color}`}>{value}</div>
      {sub && <div className="text-[9px] text-[var(--text-muted)] mt-0.5">{sub}</div>}
    </div>
  );
}

function fmtProfit(p: number) { return `${p >= 0 ? "+" : ""}${p.toFixed(2)}u`; }
function fmtRoi(r: number)    { return `${r >= 0 ? "+" : ""}${(r * 100).toFixed(1)}%`; }
function fmtOdds(o: number | null) {
  if (o == null) return "—";
  return o > 0 ? `+${o}` : `${o}`;
}

export default function RecordPage() {
  const [data, setData] = useState<StatsData | null>(null);

  useEffect(() => {
    fetch("/api/record").then(r => r.json()).then(setData).catch(() => {});
  }, []);

  const s = data?.summary;
  const streak = s?.streak ?? 0;
  const algoStatus = data?.algo_status ?? {};

  // All sports with graded card picks, sorted by P/L desc
  const sportRows = Object.entries(data?.by_sport ?? {})
    .filter(([, sp]) => sp.settled > 0)
    .sort((a, b) => b[1].units_profit - a[1].units_profit);

  // All markets with graded card picks, sorted by P/L desc
  const marketRows = Object.entries(data?.by_market ?? {})
    .filter(([, m]) => (m.wins + m.losses) > 0)
    .sort((a, b) => b[1].units_profit - a[1].units_profit);

  // Build algo health rows: cross-reference by_sport × by_market with algo_status
  // Group by sport, show each market within it
  const algoRows: { sport: string; market: string; stats: MarketStats | null; algo: AlgoEntry | null }[] = [];
  // live algos first, then shadow, then paused
  const tierOrder = ["t1", "t2", "shadow", "paused"];
  const sortedAlgos = Object.entries(algoStatus).sort((a, b) => {
    const ta = tierOrder.indexOf(a[1].tier);
    const tb = tierOrder.indexOf(b[1].tier);
    return ta - tb;
  });

  return (
    <div className="max-w-4xl mx-auto px-3 py-4 space-y-3 pb-20 md:pb-4">

      {/* ── Header ── */}
      <div className="border border-[var(--border-hi)] bg-[var(--bg-panel)] px-4 py-3 flex items-center justify-between">
        <div>
          <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-0.5">CHEFTONYBETS</div>
          <div className="text-sm font-bold text-[var(--text-bright)]">FULL TRACK RECORD</div>
        </div>
        <div className="text-right text-[9px] text-[var(--text-muted)]">
          {data?.updated_at && (
            <div>UPDATED {new Date(data.updated_at).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</div>
          )}
          <div className="mt-0.5 flex items-center gap-1.5 justify-end">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-dot inline-block" />
            <span className="text-[var(--green)]">GRADED DAILY</span>
          </div>
        </div>
      </div>

      {/* ── Overall Record ── */}
      {s && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--cyan)]">▌ OVERALL RECORD</span>
            <span className="ml-2 text-[9px] text-[var(--text-muted)]">{s.settled} settled · {s.pending} pending</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 border-t border-[var(--border-hi)] divide-x divide-y sm:divide-y-0 divide-[var(--border-hi)]">
            <StatCell label="RECORD" value={`${s.wins}W-${s.losses}L`}
              sub={s.pushes > 0 ? `${s.pushes} push` : undefined} color="text-[var(--text-bright)]" />
            <StatCell label="WIN RATE" value={`${(s.win_rate * 100).toFixed(1)}%`}
              sub="breakeven ~52.4%"
              color={s.win_rate >= 0.524 ? "text-[var(--green)]" : s.win_rate < 0.48 ? "text-[var(--red)]" : "text-[var(--text-bright)]"} />
            <StatCell label="UNITS P/L" value={fmtProfit(s.units_profit)} sub={`ROI ${fmtRoi(s.roi)}`}
              color={s.units_profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"} />
            <StatCell label="STREAK"
              value={streak > 0 ? `${streak}W` : streak < 0 ? `${Math.abs(streak)}L` : "—"}
              sub="current run"
              color={streak > 0 ? "text-[var(--green)]" : streak < 0 ? "text-[var(--red)]" : "text-[var(--text-muted)]"} />
          </div>
        </div>
      )}

      {/* ── Algo Registry ── */}
      {sortedAlgos.length > 0 && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--indigo)]">▌ ALGO REGISTRY</span>
            <span className="ml-2 text-[9px] text-[var(--text-muted)]">live = on your card · shadow = tracking only · paused = known losing</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--border-hi)]">
                  <th className="px-3 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium">MODEL</th>
                  <th className="px-3 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium">STATUS</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">W-L</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">WIN%</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">P/L</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">ROI</th>
                </tr>
              </thead>
              <tbody>
                {sortedAlgos.map(([key, algo]) => {
                  // Try to find matching stats in by_market (for card picks of this algo)
                  // key = e.g. "nba_total", "mlb_moneyline"
                  const parts = key.split("_");
                  // Find market stats — last segment is usually the market
                  const market = parts[parts.length - 1];
                  const mStats = data?.by_market?.[market] ?? null;
                  const isLive = algo.tier === "t1" || algo.tier === "t2";
                  const isPaused = algo.tier === "paused";

                  if (algo.status === "retired") return null;

                  return (
                    <tr key={key} className={`t-row border-b border-[var(--border)] last:border-0 ${isPaused ? "opacity-50" : ""}`}>
                      <td className="px-3 py-2">
                        <div className="text-[11px] font-medium text-[var(--text-bright)]">{algo.label}</div>
                      </td>
                      <td className="px-3 py-2">
                        <TierBadge tier={algo.tier} />
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-bright)]">
                        {isLive && mStats ? `${mStats.wins}-${mStats.losses}` : <span className="text-[var(--text-muted)]">—</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">
                        {isLive && mStats && (mStats.wins + mStats.losses) > 0 ? (
                          <span className={mStats.win_rate >= 0.524 ? "text-[var(--green)]" : mStats.win_rate < 0.48 ? "text-[var(--red)]" : "text-[var(--text-secondary)]"}>
                            {(mStats.win_rate * 100).toFixed(0)}%
                          </span>
                        ) : <span className="text-[var(--text-muted)]">—</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">
                        {isLive && mStats ? (
                          <span className={mStats.units_profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                            {fmtProfit(mStats.units_profit)}
                          </span>
                        ) : <span className="text-[var(--text-muted)]">shadow</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] hidden sm:table-cell">
                        {isLive && mStats ? (
                          <span className={mStats.roi >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                            {fmtRoi(mStats.roi)}
                          </span>
                        ) : <span className="text-[var(--text-muted)]">—</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── By Sport — dynamic, all sports ── */}
      {sportRows.length > 0 && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--blue)]">▌ BY SPORT</span>
            <span className="ml-2 text-[9px] text-[var(--text-muted)]">card picks only</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--border-hi)]">
                  <th className="px-3 py-1.5 text-left  text-[9px] text-[var(--text-muted)] tracking-widest font-medium">SPORT</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">W-L</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">WIN%</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">UNITS P/L</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">ROI</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">PICKS</th>
                </tr>
              </thead>
              <tbody>
                {sportRows.map(([sport, sp]) => (
                  <tr key={sport} className="t-row border-b border-[var(--border)] last:border-0">
                    <td className="px-3 py-2 text-[11px] font-medium text-[var(--text-secondary)]">{sportLabel(sport)}</td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-bright)]">{sp.wins}-{sp.losses}</td>
                    <td className="px-3 py-2 text-right font-mono text-[11px]">
                      <span className={sp.win_rate >= 0.524 ? "text-[var(--green)]" : sp.win_rate < 0.45 ? "text-[var(--red)]" : "text-[var(--text-secondary)]"}>
                        {(sp.win_rate * 100).toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[11px]">
                      <span className={sp.units_profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                        {fmtProfit(sp.units_profit)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] hidden sm:table-cell">
                      <span className={sp.roi >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>{fmtRoi(sp.roi)}</span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-muted)] hidden md:table-cell">
                      {sp.settled}{sp.pending > 0 ? <span className="text-[var(--amber)]"> +{sp.pending}</span> : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── By Market — dynamic, all markets ── */}
      {marketRows.length > 0 && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--amber)]">▌ BY MARKET</span>
            <span className="ml-2 text-[9px] text-[var(--text-muted)]">card picks only</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--border-hi)]">
                  <th className="px-3 py-1.5 text-left  text-[9px] text-[var(--text-muted)] tracking-widest font-medium">MARKET</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">W-L</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">WIN%</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">UNITS P/L</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">ROI</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">PICKS</th>
                </tr>
              </thead>
              <tbody>
                {marketRows.map(([market, m]) => {
                  const nonPush = m.wins + m.losses;
                  return (
                    <tr key={market} className="t-row border-b border-[var(--border)] last:border-0">
                      <td className="px-3 py-2 text-[11px] font-medium text-[var(--text-secondary)]">{marketLabel(market)}</td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-bright)]">{m.wins}-{m.losses}</td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">
                        {nonPush > 0 ? (
                          <span className={m.win_rate >= 0.524 ? "text-[var(--green)]" : m.win_rate < 0.48 ? "text-[var(--red)]" : "text-[var(--text-secondary)]"}>
                            {(m.win_rate * 100).toFixed(1)}%
                          </span>
                        ) : <span className="text-[var(--text-muted)]">—</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">
                        <span className={m.units_profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                          {fmtProfit(m.units_profit)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] hidden sm:table-cell">
                        <span className={m.roi >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>{fmtRoi(m.roi)}</span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-muted)] hidden md:table-cell">
                        {m.total}{m.pending > 0 ? <span className="text-[var(--amber)]"> +{m.pending}</span> : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Recent picks ── */}
      {data?.recent_picks && data.recent_picks.length > 0 && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--green)]">▌ RECENT PICKS</span>
            <span className="ml-auto text-[9px] text-[var(--text-muted)]">LAST {data.recent_picks.length} SETTLED</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--border-hi)]">
                  <th className="px-3 py-1.5 text-left  text-[9px] text-[var(--text-muted)] tracking-widest font-medium w-6"></th>
                  <th className="px-3 py-1.5 text-left  text-[9px] text-[var(--text-muted)] tracking-widest font-medium">PICK</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">ODDS</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">EDGE</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">P/L</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_picks.map((p, i) => {
                  const won  = p.result === "win";
                  const lost = p.result === "loss";
                  const date = p.date ? p.date.slice(5) : "—";
                  return (
                    <tr key={i} className="t-row border-b border-[var(--border)] last:border-0">
                      <td className="px-3 py-2">
                        <span className={`inline-flex items-center justify-center w-5 h-4 text-[8px] font-bold border ${
                          won  ? "border-[var(--green)] text-[var(--green)]" :
                          lost ? "border-[var(--red)] text-[var(--red)]" :
                                 "border-[var(--border-hi)] text-[var(--text-muted)]"
                        }`}>{won ? "W" : lost ? "L" : "P"}</span>
                      </td>
                      <td className="px-3 py-2">
                        <div className="text-[11px] font-medium text-[var(--text-bright)] truncate max-w-[160px] sm:max-w-none">{p.team ?? "—"}</div>
                        <div className="text-[9px] text-[var(--text-muted)]">
                          {date} · {sportLabel(p.sport ?? "")} · {marketLabel(p.market ?? "")}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-secondary)] hidden sm:table-cell">{fmtOdds(p.odds)}</td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--cyan)] hidden md:table-cell">
                        {p.edge_pct != null ? `+${p.edge_pct.toFixed(1)}%` : "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] font-bold">
                        {p.profit != null ? (
                          <span className={p.profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>{fmtProfit(p.profit)}</span>
                        ) : <span className="text-[var(--text-muted)]">—</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Backtest ── */}
      {data?.backtest_mlb && data.backtest_mlb.length > 0 && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--amber)]">▌ MLB MODEL BACKTEST</span>
            <span className="ml-2 text-[9px] text-[var(--text-muted)] border border-[var(--border-hi)] px-1.5 py-px">WALK-FORWARD · NO LOOK-AHEAD</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--border-hi)]">
                  <th className="px-3 py-1.5 text-left  text-[9px] text-[var(--text-muted)] tracking-widest font-medium">SEASON</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">ACCURACY</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">HIGH CONF</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">GAMES</th>
                </tr>
              </thead>
              <tbody>
                {data.backtest_mlb.map((r) => (
                  <tr key={r.season} className="t-row border-b border-[var(--border)] last:border-0">
                    <td className="px-3 py-2 font-mono text-sm font-semibold text-[var(--text-bright)]">{r.season}</td>
                    <td className="px-3 py-2 text-right font-mono text-sm font-bold text-[var(--green)]">{(r.accuracy * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--cyan)] hidden sm:table-cell">{(r.high_conf * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-muted)] hidden md:table-cell">{r.games.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Verification ── */}
      <div className="border border-[var(--border-hi)]">
        <div className="panel-header">
          <span className="text-[10px] font-bold tracking-widest text-[var(--green)]">▌ VERIFICATION</span>
        </div>
        <div className="px-4 py-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            { label: "WALK-FORWARD CV",    detail: "Expanding training window. Model only sees data it had at prediction time. No look-ahead." },
            { label: "SHA-256 PRE-COMMIT", detail: "Every pick hashed before game starts. Record mathematically impossible to backfill." },
            { label: "CLV TRACKED",        detail: "Closing line value measured on every pick. Industry gold standard for real edge." },
          ].map(({ label, detail }) => (
            <div key={label}>
              <div className="text-[9px] text-[var(--green)] tracking-widest mb-1 font-semibold">{label}</div>
              <div className="text-[10px] text-[var(--text-secondary)] leading-relaxed">{detail}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="text-[9px] text-[var(--text-muted)] text-center py-2 tracking-wider">
        NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+ · UNITS = FLAT 1 UNIT STAKED PER PICK
      </div>
    </div>
  );
}
