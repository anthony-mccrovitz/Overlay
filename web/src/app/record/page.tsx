"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Trophy,
  TrendingUp,
  TrendingDown,
  Target,
  BarChart3,
  Shield,
  Flame,
} from "lucide-react";

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

function StatBlock({
  label,
  value,
  icon: Icon,
  positive,
}: {
  label: string;
  value: string;
  icon: React.ElementType;
  positive?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon
          size={14}
          className={
            positive === undefined
              ? "text-[var(--accent)]"
              : positive
                ? "text-[var(--green)]"
                : "text-[var(--red)]"
          }
        />
        <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider font-medium">
          {label}
        </span>
      </div>
      <div
        className={`text-2xl font-bold font-mono ${
          positive === undefined
            ? "text-[var(--accent)]"
            : positive
              ? "text-[var(--green)]"
              : "text-[var(--red)]"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function BacktestCard({ row, sport }: { row: BacktestRow; sport: "mlb" | "ncaab" }) {
  const year = row.Season || row.Year || 0;
  const acc = row.Accuracy;
  const threshold = sport === "ncaab" ? 0.70 : 0.54;
  const isGood = acc >= threshold;

  return (
    <div className="flex items-center justify-between py-3 border-b border-[var(--border)] last:border-b-0">
      <div className="flex items-center gap-3">
        <span className="text-sm font-mono font-semibold w-12">{year}</span>
        <div className="w-24 h-1.5 rounded-full bg-[var(--bg-overlay)] overflow-hidden">
          <div
            className={`h-full rounded-full prob-bar ${isGood ? "bg-[var(--green)]" : "bg-[var(--amber)]"}`}
            style={{ width: `${acc * 100}%` }}
          />
        </div>
      </div>
      <div className="flex items-center gap-4">
        <span className={`text-sm font-mono font-semibold ${isGood ? "text-[var(--green)]" : ""}`}>
          {(acc * 100).toFixed(1)}%
        </span>
        {row.Lift !== undefined && (
          <span className="text-xs text-[var(--text-muted)] font-mono">
            {row.Lift >= 0 ? "+" : ""}{(row.Lift * 100).toFixed(1)}%
          </span>
        )}
        <span className="text-xs text-[var(--text-muted)]">
          {row.Games?.toLocaleString()} games
        </span>
      </div>
    </div>
  );
}

export default function RecordPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [mlb, setMlb] = useState<BacktestRow[]>([]);
  const [ncaab, setNcaab] = useState<BacktestRow[]>([]);

  useEffect(() => {
    fetch(`${API}/record`).then((r) => r.json()).then((d) => setSummary(d.summary)).catch(() => {});
    fetch(`${API}/backtest/mlb`).then((r) => r.json()).then((d) => setMlb(d.results || [])).catch(() => {});
    fetch(`${API}/backtest/ncaab`).then((r) => r.json()).then((d) => setNcaab(d.results || [])).catch(() => {});
  }, []);

  return (
    <div className="mx-auto max-w-2xl px-4 pt-4 pb-6 md:pt-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Track Record</h1>
        <p className="text-xs text-[var(--text-muted)] mt-0.5">
          Every pick. Every result. Fully transparent.
        </p>
      </div>

      {/* Live record */}
      {summary && (
        <motion.section
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-8"
        >
          <div className="flex items-center gap-2 mb-3">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-dot" />
            <h2 className="text-sm font-semibold">Live Record</h2>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <StatBlock
              label="Record"
              value={`${summary.wins}W-${summary.losses}L`}
              icon={Trophy}
            />
            <StatBlock
              label="Win Rate"
              value={`${(summary.win_rate * 100).toFixed(1)}%`}
              icon={Target}
              positive={summary.win_rate >= 0.52}
            />
            <StatBlock
              label="ROI"
              value={`${summary.roi >= 0 ? "+" : ""}${(summary.roi * 100).toFixed(1)}%`}
              icon={summary.roi >= 0 ? TrendingUp : TrendingDown}
              positive={summary.roi >= 0}
            />
            <StatBlock
              label="Streak"
              value={
                summary.streak > 0
                  ? `${summary.streak}W`
                  : summary.streak < 0
                    ? `${Math.abs(summary.streak)}L`
                    : "—"
              }
              icon={Flame}
              positive={summary.streak > 0}
            />
          </div>

          {summary.settled_picks === 0 && (
            <div className="mt-3 rounded-xl bg-[var(--bg-raised)] border border-[var(--border)] p-3 text-center">
              <div className="text-xs text-[var(--text-muted)]">
                Paper trading in progress. Live picks start when the season opens.
              </div>
            </div>
          )}
        </motion.section>
      )}

      {/* MLB Backtest */}
      {mlb.length > 0 && (
        <motion.section
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="mb-8"
        >
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <span>\u26be</span> MLB Backtest
            </h2>
            <span className="text-[10px] text-[var(--text-muted)] bg-[var(--bg-overlay)] px-2 py-0.5 rounded-full">
              Walk-forward validated
            </span>
          </div>
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] px-4 py-2">
            {mlb.map((r) => (
              <BacktestCard key={r.Season} row={r} sport="mlb" />
            ))}
          </div>
        </motion.section>
      )}

      {/* NCAAB Backtest */}
      {ncaab.length > 0 && (
        <motion.section
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="mb-8"
        >
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <span>\ud83c\udfc0</span> NCAAB Tournament Backtest
            </h2>
            <span className="text-[10px] text-[var(--text-muted)] bg-[var(--bg-overlay)] px-2 py-0.5 rounded-full">
              15-year walk-forward
            </span>
          </div>
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] px-4 py-2">
            {ncaab.map((r) => (
              <BacktestCard key={r.Year} row={r} sport="ncaab" />
            ))}
          </div>
          <div className="mt-2 text-center text-xs text-[var(--text-muted)]">
            Average:{" "}
            <span className="font-semibold text-[var(--accent)]">
              {((ncaab.reduce((a, b) => a + b.Accuracy, 0) / ncaab.length) * 100).toFixed(1)}%
            </span>
            {" "}across {ncaab.length} tournaments
          </div>
        </motion.section>
      )}

      {/* Methodology */}
      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] p-5">
          <div className="flex items-center gap-2 mb-2">
            <Shield size={16} className="text-[var(--accent)]" />
            <h2 className="text-sm font-semibold">Verification</h2>
          </div>
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
            All backtests use walk-forward validation — the model only sees data
            available before each prediction. MLB replays 16 seasons (2008-2024)
            game-by-game with expanding training windows. NCAAB trains on prior
            years, tests on the next tournament. Live picks are SHA-256 hashed
            before games start.
          </p>
        </div>
      </motion.section>
    </div>
  );
}
