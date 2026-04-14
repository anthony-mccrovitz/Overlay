"use client";

import { useEffect, useState } from "react";

const API = "/api";

interface Summary {
  total_picks: number;
  settled_picks: number;
  wins: number;
  losses: number;
  win_rate: number;
  units_staked: number;
  units_profit: number;
  roi: number;
  streak: number;
}

interface BacktestRow {
  Season?: number;
  Year?: number;
  Accuracy: number;
  Games?: number;
  BrierScore?: number;
  LogLoss?: number;
  HomeBaseline?: number;
  Lift?: number;
}

function StatCell({ label, value, color = "text-[var(--cyan)]" }: { label: string; value: string; color?: string }) {
  return (
    <div className="border-r border-[var(--border-hi)] last:border-r-0 px-4 py-3">
      <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">{label}</div>
      <div className={`text-lg font-bold font-mono ${color}`}>{value}</div>
    </div>
  );
}

export default function RecordPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [mlb, setMlb]         = useState<BacktestRow[]>([]);
  const [ncaab, setNcaab]     = useState<BacktestRow[]>([]);

  useEffect(() => {
    fetch(`${API}/record`).then(r => r.json()).then(d => setSummary(d.summary)).catch(() => {});
    fetch(`${API}/backtest/mlb`).then(r => r.json()).then(d => setMlb(d.results || [])).catch(() => {});
    fetch(`${API}/backtest/ncaab`).then(r => r.json()).then(d => setNcaab(d.results || [])).catch(() => {});
  }, []);

  const avgMlb  = mlb.length  ? (mlb.reduce((a, r)  => a + r.Accuracy, 0) / mlb.length * 100).toFixed(1)  : null;
  const avgNcaab= ncaab.length? (ncaab.reduce((a, r) => a + r.Accuracy, 0) / ncaab.length * 100).toFixed(1): null;

  return (
    <div className="max-w-5xl mx-auto px-3 py-4 space-y-px">

      {/* Header */}
      <div className="border border-[var(--border-hi)] bg-[var(--bg-panel)] px-4 py-3 flex items-center justify-between">
        <div>
          <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-0.5">EDGEFINDER</div>
          <div className="text-sm font-bold text-[var(--text-bright)]">TRACK RECORD</div>
        </div>
        <div className="text-right text-[9px] text-[var(--text-muted)]">
          <div>METHODOLOGY: WALK-FORWARD CV</div>
          <div className="mt-0.5 flex items-center gap-1.5 justify-end">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-dot inline-block" />
            <span className="text-[var(--green)]">VERIFICATION ACTIVE</span>
          </div>
        </div>
      </div>

      {/* Live record */}
      {summary && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--cyan)]">▌ LIVE RECORD</span>
            <span className="ml-2 text-[9px] text-[var(--text-muted)]">{summary.settled_picks} settled</span>
            {summary.settled_picks === 0 && (
              <span className="ml-auto text-[9px] text-[var(--amber)]">PAPER TRADING — PRE-SEASON</span>
            )}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 border-t border-[var(--border-hi)]">
            <StatCell
              label="RECORD"
              value={`${summary.wins}W-${summary.losses}L`}
            />
            <StatCell
              label="WIN RATE"
              value={`${(summary.win_rate * 100).toFixed(1)}%`}
              color={summary.win_rate >= 0.52 ? "text-[var(--green)]" : "text-[var(--red)]"}
            />
            <StatCell
              label="ROI"
              value={`${summary.roi >= 0 ? "+" : ""}${(summary.roi * 100).toFixed(1)}%`}
              color={summary.roi >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}
            />
            <StatCell
              label="STREAK"
              value={summary.streak > 0 ? `${summary.streak}W` : summary.streak < 0 ? `${Math.abs(summary.streak)}L` : "—"}
              color={summary.streak > 0 ? "text-[var(--green)]" : summary.streak < 0 ? "text-[var(--red)]" : "text-[var(--text-muted)]"}
            />
          </div>
        </div>
      )}

      {/* MLB Backtest */}
      {mlb.length > 0 && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--amber)]">▌ MLB BACKTEST</span>
            <span className="ml-2 text-[9px] text-[var(--text-muted)] border border-[var(--border-hi)] px-1.5 py-px">WALK-FORWARD VALIDATED</span>
            {avgMlb && (
              <span className="ml-auto text-[10px] text-[var(--green)] font-bold">AVG: {avgMlb}%</span>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--border-hi)]">
                  <th className="px-3 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium">SEASON</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">ACCURACY</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">VS BASELINE</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">GAMES</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden lg:table-cell">BRIER</th>
                  <th className="px-20 py-1.5 hidden sm:table-cell" />
                </tr>
              </thead>
              <tbody>
                {mlb.map((r) => {
                  const acc = r.Accuracy * 100;
                  const isGood = acc >= 54;
                  return (
                    <tr key={r.Season} className="t-row">
                      <td className="px-3 py-2 font-mono text-sm font-semibold text-[var(--text-bright)]">
                        {r.Season}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className={`font-mono text-sm font-bold ${isGood ? "text-[var(--green)]" : "text-[var(--amber)]"}`}>
                          {acc.toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-secondary)] hidden sm:table-cell">
                        {r.Lift !== undefined
                          ? <span className={r.Lift >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                              {r.Lift >= 0 ? "+" : ""}{(r.Lift * 100).toFixed(1)}%
                            </span>
                          : r.HomeBaseline !== undefined
                            ? <span className="text-[var(--text-muted)]">base: {(r.HomeBaseline * 100).toFixed(1)}%</span>
                            : "—"
                        }
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-muted)] hidden md:table-cell">
                        {r.Games?.toLocaleString() ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-muted)] hidden lg:table-cell">
                        {r.BrierScore?.toFixed(4) ?? "—"}
                      </td>
                      <td className="px-3 py-2 hidden sm:table-cell">
                        <div className="w-full max-w-[120px] h-1 bg-[var(--bg-overlay)] overflow-hidden ml-auto">
                          <div
                            className={`h-full prob-bar ${isGood ? "bg-[var(--green)]" : "bg-[var(--amber)]"}`}
                            style={{ width: `${Math.min(acc, 100)}%` }}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* NCAAB Backtest */}
      {ncaab.length > 0 && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--purple)]">▌ NCAAB TOURNAMENT BACKTEST</span>
            <span className="ml-2 text-[9px] text-[var(--text-muted)] border border-[var(--border-hi)] px-1.5 py-px">15-YEAR WALK-FORWARD</span>
            {avgNcaab && (
              <span className="ml-auto text-[10px] text-[var(--green)] font-bold">AVG: {avgNcaab}%</span>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--border-hi)]">
                  <th className="px-3 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium">YEAR</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">ACCURACY</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">GAMES</th>
                  <th className="px-20 py-1.5 hidden sm:table-cell" />
                </tr>
              </thead>
              <tbody>
                {ncaab.map((r) => {
                  const acc = r.Accuracy * 100;
                  const isGood = acc >= 70;
                  return (
                    <tr key={r.Year} className="t-row">
                      <td className="px-3 py-2 font-mono text-sm font-semibold text-[var(--text-bright)]">{r.Year}</td>
                      <td className="px-3 py-2 text-right">
                        <span className={`font-mono text-sm font-bold ${isGood ? "text-[var(--green)]" : "text-[var(--amber)]"}`}>
                          {acc.toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-muted)] hidden md:table-cell">
                        {r.Games?.toLocaleString() ?? "—"}
                      </td>
                      <td className="px-3 py-2 hidden sm:table-cell">
                        <div className="w-full max-w-[120px] h-1 bg-[var(--bg-overlay)] overflow-hidden ml-auto">
                          <div className={`h-full prob-bar ${isGood ? "bg-[var(--purple)]" : "bg-[var(--amber)]"}`}
                            style={{ width: `${Math.min(acc, 100)}%` }} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Verification */}
      <div className="border border-[var(--border-hi)]">
        <div className="panel-header">
          <span className="text-[10px] font-bold tracking-widest text-[var(--green)]">▌ VERIFICATION PROTOCOL</span>
        </div>
        <div className="px-4 py-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            { label: "WALK-FORWARD CV", detail: "Expanding training window. No look-ahead bias. Model only sees historical data at prediction time." },
            { label: "SHA-256 PRE-COMMIT", detail: "Every pick is hashed before game start. Track record cannot be retroactively altered or cherry-picked." },
            { label: "CLV TRACKING", detail: "Closing line value measured against where lines close. Gold standard for real-edge verification." },
          ].map(({ label, detail }) => (
            <div key={label}>
              <div className="text-[9px] text-[var(--green)] tracking-widest mb-1 font-semibold">{label}</div>
              <div className="text-[10px] text-[var(--text-secondary)] leading-relaxed">{detail}</div>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
