"use client";

import { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Zap,
  TrendingUp,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Shield,
  DollarSign,
  Target,
  BarChart3,
  Activity,
} from "lucide-react";

const API = "/api";

interface Game {
  game_id: string;
  home_team: string;
  away_team: string;
  home_win_prob: number;
  home_pitcher: string;
  away_pitcher: string;
  edge_drivers: string[];
}

interface Pick {
  Team: string;
  Opponent: string;
  ModelProb: number;
  ImpliedProb: number;
  Edge: number;
  BestOdds: number;
  Sportsbook: string;
  Market?: string;
  BetSize?: number;
  KellyFraction?: number;
  ExpectedProfit?: number;
}

interface Prop {
  player: string;
  team: string;
  opponent: string;
  market: string;
  line: number;
  direction: string;
  projected: number | null;
  ModelProb: number;
  ImpliedProb: number;
  EdgePct: number;
  BestOdds: number;
  Sportsbook: string;
  label: string;
  BetSize?: number;
  ExpectedProfit?: number;
}

interface NrfiGame {
  direction: string;
  home_team: string;
  away_team: string;
  home_sp: string;
  away_sp: string;
  projected_nrfi: number | null;
  implied_nrfi: number | null;
  EdgePct: number | null;
  BestOdds: number | null;
  Sportsbook: string;
  label: string;
}

interface PicksData {
  sport: string;
  date?: string;
  display_date?: string;
  moneyline: Pick[];
  spread: Pick[];
  totals: Pick[];
  props: Prop[];
  nrfi: NrfiGame[];
  games: Game[];
  message?: string;
}

const SPORTS = [
  { key: "mlb", label: "MLB", emoji: "⚾" },
  { key: "nba", label: "NBA", emoji: "🏀" },
  { key: "ncaab", label: "NCAAB", emoji: "🏈" },
  { key: "nfl", label: "NFL", emoji: "🏈" },
];

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

function teamAbbr(name: string): string {
  const abbrs: Record<string, string> = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
    "Athletics": "OAK",
  };
  return abbrs[name] || name.split(" ").pop()?.slice(0, 3).toUpperCase() || "???";
}

function ProbBar({ prob }: { prob: number }) {
  const pct = Math.round(prob * 100);
  const isStrong = pct >= 58;
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-[var(--text-muted)] w-8 text-right font-mono">{pct}%</span>
      <div className="flex-1 h-1.5 rounded-full bg-[var(--bg-overlay)] overflow-hidden">
        <div
          className={`h-full rounded-full ${isStrong ? "bg-[var(--accent)]" : "bg-[var(--text-muted)]"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function EdgePill({ edge, isRaw = false }: { edge: number; isRaw?: boolean }) {
  // isRaw = edge is already a percentage (like 36.8 for props)
  const pct = isRaw ? edge.toFixed(1) : (edge * 100).toFixed(1);
  const val = isRaw ? edge : edge * 100;
  if (val >= 8)
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold bg-[var(--green-dim)] text-[var(--green)]">
        <Zap size={10} /> +{pct}%
      </span>
    );
  if (val >= 5)
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold bg-[var(--amber-dim)] text-[var(--amber)]">
        +{pct}%
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold bg-[var(--blue-dim)] text-[var(--blue)]">
      +{pct}%
    </span>
  );
}

const MARKET_LABEL: Record<string, string> = { moneyline: "ML", total: "O/U", spread: "RL" };
const MARKET_COLOR: Record<string, string> = {
  moneyline: "bg-[var(--accent-dim)] text-[var(--accent)]",
  total:     "bg-[var(--blue-dim)] text-[var(--blue)]",
  spread:    "bg-[#39FF7820] text-[#39FF78]",
};

function MarketBadge({ market }: { market?: string }) {
  const key = market ?? "moneyline";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wider ${MARKET_COLOR[key] ?? "bg-[var(--bg-overlay)] text-[var(--text-muted)]"}`}>
      {MARKET_LABEL[key] ?? key.toUpperCase()}
    </span>
  );
}

