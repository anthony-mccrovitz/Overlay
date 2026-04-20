"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

interface Summary {
  total_picks: number;
  settled: number;
  pending: number;
  wins: number;
  losses: number;
  win_rate: number;
  units_profit: number;
  roi: number;
  streak: number;
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
}

interface MarketStats {
  wins: number;
  losses: number;
  win_rate: number;
  units_profit: number;
  roi: number;
}

interface StatsData {
  summary: Summary;
  by_market: Record<string, MarketStats>;
  recent_picks: RecentPick[];
  nrfi: { wins: number; losses: number; win_rate: number } | null;
  updated_at: string | null;
}

function fmt(val: number, sign = true) {
  return `${sign && val >= 0 ? "+" : ""}${val.toFixed(2)}u`;
}

function fmtRoi(val: number) {
  return `${val >= 0 ? "+" : ""}${(val * 100).toFixed(1)}%`;
}

function fmtOdds(odds: number | null) {
  if (odds == null) return "—";
  return odds > 0 ? `+${odds}` : `${odds}`;
}

function fmtDate(d: string | null) {
  if (!d) return "—";
  return d.slice(5); // MM-DD
}

export default function Home() {
  const [stats, setStats] = useState<StatsData | null>(null);

  useEffect(() => {
    fetch("/api/record").then(r => r.json()).then(setStats).catch(() => {});
  }, []);

  const s = stats?.summary;
  const streak = s?.streak ?? 0;
  const streakStr = streak > 0 ? `${streak}W` : streak < 0 ? `${Math.abs(streak)}L` : "—";
  const streakColor = streak > 0 ? "text-[var(--green)]" : streak < 0 ? "text-[var(--red)]" : "text-[var(--text-muted)]";

  const MARKETS = [
    { key: "moneyline", label: "Moneyline" },
    { key: "spread",    label: "Spread" },
    { key: "total",     label: "Totals" },
    { key: "nrfi",      label: "NRFI" },
    { key: "prop",      label: "Props" },
  ] as const;

  return (
    <div className="max-w-4xl mx-auto px-3 py-4 space-y-3 pb-20 md:pb-4">

      {/* ── Hero ── */}
      <div className="border border-[var(--border-hi)] bg-[var(--bg-panel)]">
        <div className="px-4 py-4 flex items-start justify-between gap-4">
          <div>
            <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">
              ML-POWERED SPORTS BETTING PICKS
            </div>
            <div className="text-xl sm:text-2xl font-bold text-[var(--text-bright)] tracking-tight">
              ChefTonyBets
            </div>
            <div className="text-[11px] text-[var(--text-secondary)] mt-0.5">
              Daily picks. Real results. No cherry-picking.
            </div>
          </div>
          <div className="text-right flex-shrink-0">
            <div className="flex items-center gap-1.5 justify-end mb-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-dot inline-block" />
              <span className="text-[9px] text-[var(--green)] tracking-widest">LIVE</span>
            </div>
            {stats?.updated_at && (
              <div className="text-[9px] text-[var(--text-muted)]">
                Updated {new Date(stats.updated_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
              </div>
            )}
          </div>
        </div>

        {/* ── Stat strip ── */}
        {s && (
          <div className="border-t border-[var(--border-hi)] grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0 divide-[var(--border-hi)]">
            <div className="px-4 py-3">
              <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">RECORD</div>
              <div className="text-lg font-bold font-mono text-[var(--text-bright)]">
                {s.wins}<span className="text-[var(--text-muted)] text-sm">W</span>-{s.losses}<span className="text-[var(--text-muted)] text-sm">L</span>
              </div>
              <div className="text-[9px] text-[var(--text-muted)]">{s.settled} settled · {s.pending} pending</div>
            </div>
            <div className="px-4 py-3">
              <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">WIN RATE</div>
              <div className={`text-lg font-bold font-mono ${s.win_rate >= 0.52 ? "text-[var(--green)]" : s.win_rate < 0.48 ? "text-[var(--red)]" : "text-[var(--text-bright)]"}`}>
                {(s.win_rate * 100).toFixed(1)}%
              </div>
              <div className="text-[9px] text-[var(--text-muted)]">breakeven ~52.4%</div>
            </div>
            <div className="px-4 py-3">
              <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">UNITS P/L</div>
              <div className={`text-lg font-bold font-mono ${s.units_profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                {fmt(s.units_profit)}
              </div>
              <div className="text-[9px] text-[var(--text-muted)]">ROI {fmtRoi(s.roi)}</div>
            </div>
            <div className="px-4 py-3">
              <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">STREAK</div>
              <div className={`text-lg font-bold font-mono ${streakColor}`}>{streakStr}</div>
              <div className="text-[9px] text-[var(--text-muted)]">current run</div>
            </div>
          </div>
        )}
      </div>

      {/* ── By market ── */}
      {stats?.by_market && Object.keys(stats.by_market).length > 0 && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--cyan)]">▌ BY MARKET</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--border-hi)]">
                  <th className="px-3 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium">MARKET</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">W-L</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">WIN%</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">P/L</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">ROI</th>
                </tr>
              </thead>
              <tbody>
                {MARKETS.map(({ key, label }) => {
                  const m = stats.by_market[key];
                  if (!m || (m.wins + m.losses) === 0) return null;
                  const profit = m.units_profit;
                  return (
                    <tr key={key} className="t-row border-b border-[var(--border)] last:border-0">
                      <td className="px-3 py-2 text-[11px] font-medium text-[var(--text-secondary)]">{label}</td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-bright)]">
                        {m.wins}-{m.losses}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">
                        <span className={m.win_rate >= 0.524 ? "text-[var(--green)]" : "text-[var(--text-secondary)]"}>
                          {(m.win_rate * 100).toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px]">
                        <span className={profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                          {fmt(profit)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] hidden sm:table-cell">
                        <span className={m.roi >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                          {fmtRoi(m.roi)}
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
      {stats?.recent_picks && stats.recent_picks.length > 0 && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--amber)]">▌ RECENT PICKS</span>
            <span className="ml-auto text-[9px] text-[var(--text-muted)]">LAST {stats.recent_picks.length} SETTLED</span>
          </div>
          <div className="divide-y divide-[var(--border)]">
            {stats.recent_picks.map((p, i) => {
              const won = p.result === "win";
              const lost = p.result === "loss";
              return (
                <div key={i} className="flex items-center gap-2 px-3 py-2 hover:bg-[var(--bg-overlay)] transition-colors">
                  {/* Result badge */}
                  <div className={`flex-shrink-0 w-8 h-5 flex items-center justify-center text-[9px] font-bold tracking-widest border ${
                    won  ? "border-[var(--green)] text-[var(--green)] bg-[var(--green-dim,#0a2a0a)]" :
                    lost ? "border-[var(--red)] text-[var(--red)]" :
                           "border-[var(--border-hi)] text-[var(--text-muted)]"
                  }`}>
                    {won ? "W" : lost ? "L" : "P"}
                  </div>
                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="text-[11px] text-[var(--text-bright)] truncate font-medium">
                      {p.team ?? "—"}
                    </div>
                    <div className="text-[9px] text-[var(--text-muted)]">
                      {fmtDate(p.date)} · {(p.sport ?? "").toUpperCase()} {p.market ?? ""}
                      {p.odds != null ? ` · ${fmtOdds(p.odds)}` : ""}
                    </div>
                  </div>
                  {/* P/L */}
                  {p.profit != null && (
                    <div className={`flex-shrink-0 text-[11px] font-bold font-mono ${p.profit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                      {fmt(p.profit)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── CTA ── */}
      <div className="border border-[var(--border-hi)] bg-[var(--bg-panel)]">
        <div className="px-4 py-4 flex flex-col sm:flex-row items-center gap-3">
          <div className="text-[11px] text-[var(--text-secondary)] text-center sm:text-left">
            Today&apos;s full slate — moneyline, spread, totals, NRFI, and props
          </div>
          <div className="flex items-center gap-2 sm:ml-auto">
            <Link href="/dashboard" className="border border-[var(--cyan)] text-[var(--cyan)] px-4 py-2 text-[11px] font-semibold tracking-widest hover:bg-[var(--cyan-dim)] transition-colors pressable">
              TODAY&apos;S PICKS →
            </Link>
            <Link href="/record" className="border border-[var(--border-hi)] text-[var(--text-secondary)] px-4 py-2 text-[11px] font-semibold tracking-widest hover:bg-[var(--bg-overlay)] transition-colors pressable">
              FULL RECORD
            </Link>
          </div>
        </div>
      </div>

      {/* ── Backtest proof ── */}
      <div className="border border-[var(--border-hi)]">
        <div className="panel-header">
          <span className="text-[10px] font-bold tracking-widest text-[var(--green)]">▌ MODEL BACKTEST — MLB</span>
          <span className="ml-auto text-[9px] text-[var(--text-muted)]">WALK-FORWARD VALIDATED · NO LOOK-AHEAD</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[var(--border-hi)]">
                <th className="px-3 py-1.5 text-left   text-[9px] text-[var(--text-muted)] tracking-widest font-medium">SEASON</th>
                <th className="px-3 py-1.5 text-right  text-[9px] text-[var(--text-muted)] tracking-widest font-medium">ACCURACY</th>
                <th className="px-3 py-1.5 text-right  text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">HIGH CONF</th>
                <th className="px-3 py-1.5 text-right  text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">GAMES</th>
              </tr>
            </thead>
            <tbody>
              {[
                { season: 2025, accuracy: 0.541, high_conf: 0.583, games: 2432 },
                { season: 2024, accuracy: 0.538, high_conf: 0.571, games: 2430 },
              ].map((r) => (
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

      <div className="text-[9px] text-[var(--text-muted)] text-center py-2 tracking-wider">
        NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+ · ALL PROFITS IN UNITS (1u = 1 UNIT STAKED FLAT)
      </div>
    </div>
  );
}
