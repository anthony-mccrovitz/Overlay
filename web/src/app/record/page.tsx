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

interface NrfiStats {
  wins: number;
  losses: number;
  win_rate: number;
  streak: number;
  settled: number;
  pending: number;
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
  nrfi: NrfiStats | null;
  by_market: Record<string, MarketStats>;
  by_sport: Record<string, SportStats>;
  backtest_mlb: { season: number; accuracy: number; high_conf: number; games: number }[];
  recent_picks: RecentPick[];
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

function fmtProfit(p: number) {
  return `${p >= 0 ? "+" : ""}${p.toFixed(2)}u`;
}

function fmtRoi(r: number) {
  return `${r >= 0 ? "+" : ""}${(r * 100).toFixed(1)}%`;
}

function fmtOdds(o: number | null) {
  if (o == null) return "—";
  return o > 0 ? `+${o}` : `${o}`;
}

const MARKETS: { key: string; label: string }[] = [
  { key: "moneyline", label: "Moneyline" },
  { key: "spread",    label: "Spread" },
  { key: "total",     label: "Totals" },
  { key: "nrfi",      label: "NRFI" },
  { key: "prop",      label: "Props" },
];

export default function RecordPage() {
  const [data, setData] = useState<StatsData | null>(null);

  useEffect(() => {
    fetch("/api/record").then(r => r.json()).then(setData).catch(() => {});
  }, []);

  const s = data?.summary;
  const streak = s?.streak ?? 0;

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

      {/* ── Composite record ── */}
      {s && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--cyan)]">▌ OVERALL RECORD</span>
            <span className="ml-2 text-[9px] text-[var(--text-muted)]">{s.settled} settled · {s.pending} pending</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 border-t border-[var(--border-hi)] divide-x divide-y sm:divide-y-0 divide-[var(--border-hi)]">
            <StatCell
              label="RECORD"
              value={`${s.wins}W-${s.losses}L`}
              sub={s.pushes > 0 ? `${s.pushes} push` : undefined}
              color="text-[var(--text-bright)]"
            />
            <StatCell
              label="WIN RATE"
              value={`${(s.win_rate * 100).toFixed(1)}%`}
              sub="breakeven ~52.4%"
              color={s.win_rate >= 0.524 ? "text-[var(--green)]" : s.win_rate < 0.48 ? "text-[var(--red)]" : "text-[var(--text-bright)]"}
            />
            <StatCell
              label="UNITS P/L"
              value={fmtProfit(s.units_profit)}
              sub={`ROI ${fmtRoi(s.roi)}`}
              color={s.units_profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}
            />
            <StatCell
              label="STREAK"
              value={streak > 0 ? `${streak}W` : streak < 0 ? `${Math.abs(streak)}L` : "—"}
              sub="current run"
              color={streak > 0 ? "text-[var(--green)]" : streak < 0 ? "text-[var(--red)]" : "text-[var(--text-muted)]"}
            />
          </div>
        </div>
      )}

      {/* ── Model Health ── */}
      {data?.by_market && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--indigo)]">▌ MODEL HEALTH</span>
            <span className="ml-2 text-[9px] text-[var(--text-muted)]">ROI = process quality proxy · CLV is ground truth</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 divide-x divide-y divide-[var(--border-hi)] border-t border-[var(--border-hi)]">
            {[
              { key: "total",     label: "Totals",    tier: "TIER 1", research: "Weather + Voulgaris" },
              { key: "moneyline", label: "Moneyline", tier: "TIER 2", research: "Bias-fixed Elo" },
              { key: "prop",      label: "Props",     tier: "SHADOW", research: "Incubating (50+ needed)" },
              { key: "nrfi",      label: "NRFI",      tier: "SHADOW", research: "No peer review yet" },
              { key: "spread",    label: "Spread",    tier: "PAUSED", research: "Vig kills edge" },
            ].map(({ key, label, tier, research }) => {
              const m = data.by_market[key];
              const roi = m?.roi ?? null;
              const isGreen  = roi != null && roi > 0.05;
              const isYellow = roi != null && roi >= -0.05 && roi <= 0.05;
              const isRed    = roi != null && roi < -0.05;
              const tierColor =
                tier === "TIER 1" ? "text-[var(--cyan)] border-[var(--indigo)]/40 bg-[var(--indigo)]/10" :
                tier === "TIER 2" ? "text-[var(--amber)] border-[var(--amber)]/40 bg-[var(--amber)]/10" :
                tier === "SHADOW" ? "text-[var(--text-muted)] border-[var(--border-hi)] bg-[var(--bg-overlay)]" :
                "text-[var(--red)] border-[var(--red)]/40 bg-[var(--red)]/10";
              return (
                <div key={key} className="px-3 py-3">
                  <div className="flex items-center gap-1.5 mb-2">
                    <span className={`text-[8px] font-bold tracking-widest px-1.5 py-px border rounded ${tierColor}`}>{tier}</span>
                  </div>
                  <div className="text-[11px] font-bold text-[var(--text-bright)] mb-1">{label}</div>
                  {m && m.total > 0 ? (
                    <>
                      <div className="text-[10px] font-mono font-semibold text-[var(--text-secondary)]">{m.wins}-{m.losses}</div>
                      <div className={`text-[11px] font-bold font-mono mt-0.5 ${isGreen ? "text-[var(--green)]" : isRed ? "text-[var(--red)]" : isYellow ? "text-[var(--amber)]" : "text-[var(--text-muted)]"}`}>
                        {roi != null ? fmtRoi(roi) : "—"}
                      </div>
                    </>
                  ) : (
                    <div className="text-[10px] text-[var(--text-muted)]">No data</div>
                  )}
                  <div className="text-[8px] text-[var(--text-muted)] mt-1.5 leading-tight">{research}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── By market ── */}
      {data?.by_market && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--amber)]">▌ BY MARKET</span>
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
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">TOTAL</th>
                </tr>
              </thead>
              <tbody>
                {MARKETS.map(({ key, label }) => {
                  const m = data.by_market[key];
                  if (!m || m.total === 0) return null;
                  const nonPush = m.wins + m.losses;
                  return (
                    <tr key={key} className="t-row border-b border-[var(--border)] last:border-0">
                      <td className="px-3 py-2 text-[11px] font-medium text-[var(--text-secondary)]">{label}</td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-bright)]">
                        {m.wins}-{m.losses}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">
                        {nonPush > 0
                          ? <span className={m.win_rate >= 0.524 ? "text-[var(--green)]" : "text-[var(--text-secondary)]"}>
                              {(m.win_rate * 100).toFixed(1)}%
                            </span>
                          : <span className="text-[var(--text-muted)]">—</span>
                        }
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">
                        <span className={m.units_profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                          {fmtProfit(m.units_profit)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] hidden sm:table-cell">
                        <span className={m.roi >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                          {fmtRoi(m.roi)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-muted)] hidden md:table-cell">
                        {m.total}
                        {m.pending > 0 ? <span className="text-[var(--amber)]"> +{m.pending}</span> : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── By sport ── */}
      {data?.by_sport && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--blue)]">▌ BY SPORT</span>
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
                </tr>
              </thead>
              <tbody>
                {[{ key: "mlb", label: "MLB" }, { key: "nba", label: "NBA" }].map(({ key, label }) => {
                  const sp = data.by_sport[key];
                  if (!sp || sp.settled === 0) return null;
                  return (
                    <tr key={key} className="t-row border-b border-[var(--border)] last:border-0">
                      <td className="px-3 py-2 text-[11px] font-medium text-[var(--text-secondary)]">{label}</td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-bright)]">{sp.wins}-{sp.losses}</td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">
                        <span className={sp.win_rate >= 0.524 ? "text-[var(--green)]" : "text-[var(--text-secondary)]"}>
                          {(sp.win_rate * 100).toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">
                        <span className={sp.units_profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                          {fmtProfit(sp.units_profit)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] hidden sm:table-cell">
                        <span className={sp.roi >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                          {fmtRoi(sp.roi)}
                        </span>
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
                        }`}>
                          {won ? "W" : lost ? "L" : "P"}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <div className="text-[11px] font-medium text-[var(--text-bright)] truncate max-w-[160px] sm:max-w-none">
                          {p.team ?? "—"}
                        </div>
                        <div className="text-[9px] text-[var(--text-muted)]">
                          {date} · {(p.sport ?? "").toUpperCase()} {p.market ?? ""}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-secondary)] hidden sm:table-cell">
                        {fmtOdds(p.odds)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--cyan)] hidden md:table-cell">
                        {p.edge_pct != null ? `+${p.edge_pct.toFixed(1)}%` : "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] font-bold">
                        {p.profit != null
                          ? <span className={p.profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                              {fmtProfit(p.profit)}
                            </span>
                          : <span className="text-[var(--text-muted)]">—</span>
                        }
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
                    <td className="px-3 py-2 text-right font-mono text-sm font-bold text-[var(--green)]">
                      {(r.accuracy * 100).toFixed(1)}%
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--cyan)] hidden sm:table-cell">
                      {(r.high_conf * 100).toFixed(1)}%
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-muted)] hidden md:table-cell">
                      {r.games.toLocaleString()}
                    </td>
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