// ── Card types ─────────────────────────────────────────────────────────

function PickCard({ pick, bankroll, index }: { pick: Pick; bankroll: number; index: number }) {
  const odds = pick.BestOdds > 0 ? `+${pick.BestOdds}` : `${pick.BestOdds}`;
  const isTotal = pick.Market === "total";
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04, duration: 0.3 }}
      className={`rounded-2xl border bg-[var(--bg-raised)] p-4 ${isTotal ? "border-[var(--blue)]/20" : "border-[var(--green)]/20"}`}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1 min-w-0 mr-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold">{pick.Team}</span>
            <MarketBadge market={pick.Market} />
          </div>
          <div className="text-[11px] text-[var(--text-muted)] mt-0.5 truncate">{pick.Opponent}</div>
        </div>
        <EdgePill edge={pick.Edge} />
      </div>
      <div className="grid grid-cols-3 gap-3 mt-3">
        <div>
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{isTotal ? "Book %" : "Model"}</div>
          <div className="text-sm font-mono font-semibold text-[var(--accent)]">{(pick.ModelProb * 100).toFixed(1)}%</div>
        </div>
        <div>
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Implied</div>
          <div className="text-sm font-mono font-semibold">{(pick.ImpliedProb * 100).toFixed(1)}%</div>
        </div>
        <div>
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Best Odds</div>
          <div className="text-sm font-mono font-semibold">{odds}</div>
        </div>
      </div>
      {pick.Sportsbook && (
        <div className="mt-2 text-[11px] text-[var(--text-muted)]">Best at {pick.Sportsbook}</div>
      )}
      {bankroll > 0 && pick.BetSize && pick.BetSize > 0 && (
        <div className="mt-3 pt-3 border-t border-[var(--border)] flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
            <DollarSign size={12} />
            Bet ${pick.BetSize.toFixed(0)}
          </div>
          <div className="text-xs font-mono text-[var(--green)]">+${pick.ExpectedProfit?.toFixed(2)} EV</div>
        </div>
      )}
    </motion.div>
  );
}

function PropCard({ prop, bankroll, index }: { prop: Prop; bankroll: number; index: number }) {
  const odds = prop.BestOdds > 0 ? `+${prop.BestOdds}` : `${prop.BestOdds}`;
  const marketLabel = prop.market.replace("pitcher_", "").replace("_", " ");
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04, duration: 0.3 }}
      className="rounded-2xl border border-[#B44FFF]/20 bg-[var(--bg-raised)] p-4"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1 min-w-0 mr-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold">{prop.player}</span>
            <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wider bg-[#B44FFF20] text-[#B44FFF]">
              {prop.direction} {prop.line} {marketLabel}
            </span>
          </div>
          <div className="text-[11px] text-[var(--text-muted)] mt-0.5">{prop.team} vs {prop.opponent}</div>
        </div>
        <EdgePill edge={prop.EdgePct} isRaw />
      </div>
      <div className="grid grid-cols-3 gap-3 mt-3">
        <div>
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Model</div>
          <div className="text-sm font-mono font-semibold text-[#B44FFF]">{(prop.ModelProb * 100).toFixed(1)}%</div>
        </div>
        <div>
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Projected</div>
          <div className="text-sm font-mono font-semibold">{prop.projected != null ? prop.projected.toFixed(1) : "—"}</div>
        </div>
        <div>
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Best Odds</div>
          <div className="text-sm font-mono font-semibold">{odds}</div>
        </div>
      </div>
      {prop.Sportsbook && (
        <div className="mt-2 text-[11px] text-[var(--text-muted)]">Best at {prop.Sportsbook}</div>
      )}
      {bankroll > 0 && prop.BetSize && prop.BetSize > 0 && (
        <div className="mt-3 pt-3 border-t border-[var(--border)] flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
            <DollarSign size={12} />
            Bet ${prop.BetSize.toFixed(0)}
          </div>
          <div className="text-xs font-mono text-[var(--green)]">+${prop.ExpectedProfit?.toFixed(2)} EV</div>
        </div>
      )}
    </motion.div>
  );
}

