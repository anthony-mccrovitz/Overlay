"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  TrendingUp,
  TrendingDown,
  Target,
  BarChart3,
  Activity,
  CheckCircle,
  Clock,
  AlertTriangle,
  Zap,
} from "lucide-react";

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

function VerdictBadge({ verdict }: { verdict: string }) {
  const colors: Record<string, string> = {
    "EDGE CONFIRMED": "bg-[var(--green-dim)] text-[var(--green)] border-[var(--green)]",
    "LIKELY EDGE": "bg-[var(--green-dim)] text-[var(--green)] border-[var(--green)]",
    "PROMISING": "bg-[var(--blue-dim)] text-[var(--blue)] border-[var(--blue)]",
    "CAUTIOUSLY POSITIVE": "bg-[var(--blue-dim)] text-[var(--blue)] border-[var(--blue)]",
    "EARLY SIGNAL": "bg-[var(--amber-dim)] text-[var(--amber)] border-[var(--amber)]",
    "TOO EARLY": "bg-[var(--bg-overlay)] text-[var(--text-muted)] border-[var(--border)]",
    "INCONCLUSIVE": "bg-[var(--amber-dim)] text-[var(--amber)] border-[var(--amber)]",
    "NO EDGE DETECTED": "bg-[var(--red-dim)] text-[var(--red)] border-[var(--red)]",
  };
  const cls = colors[verdict] || colors["TOO EARLY"];
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${cls}`}>
      {verdict}
    </span>
  );
}

function Stat({
  label,
  value,
  sub,
  positive,
}: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] p-4">
      <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium mb-1">
        {label}
      </div>
      <div
        className={`text-xl font-bold font-mono ${
          positive === undefined
            ? "text-[var(--accent)]"
            : positive
              ? "text-[var(--green)]"
              : "text-[var(--red)]"
        }`}
      >
        {value}
      </div>
      {sub && <div className="text-[10px] text-[var(--text-muted)] mt-0.5">{sub}</div>}
    </div>
  );
}

function PnlChart({ series }: { series: DaySeries[] }) {
  if (series.length === 0) return null;

  const max = Math.max(...series.map((d) => d.cumulative_profit), 0);
  const min = Math.min(...series.map((d) => d.cumulative_profit), 0);
  const range = max - min || 1;
  const h = 140;
  const w = 100;

  const points = series
    .map((d, i) => {
      const x = (i / Math.max(series.length - 1, 1)) * w;
      const y = h - ((d.cumulative_profit - min) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  const lastProfit = series[series.length - 1]?.cumulative_profit ?? 0;
  const color = lastProfit >= 0 ? "var(--green)" : "var(--red)";

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">
          Cumulative P&L
        </div>
        <div className={`text-sm font-mono font-bold ${lastProfit >= 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
          ${lastProfit >= 0 ? "+" : ""}{lastProfit.toFixed(0)}
        </div>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" preserveAspectRatio="none" style={{ height: 140 }}>
        {min < 0 && (
          <line
            x1="0" y1={h - ((0 - min) / range) * h}
            x2={w} y2={h - ((0 - min) / range) * h}
            stroke="var(--border)" strokeWidth="0.5" strokeDasharray="2,2"
          />
        )}
        <polyline fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" points={points} />
      </svg>
      <div className="flex justify-between text-[9px] text-[var(--text-muted)] mt-1">
        <span>{series[0]?.date}</span>
        <span>{series[series.length - 1]?.date}</span>
      </div>
    </div>
  );
}

