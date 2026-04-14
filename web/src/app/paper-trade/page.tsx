"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

interface DaySeries {
  date: string;
  daily_profit: number;
  cumulative_profit: number;
  bets: number;
  wins: number;
}

interface ValidationData {
  total_bets: number;
  wins: number;
  losses: number;
  win_rate: number;
  roi: number;
  total_profit: number;
  total_staked: number;
  binom_p_value: number;
  binom_significant: boolean;
  clv_mean: number;
  clv_picks_with_closing: number;
  clv_significant: boolean;
  roi_ci_lower: number;
  roi_ci_upper: number;
  sharpe_ratio: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  verdict: string;
  verdict_detail: string;
  days_tracked: number;
  bets_needed: number;
  daily_series: DaySeries[];
  recent_picks: any[];
}

function verdictColor(v: string) {
  if (v.includes("CONFIRMED") || v.includes("LIKELY")) return "text-[var(--green)] border-[var(--green)]/30 bg-[var(--green-dim)]";
  if (v.includes("PROMISING") || v.includes("POSITIVE")) return "text-[var(--blue)] border-[var(--blue)]/30 bg-[var(--blue-dim)]";
  if (v.includes("SIGNAL") || v.includes("EARLY")) return "text-[var(--amber)] border-[var(--amber)]/30 bg-[var(--amber-dim)]";
  if (v.includes("NO EDGE")) return "text-[var(--red)] border-[var(--red)]/30 bg-[var(--red-dim)]";
  return "text-[var(--text-muted)] border-[var(--border-hi)] bg-[var(--bg-overlay)]";
}