function NrfiCard({ game, index }: { game: NrfiGame; index: number }) {
  const odds = game.BestOdds != null
    ? (game.BestOdds > 0 ? `+${game.BestOdds}` : `${game.BestOdds}`)
    : null;
  const projPct = game.projected_nrfi != null ? (game.projected_nrfi * 100).toFixed(0) : null;
  const isNrfi = game.direction === "NRFI";
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04, duration: 0.3 }}
      className="rounded-2xl border border-[#B44FFF]/20 bg-[var(--bg-raised)] p-4"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1 min-w-0 mr-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold">{game.away_team} @ {game.home_team}</span>
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wider ${isNrfi ? "bg-[#39FF7820] text-[#39FF78]" : "bg-[var(--red-dim)] text-[var(--red)]"}`}>
              {game.direction}
            </span>
          </div>
          <div className="text-[11px] text-[var(--text-muted)] mt-0.5">
            {game.away_sp} vs {game.home_sp}
          </div>
        </div>
        {game.EdgePct != null
          ? <EdgePill edge={game.EdgePct} isRaw />
          : projPct && (
            <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold bg-[var(--bg-overlay)] text-[var(--text-secondary)]">
              {projPct}% NRFI
            </span>
          )
        }
      </div>
      <div className="grid grid-cols-3 gap-3 mt-3">
        <div>
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Proj NRFI</div>
          <div className="text-sm font-mono font-semibold text-[#B44FFF]">{projPct ? `${projPct}%` : "—"}</div>
        </div>
        <div>
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Implied</div>
          <div className="text-sm font-mono font-semibold">
            {game.implied_nrfi != null ? `${(game.implied_nrfi * 100).toFixed(0)}%` : "—"}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Best Odds</div>
          <div className="text-sm font-mono font-semibold">{odds ?? "—"}</div>
        </div>
      </div>
      {game.Sportsbook && (
        <div className="mt-2 text-[11px] text-[var(--text-muted)]">Best at {game.Sportsbook}</div>
      )}
    </motion.div>
  );
}

function GameCard({ game, index }: { game: Game; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const homeProb = game.home_win_prob;
  const awayProb = 1 - homeProb;
  const fav = homeProb >= 0.5 ? "home" : "away";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.03, duration: 0.3 }}
      className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] overflow-hidden pressable"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <div className={`flex items-center gap-2 flex-1 min-w-0 ${fav === "away" ? "" : "opacity-60"}`}>
              <div className={`flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center text-xs font-bold ${fav === "away" ? "bg-[var(--accent-dim)] text-[var(--accent)]" : "bg-[var(--bg-overlay)] text-[var(--text-muted)]"}`}>
                {teamAbbr(game.away_team)}
              </div>
              <div className="min-w-0">
                <div className="text-sm font-semibold truncate">{game.away_team.split(" ").pop()}</div>
                <div className="text-[11px] text-[var(--text-muted)] truncate">{game.away_pitcher || "TBD"}</div>
              </div>
            </div>
            <div className="text-[11px] text-[var(--text-muted)] font-medium px-2">@</div>
            <div className={`flex items-center gap-2 flex-1 min-w-0 justify-end text-right ${fav === "home" ? "" : "opacity-60"}`}>
              <div className="min-w-0">
                <div className="text-sm font-semibold truncate">{game.home_team.split(" ").pop()}</div>
                <div className="text-[11px] text-[var(--text-muted)] truncate">{game.home_pitcher || "TBD"}</div>
              </div>
              <div className={`flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center text-xs font-bold ${fav === "home" ? "bg-[var(--accent-dim)] text-[var(--accent)]" : "bg-[var(--bg-overlay)] text-[var(--text-muted)]"}`}>
                {teamAbbr(game.home_team)}
              </div>
            </div>
          </div>
        </div>
        <div className="space-y-1.5">
          <ProbBar prob={awayProb} />
          <ProbBar prob={homeProb} />
        </div>
      </div>
      <AnimatePresence>
        {expanded && game.edge_drivers.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3 pt-1 border-t border-[var(--border)]">
              {game.edge_drivers.map((d, i) => (
                <div key={i} className="text-xs text-[var(--text-secondary)] py-0.5 flex items-start gap-1.5">
                  <Target size={10} className="mt-0.5 text-[var(--accent)] flex-shrink-0" />
                  {d}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function SectionHeader({ icon, label, count, color = "text-[var(--accent)]" }: {
  icon: React.ReactNode; label: string; count: number; color?: string;
}) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className={color}>{icon}</span>
      <h2 className="text-base font-semibold">{label}</h2>
      <span className="text-xs text-[var(--text-muted)] bg-[var(--bg-overlay)] px-2 py-0.5 rounded-full">
        {count}
      </span>
    </div>
  );
}

function EmptySection({ label }: { label: string }) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] p-5 text-center">
      <div className="text-xs text-[var(--text-muted)]">No {label} edges found today</div>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3, 4].map((i) => (
        <Skeleton key={i} className="h-32 w-full" />
      ))}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [data, setData] = useState<PicksData | null>(null);
  const [sport, setSport] = useState("mlb");
  const [bankroll, setBankroll] = useState(500);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showBankroll, setShowBankroll] = useState(false);

  const fetchData = useCallback(() => {
    setLoading(true);
    setError("");
    fetch(`${API}/picks/${sport}?bankroll=${bankroll}&min_edge=0.03`)
      .then((r) => r.json())
      .then((d) => { setData(d); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  }, [sport, bankroll]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const today = data?.display_date ?? new Date().toLocaleDateString("en-US", {
    weekday: "short", month: "short", day: "numeric",
  });

  const hasAnyData = data && (
    data.moneyline.length + data.spread.length + data.totals.length +
    data.props.length + data.nrfi.length + data.games.length > 0
  );

  return (
    <div className="mx-auto max-w-2xl px-4 pt-4 pb-6 md:pt-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-1">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Today&apos;s Picks</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-dot" />
            <span className="text-xs text-[var(--text-muted)]">{today}</span>
          </div>
        </div>
        <button
          onClick={fetchData}
          className="p-2 rounded-xl hover:bg-[var(--bg-overlay)] transition-colors pressable"
          title="Refresh"
        >
          <RefreshCw size={18} className={`text-[var(--text-muted)] ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Sport pills + bankroll */}
      <div className="flex items-center gap-2 mt-4 mb-6">
        <div className="flex gap-1 flex-1 overflow-x-auto no-scrollbar">
          {SPORTS.map((s) => (
            <button
              key={s.key}
              onClick={() => setSport(s.key)}
              className={`flex items-center gap-1 px-3 py-1.5 rounded-full text-sm font-medium whitespace-nowrap transition-all pressable ${
                sport === s.key
                  ? "bg-[var(--accent)] text-black"
                  : "bg-[var(--bg-raised)] text-[var(--text-secondary)] border border-[var(--border)]"
              }`}
            >
              <span className="text-xs">{s.emoji}</span>
              {s.label}
            </button>
          ))}
        </div>
        <button
          onClick={() => setShowBankroll(!showBankroll)}
          className={`flex items-center gap-1 px-3 py-1.5 rounded-full text-sm font-medium transition-all pressable border ${
            showBankroll
              ? "border-[var(--accent)] text-[var(--accent)]"
              : "border-[var(--border)] text-[var(--text-secondary)] bg-[var(--bg-raised)]"
          }`}
        >
          <DollarSign size={14} />
          <span className="hidden sm:inline">{bankroll > 0 ? `$${bankroll}` : "Set"}</span>
        </button>
      </div>

      {/* Bankroll input */}
      <AnimatePresence>
        {showBankroll && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="mb-4 p-3 rounded-xl bg-[var(--bg-raised)] border border-[var(--border)]">
              <label className="text-xs text-[var(--text-muted)] mb-1.5 block">Bankroll for Kelly sizing</label>
              <div className="flex items-center gap-2">
                <span className="text-[var(--text-muted)]">$</span>
                <input
                  type="number"
                  value={bankroll}
                  onChange={(e) => setBankroll(Number(e.target.value))}
                  className="flex-1 bg-transparent text-lg font-mono font-semibold outline-none"
                  placeholder="500"
                />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-xl border border-red-500/20 bg-red-500/10 p-4 flex items-start gap-2">
          <Shield size={16} className="text-red-400 mt-0.5 flex-shrink-0" />
          <div>
            <div className="text-sm font-medium text-red-400">Connection Error</div>
            <div className="text-xs text-[var(--text-secondary)] mt-0.5">{error}</div>
          </div>
        </div>
      )}

      {loading && <DashboardSkeleton />}

      {data && !loading && !hasAnyData && (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-raised)] p-8 text-center">
          <div className="text-4xl mb-3">⚾</div>
          <div className="text-sm font-medium mb-1">No games found</div>
          <div className="text-xs text-[var(--text-muted)]">{data.message ?? "Check back tomorrow."}</div>
        </div>
      )}

      {data && !loading && hasAnyData && (
        <div className="space-y-8">

          {/* 1. Moneyline */}
          <section>
            <SectionHeader
              icon={<Zap size={16} />}
              label="Moneyline"
              count={data.moneyline.length}
              color="text-[var(--accent)]"
            />
            {data.moneyline.length > 0
              ? <div className="space-y-3">{data.moneyline.map((p, i) => <PickCard key={i} pick={p} bankroll={bankroll} index={i} />)}</div>
              : <EmptySection label="moneyline" />
            }
          </section>

          {/* 2. Run Line (Spread) */}
          <section>
            <SectionHeader
              icon={<TrendingUp size={16} />}
              label="Run Line"
              count={data.spread.length}
              color="text-[#39FF78]"
            />
            {data.spread.length > 0
              ? <div className="space-y-3">{data.spread.map((p, i) => <PickCard key={i} pick={p} bankroll={bankroll} index={i} />)}</div>
              : <EmptySection label="run line" />
            }
          </section>

          {/* 3. Over / Under */}
          <section>
            <SectionHeader
              icon={<BarChart3 size={16} />}
              label="Over / Under"
              count={data.totals.length}
              color="text-[var(--blue)]"
            />
            {data.totals.length > 0
              ? <div className="space-y-3">{data.totals.map((p, i) => <PickCard key={i} pick={p} bankroll={bankroll} index={i} />)}</div>
              : <EmptySection label="totals" />
            }
          </section>

          {/* 4. Player Props */}
          <section>
            <SectionHeader
              icon={<Activity size={16} />}
              label="Player Props"
              count={data.props.length}
              color="text-[#B44FFF]"
            />
            {data.props.length > 0
              ? <div className="space-y-3">{data.props.map((p, i) => <PropCard key={i} prop={p} bankroll={bankroll} index={i} />)}</div>
              : <EmptySection label="player props" />
            }
          </section>

          {/* 5. NRFI / YRFI */}
          <section>
            <SectionHeader
              icon={<Target size={16} />}
              label="NRFI / YRFI"
              count={data.nrfi.length}
              color="text-[#B44FFF]"
            />
            {data.nrfi.length > 0
              ? <div className="space-y-3">{data.nrfi.map((g, i) => <NrfiCard key={i} game={g} index={i} />)}</div>
              : <EmptySection label="NRFI" />
            }
          </section>

          {/* 6. All Games */}
          {data.games.length > 0 && (
            <section>
              <SectionHeader
                icon={<BarChart3 size={16} />}
                label="All Games"
                count={data.games.length}
                color="text-[var(--text-secondary)]"
              />
              <div className="space-y-2">
                {data.games.map((g, i) => <GameCard key={g.game_id} game={g} index={i} />)}
              </div>
            </section>
          )}

        </div>
      )}
    </div>
  );
}