function ProgressBar({ current, target, label }: { current: number; target: number; label: string }) {
  const pct = Math.min(current / target, 1) * 100;
  return (
    <div>
      <div className="flex justify-between text-[10px] text-[var(--text-muted)] mb-1">
        <span>{label}</span>
        <span className="font-mono">{current}/{target}</span>
      </div>
      <div className="h-1.5 rounded-full bg-[var(--bg-overlay)] overflow-hidden">
        <div
          className="h-full rounded-full bg-[var(--accent)] prob-bar"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function RecentPick({ pick }: { pick: any }) {
  const won = pick.won;
  const clv = pick.clv_cents;
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[var(--border)] last:border-b-0">
      <div className="flex items-center gap-2">
        {won === true && <CheckCircle size={14} className="text-[var(--green)]" />}
        {won === false && <AlertTriangle size={14} className="text-[var(--red)]" />}
        {won === null && <Clock size={14} className="text-[var(--text-muted)]" />}
        <div>
          <div className="text-sm font-medium">{pick.team}</div>
          <div className="text-[10px] text-[var(--text-muted)]">
            {pick.pick_odds > 0 ? "+" : ""}{pick.pick_odds} @ {pick.sportsbook}
          </div>
        </div>
      </div>
      <div className="text-right">
        {clv !== null && clv !== undefined && (
          <div className={`text-xs font-mono ${clv > 0 ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
            {clv > 0 ? "+" : ""}{clv.toFixed(1)}c CLV
          </div>
        )}
        <div className="text-[10px] text-[var(--text-muted)]">
          {pick.model_prob ? `${(pick.model_prob * 100).toFixed(0)}% model` : ""}
        </div>
      </div>
    </div>
  );
}

export default function PaperTradePage() {
  const [data, setData] = useState<ValidationData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/paper-trade/summary`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="mx-auto max-w-2xl px-4 pt-4 pb-6 md:pt-8">
        <div className="skeleton h-8 w-48 mb-4" />
        <div className="grid grid-cols-2 gap-2">
          {[...Array(4)].map((_, i) => <div key={i} className="skeleton h-20 rounded-2xl" />)}
        </div>
        <div className="skeleton h-40 rounded-2xl mt-4" />
      </div>
    );
  }

  if (!data || data.total_bets === 0) {
    return (
      <div className="mx-auto max-w-2xl px-4 pt-4 pb-6 md:pt-8">
        <h1 className="text-2xl font-bold tracking-tight mb-1">Paper Trading</h1>
        <p className="text-xs text-[var(--text-muted)] mb-6">
          Validating model edge before risking real money.
        </p>
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] p-6 text-center">
          <Activity size={32} className="text-[var(--text-muted)] mx-auto mb-3" />
          <div className="text-sm font-medium mb-1">No paper trades yet</div>
          <div className="text-xs text-[var(--text-muted)] max-w-xs mx-auto">
            Run <code className="bg-[var(--bg-overlay)] px-1.5 py-0.5 rounded text-[var(--accent)]">
            python -m src.paper_trade morning</code> to generate today&apos;s picks
            and start tracking.
          </div>
        </div>
      </div>
    );
  }

  const betsTarget = data.bets_needed > 0 ? data.total_bets + data.bets_needed : 200;

  return (
    <div className="mx-auto max-w-2xl px-4 pt-4 pb-6 md:pt-8">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-bold tracking-tight">Paper Trading</h1>
        <VerdictBadge verdict={data.verdict} />
      </div>
      <p className="text-xs text-[var(--text-muted)] mb-5">
        Day {data.days_tracked} &middot; {data.total_bets} bets tracked &middot; Validating model edge
      </p>

      {/* Core stats */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="grid grid-cols-2 gap-2 mb-4"
      >
        <Stat
          label="Record"
          value={`${data.wins}W-${data.losses}L`}
          sub={`${(data.win_rate * 100).toFixed(1)}% (baseline 53.7%)`}
        />
        <Stat
          label="ROI"
          value={`${data.roi >= 0 ? "+" : ""}${(data.roi * 100).toFixed(1)}%`}
          sub={`CI: [${(data.roi_ci_lower * 100).toFixed(1)}%, ${(data.roi_ci_upper * 100).toFixed(1)}%]`}
          positive={data.roi >= 0}
        />
        <Stat
          label="P-Value"
          value={data.binom_p_value.toFixed(4)}
          sub={data.binom_significant ? "Significant (p < 0.05)" : "Not yet significant"}
          positive={data.binom_significant ? true : undefined}
        />
        <Stat
          label="CLV"
          value={`${data.clv_mean >= 0 ? "+" : ""}${data.clv_mean.toFixed(1)}c`}
          sub={`${data.clv_picks_with_closing} picks with closing lines`}
          positive={data.clv_mean > 0}
        />
      </motion.div>

      {/* P&L Chart */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="mb-4"
      >
        <PnlChart series={data.daily_series} />
      </motion.div>

      {/* Progress + Risk */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="grid grid-cols-2 gap-2 mb-4"
      >
        <Stat
          label="Sharpe Ratio"
          value={data.sharpe_ratio.toFixed(2)}
          sub={data.sharpe_ratio > 1 ? "Strong" : data.sharpe_ratio > 0.5 ? "Moderate" : "Weak"}
          positive={data.sharpe_ratio > 0.5 ? true : data.sharpe_ratio > 0 ? undefined : false}
        />
        <Stat
          label="Max Drawdown"
          value={`$${data.max_drawdown.toFixed(0)}`}
          sub={`${(data.max_drawdown_pct * 100).toFixed(1)}% of peak`}
          positive={false}
        />
      </motion.div>

      {/* Validation progress */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] p-4 mb-4"
      >
        <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium mb-3">
          Validation Progress
        </div>
        <div className="space-y-3">
          <ProgressBar current={data.total_bets} target={betsTarget} label="Bets tracked" />
          <ProgressBar current={data.clv_picks_with_closing} target={Math.max(data.total_bets, 50)} label="Closing lines captured" />
          <ProgressBar current={data.days_tracked} target={28} label="Days tracked" />
        </div>
        <div className="mt-3 text-xs text-[var(--text-secondary)]">
          {data.verdict_detail}
        </div>
      </motion.div>

      {/* Recent picks */}
      {data.recent_picks.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.25 }}
          className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] px-4 py-2"
        >
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium py-2">
            Recent Picks
          </div>
          {data.recent_picks.slice(-10).reverse().map((pick, i) => (
            <RecentPick key={i} pick={pick} />
          ))}
        </motion.div>
      )}
    </div>
  );
}