function PnlChart({ series }: { series: DaySeries[] }) {
  if (series.length === 0) return null;
  const max = Math.max(...series.map(d => d.cumulative_profit), 0);
  const min = Math.min(...series.map(d => d.cumulative_profit), 0);
  const range = max - min || 1;
  const H = 120, W = 500;

  const points = series.map((d, i) => {
    const x = (i / Math.max(series.length - 1, 1)) * W;
    const y = H - ((d.cumulative_profit - min) / range) * H;
    return `${x},${y}`;
  }).join(" ");

  const last = series[series.length - 1]?.cumulative_profit ?? 0;
  const strokeColor = last >= 0 ? "var(--green)" : "var(--red)";
  const zeroY = H - ((0 - min) / range) * H;

  return (
    <div className="border border-[var(--border-hi)]">
      <div className="panel-header">
        <span className="text-[10px] font-bold tracking-widest text-[var(--amber)]">▌ CUMULATIVE P&L</span>
        <span className={`ml-auto text-sm font-bold font-mono ${last >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
          {last >= 0 ? "+" : ""}${last.toFixed(0)}
        </span>
      </div>
      <div className="px-3 pt-2 pb-1">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="none" style={{ height: 120 }}>
          {/* Zero line */}
          {min < 0 && (
            <line x1="0" y1={zeroY} x2={W} y2={zeroY}
              stroke="var(--border-hi)" strokeWidth="1" strokeDasharray="4,4" />
          )}
          {/* Grid lines */}
          {[0.25, 0.5, 0.75].map(f => (
            <line key={f} x1="0" y1={H * f} x2={W} y2={H * f}
              stroke="var(--border)" strokeWidth="0.5" />
          ))}
          {/* PnL line */}
          <polyline fill="none" stroke={strokeColor} strokeWidth="1.5" strokeLinejoin="round" points={points} />
          {/* Fill */}
          <polygon
            fill={strokeColor}
            fillOpacity="0.06"
            points={`0,${H} ${points} ${W},${H}`}
          />
        </svg>
        <div className="flex justify-between text-[9px] text-[var(--text-muted)] mt-1">
          <span>{series[0]?.date}</span>
          <span>{series[series.length - 1]?.date}</span>
        </div>
      </div>
    </div>
  );
}

function StatCell({ label, value, sub, color = "text-[var(--cyan)]" }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="border-r border-b border-[var(--border-hi)] last:border-r-0 px-3 py-3">
      <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-1">{label}</div>
      <div className={`text-base font-bold font-mono ${color}`}>{value}</div>
      {sub && <div className="text-[9px] text-[var(--text-muted)] mt-0.5">{sub}</div>}
    </div>
  );
}

function ProgressBar({ current, target, label, color = "bg-[var(--cyan)]" }: {
  current: number; target: number; label: string; color?: string;
}) {
  const pct = Math.min(current / target, 1) * 100;
  return (
    <div className="border-b border-[var(--border)] last:border-b-0 px-3 py-2.5">
      <div className="flex justify-between text-[9px] text-[var(--text-muted)] mb-1.5">
        <span className="tracking-wider">{label}</span>
        <span className="font-mono">{current} / {target}</span>
      </div>
      <div className="h-1 bg-[var(--bg-overlay)] overflow-hidden">
        <div className={`h-full ${color} prob-bar`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function PaperTradePage() {
  const [data, setData]       = useState<ValidationData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/paper-trade/summary`)
      .then(r => r.json())
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto px-3 py-4 space-y-px">
        {[40, 120, 200, 140].map((h, i) => (
          <div key={i} className="skeleton border border-[var(--border-hi)]" style={{ height: h }} />
        ))}
      </div>
    );
  }

  if (!data || data.total_bets === 0) {
    return (
      <div className="max-w-5xl mx-auto px-3 py-4 space-y-px">
        <div className="border border-[var(--border-hi)] bg-[var(--bg-panel)] px-4 py-3">
          <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-0.5">EDGEFINDER</div>
          <div className="text-sm font-bold text-[var(--text-bright)]">PAPER TRADING VALIDATOR</div>
        </div>
        <div className="border border-[var(--border-hi)] px-4 py-8 text-center">
          <div className="text-[10px] text-[var(--text-muted)] tracking-widest mb-3">STATUS: AWAITING DATA</div>
          <div className="text-sm text-[var(--text-secondary)] mb-3">No paper trades recorded yet.</div>
          <div className="text-[10px] text-[var(--text-muted)] font-mono">
            RUN: python -m src.paper_trade morning
          </div>
        </div>
      </div>
    );
  }

  const betsTarget = data.bets_needed > 0 ? data.total_bets + data.bets_needed : 200;
  const vc = verdictColor(data.verdict);

  return (
    <div className="max-w-5xl mx-auto px-3 py-4 space-y-px">

      {/* Header */}
      <div className="border border-[var(--border-hi)] bg-[var(--bg-panel)] px-4 py-3 flex items-center justify-between">
        <div>
          <div className="text-[9px] text-[var(--text-muted)] tracking-widest mb-0.5">EDGEFINDER · DAY {data.days_tracked}</div>
          <div className="text-sm font-bold text-[var(--text-bright)]">PAPER TRADING VALIDATOR</div>
        </div>
        <span className={`border px-2.5 py-1 text-[10px] font-bold tracking-widest ${vc}`}>
          {data.verdict}
        </span>
      </div>

      {/* Core stats grid */}
      <div className="border border-[var(--border-hi)]">
        <div className="panel-header">
          <span className="text-[10px] font-bold tracking-widest text-[var(--cyan)]">▌ CORE METRICS</span>
          <span className="ml-2 text-[9px] text-[var(--text-muted)]">{data.total_bets} bets tracked</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4">
          <StatCell
            label="RECORD"
            value={`${data.wins}W-${data.losses}L`}
            sub={`${(data.win_rate * 100).toFixed(1)}% (base 53.7%)`}
          />
          <StatCell
            label="ROI"
            value={`${data.roi >= 0 ? "+" : ""}${(data.roi * 100).toFixed(1)}%`}
            sub={`CI: [${(data.roi_ci_lower * 100).toFixed(1)}%, ${(data.roi_ci_upper * 100).toFixed(1)}%]`}
            color={data.roi >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}
          />
          <StatCell
            label="P-VALUE"
            value={data.binom_p_value.toFixed(4)}
            sub={data.binom_significant ? "SIG: p < 0.05" : "NOT YET SIGNIFICANT"}
            color={data.binom_significant ? "text-[var(--green)]" : "text-[var(--amber)]"}
          />
          <StatCell
            label="CLV MEAN"
            value={`${data.clv_mean >= 0 ? "+" : ""}${data.clv_mean.toFixed(1)}c`}
            sub={`${data.clv_picks_with_closing} picks w/ closing`}
            color={data.clv_mean > 0 ? "text-[var(--green)]" : "text-[var(--red)]"}
          />
        </div>
        <div className="grid grid-cols-2 border-t border-[var(--border-hi)]">
          <StatCell
            label="SHARPE RATIO"
            value={data.sharpe_ratio.toFixed(2)}
            sub={data.sharpe_ratio > 1 ? "STRONG" : data.sharpe_ratio > 0.5 ? "MODERATE" : "WEAK"}
            color={data.sharpe_ratio > 0.5 ? "text-[var(--green)]" : "text-[var(--amber)]"}
          />
          <StatCell
            label="MAX DRAWDOWN"
            value={`$${data.max_drawdown.toFixed(0)}`}
            sub={`${(data.max_drawdown_pct * 100).toFixed(1)}% of peak`}
            color="text-[var(--red)]"
          />
        </div>
      </div>

      {/* P&L Chart */}
      <PnlChart series={data.daily_series} />

      {/* Validation progress */}
      <div className="border border-[var(--border-hi)]">
        <div className="panel-header">
          <span className="text-[10px] font-bold tracking-widest text-[var(--amber)]">▌ VALIDATION PROGRESS</span>
        </div>
        <ProgressBar current={data.total_bets} target={betsTarget} label="BETS TRACKED" color="bg-[var(--cyan)]" />
        <ProgressBar current={data.clv_picks_with_closing} target={Math.max(data.total_bets, 50)} label="CLOSING LINES CAPTURED" color="bg-[var(--purple)]" />
        <ProgressBar current={data.days_tracked} target={28} label="DAYS TRACKED" color="bg-[var(--amber)]" />
        <div className="px-3 py-2.5">
          <div className="text-[10px] text-[var(--text-secondary)]">{data.verdict_detail}</div>
        </div>
      </div>

      {/* Recent picks */}
      {data.recent_picks.length > 0 && (
        <div className="border border-[var(--border-hi)]">
          <div className="panel-header">
            <span className="text-[10px] font-bold tracking-widest text-[var(--cyan)]">▌ RECENT PICKS</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--border-hi)]">
                  <th className="px-3 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium">STATUS</th>
                  <th className="px-3 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium">TEAM</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">ODDS</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">MODEL</th>
                  <th className="px-3 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">CLV</th>
                  <th className="px-3 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">BOOK</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_picks.slice(-10).reverse().map((p: any, i: number) => (
                  <tr key={i} className="t-row">
                    <td className="px-3 py-2">
                      {p.won === true  && <span className="text-[var(--green)] font-bold text-xs">WIN</span>}
                      {p.won === false && <span className="text-[var(--red)] font-bold text-xs">LOSS</span>}
                      {p.won === null  && <span className="text-[var(--text-muted)] text-xs">PENDING</span>}
                    </td>
                    <td className="px-3 py-2 text-xs text-[var(--text-bright)] font-medium">{p.team}</td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--text-secondary)]">
                      {p.pick_odds > 0 ? "+" : ""}{p.pick_odds}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-[var(--cyan)] hidden sm:table-cell">
                      {p.model_prob ? `${(p.model_prob * 100).toFixed(0)}%` : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] hidden md:table-cell">
                      {p.clv_cents != null
                        ? <span className={p.clv_cents > 0 ? "text-[var(--green)]" : "text-[var(--red)]"}>
                            {p.clv_cents > 0 ? "+" : ""}{p.clv_cents.toFixed(1)}c
                          </span>
                        : <span className="text-[var(--text-muted)]">—</span>
                      }
                    </td>
                    <td className="px-3 py-2 text-[10px] text-[var(--text-muted)] hidden sm:table-cell">{p.sportsbook || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

    </div>
  );
}
