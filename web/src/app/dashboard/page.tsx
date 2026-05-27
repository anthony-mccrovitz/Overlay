"use client";

import { useEffect, useState, useCallback } from "react";

// ── Types ──────────────────────────────────────────────────────────────────────

interface FlatPick {
  pick_id: string;
  date: string;
  sport: string;
  market: string;
  team: string;
  matchup: string;
  direction: string;
  line: number | null;
  odds: number;
  odds_fmt: string;
  sportsbook: string;
  edge_pct: number;
  model_prob: number;
  result: string | null;
  profit: number;
}

interface TodayData {
  date: string;
  count: number;
  picks: FlatPick[];
  potd: FlatPick | null;
  by_sport: Record<string, FlatPick[]>;
}

interface YestData {
  date: string;
  count: number;
  wins: number;
  losses: number;
  pl: number;
  picks: FlatPick[];
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtOdds(o: number): string { return o > 0 ? `+${o}` : `${o}`; }

function impliedProb(odds: number): number {
  if (odds < 0) return (-odds) / (-odds + 100);
  return 100 / (odds + 100);
}

function edgeTier(v: number): "hot" | "high" | "med" | "low" {
  if (v >= 10) return "hot";
  if (v >= 7)  return "high";
  if (v >= 4)  return "med";
  return "low";
}

const SPORT_LABELS: Record<string, string> = {
  mlb: "MLB", nba: "NBA", nhl: "NHL",
  basketball_wnba: "WNBA", wnba: "WNBA",
  soccer: "Soccer", soccer_epl: "Soccer · EPL",
  soccer_spain_la_liga: "Soccer · La Liga",
  soccer_france_ligue_1: "Soccer · Ligue 1",
  soccer_germany_bundesliga: "Soccer · Bundesliga",
  soccer_italy_serie_a: "Soccer · Serie A",
  soccer_usa_mls: "MLS",
  golf_pga: "Golf · PGA", tennis_atp: "Tennis · ATP",
  nascar: "NASCAR", ufc_mma: "UFC/MMA",
};

const MARKET_LABELS: Record<string, string> = {
  moneyline: "ML", f5_total: "F5 O/U", total: "O/U",
  nrfi: "NRFI", spread: "Spread", puck_line: "Puck Line", prop: "Prop",
};

const SECTION_TITLES: Record<string, string> = {
  moneyline: "Moneyline",
  total: "Game Totals",
  f5_total: "F5 Totals",
  nrfi: "NRFI / YRFI",
  puck_line: "Puck Line",
  spread: "Spread / Run Line",
  prop: "Player Props",
};

const MARKET_COLORS: Record<string, string> = {
  moneyline:  "text-[var(--cyan)]",
  total:      "text-[var(--blue)]",
  f5_total:   "text-[var(--indigo)]",
  nrfi:       "text-[var(--amber)]",
  puck_line:  "text-[var(--green)]",
  spread:     "text-[var(--green)]",
  prop:       "text-[var(--purple)]",
};

const MARKET_ORDER = ["moneyline", "puck_line", "spread", "total", "f5_total", "nrfi", "prop"];

function sportLabel(k: string): string {
  return SPORT_LABELS[k] ?? k.replace(/_/g, " ").toUpperCase();
}

function mktLabel(k: string): string {
  return MARKET_LABELS[k] ?? k.replace(/_/g, " ").toUpperCase().slice(0, 8);
}

function sectionTitle(mkt: string): string {
  return SECTION_TITLES[mkt] ?? mkt.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function mktBadgeClass(mkt: string): string {
  switch (mkt) {
    case "moneyline":  return "ml";
    case "f5_total":
    case "total":      return "ou";
    case "nrfi":       return "nrfi";
    case "spread":
    case "puck_line":  return "rl";
    default:           return "prop";
  }
}

function resultClass(r: string | null): string {
  if (!r) return "text-[var(--text-muted)]";
  if (r === "win")  return "text-[var(--green)]";
  if (r === "loss") return "text-[var(--red)]";
  if (r === "push") return "text-[var(--amber)]";
  return "text-[var(--text-muted)]";
}

function resultLabel(r: string | null): string {
  if (!r) return "–";
  return r.charAt(0).toUpperCase() + r.slice(1);
}

// ── Probability bar ────────────────────────────────────────────────────────────

function ProbBar({ model, implied }: { model: number; implied: number }) {
  const [w, setW] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setW(model * 100), 120);
    return () => clearTimeout(t);
  }, [model]);
  const edgeVal = (model - implied) * 100;
  const tier = edgeTier(edgeVal);
  const colorClass = tier === "hot" || tier === "high" ? "high" : "indigo";

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-semibold text-[var(--text-muted)]">AI CONFIDENCE</span>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[var(--text-muted)]">Market {(implied * 100).toFixed(0)}%</span>
          <span className="font-black text-base text-[var(--text-bright)]">{(model * 100).toFixed(1)}%</span>
        </div>
      </div>
      <div className="prob-track">
        <div className={`prob-fill ${colorClass}`} style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}

// ── Pick Card ──────────────────────────────────────────────────────────────────

function PickCard({ pick, featured = false }: { pick: FlatPick; featured?: boolean }) {
  const [open, setOpen] = useState(false);
  const tier = edgeTier(pick.edge_pct);
  const imp  = impliedProb(pick.odds);
  const dir  = pick.direction && pick.direction !== "NAN" ? pick.direction : null;

  return (
    <div
      className={`pick-card ${featured ? "featured" : ""}`}
      onClick={() => setOpen(o => !o)}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <span className={`mkt-badge ${mktBadgeClass(pick.market)}`}>{mktLabel(pick.market)}</span>
          {featured && (
            <span className="text-[9px] font-bold tracking-widest text-[var(--gold)]">★ PICK OF THE DAY</span>
          )}
          {dir && (
            <span className="text-[10px] text-[var(--text-muted)] font-medium">{dir}</span>
          )}
        </div>
        <span className={`edge-badge ${tier}`}>
          {tier === "hot" ? "🔥 " : tier === "high" ? "↑ " : ""}
          +{pick.edge_pct.toFixed(1)}%
        </span>
      </div>

      {/* Body */}
      <div className="px-4 py-4">
        <div className="mb-3">
          <div className="text-lg font-black text-[var(--text-bright)] leading-tight">{pick.team}</div>
          {pick.matchup && pick.matchup !== pick.team && (
            <div className="text-sm text-[var(--text-muted)] mt-0.5">{pick.matchup}</div>
          )}
        </div>
        <ProbBar model={pick.model_prob} implied={imp} />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)] bg-[var(--bg-overlay)]">
        <div className="flex items-center gap-3">
          <span className="text-xl font-black text-[var(--amber)] font-mono">{pick.odds_fmt}</span>
          {pick.sportsbook && (
            <span className="text-[10px] text-[var(--text-muted)] font-medium">
              {pick.sportsbook.toUpperCase()}
            </span>
          )}
        </div>
        <span className="text-[10px] text-[var(--border-hi)]">{open ? "▲" : "▼"}</span>
      </div>

      {/* Expanded */}
      {open && (
        <div
          className="px-4 py-4 border-t border-[var(--border)] grid grid-cols-2 sm:grid-cols-3 gap-4 bg-[var(--bg-panel)]"
          onClick={e => e.stopPropagation()}
        >
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">MODEL PROB</div>
            <div className="text-[var(--indigo)] font-black font-mono">{(pick.model_prob * 100).toFixed(2)}%</div>
          </div>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">IMPLIED PROB</div>
            <div className="text-[var(--text-bright)] font-bold font-mono">{(imp * 100).toFixed(2)}%</div>
          </div>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">EDGE</div>
            <div className="text-[var(--green)] font-bold font-mono">+{pick.edge_pct.toFixed(1)}%</div>
          </div>
          {pick.line != null && (
            <div>
              <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">LINE</div>
              <div className="text-[var(--amber)] font-bold font-mono">{pick.line}</div>
            </div>
          )}
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">SPORTSBOOK</div>
            <div className="text-[var(--text)] font-bold">{pick.sportsbook}</div>
          </div>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">MARKET</div>
            <div className="text-[var(--purple)] font-bold">{sectionTitle(pick.market)}</div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Yesterday Result Row ───────────────────────────────────────────────────────

function ResultRow({ pick }: { pick: FlatPick }) {
  const pnlColor =
    pick.profit > 0 ? "text-[var(--green)]" :
    pick.profit < 0 ? "text-[var(--red)]" :
    "text-[var(--text-muted)]";

  return (
    <div className="flex items-center justify-between py-2 border-b border-[var(--border)] last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className={`mkt-badge ${mktBadgeClass(pick.market)} shrink-0`}>
          {mktLabel(pick.market)}
        </span>
        <span className="text-sm text-[var(--text)] font-medium truncate">{pick.team}</span>
        <span className="text-xs text-[var(--text-muted)] font-mono shrink-0">{pick.odds_fmt}</span>
      </div>
      <div className="flex items-center gap-3 shrink-0 ml-2">
        <span className={`text-xs font-bold ${resultClass(pick.result)}`}>
          {resultLabel(pick.result)}
        </span>
        <span className={`text-sm font-black font-mono ${pnlColor}`}>
          {pick.profit >= 0 ? "+" : ""}{pick.profit.toFixed(2)}u
        </span>
      </div>
    </div>
  );
}

// ── Section wrapper ────────────────────────────────────────────────────────────

function Section({ title, color, count, children }: {
  title: string; color: string; count: number; children: React.ReactNode;
}) {
  if (count === 0) return null;
  const borderClass = color.replace("text-", "border-").replace("]", "/30]");
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <h2 className={`text-sm font-bold ${color}`}>{title}</h2>
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${borderClass} bg-[var(--bg-raised)]`}>
          {count}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{children}</div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [today,    setToday]    = useState<TodayData | null>(null);
  const [yest,     setYest]     = useState<YestData | null>(null);
  const [sport,    setSport]    = useState("all");
  const [mktFilt,  setMktFilt]  = useState("all");
  const [minEdge,  setMinEdge]  = useState(3);
  const [showYest, setShowYest] = useState(false);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState("");
  const [ts,       setTs]       = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    Promise.all([
      fetch("/data/today_picks.json").then(r => { if (!r.ok) throw new Error(`today_picks: ${r.status}`); return r.json(); }),
      fetch("/data/yesterday_results.json").then(r => { if (!r.ok) throw new Error(`yesterday: ${r.status}`); return r.json(); }),
    ])
      .then(([t, y]: [TodayData, YestData]) => {
        setToday(t);
        setYest(y);
        setLoading(false);
        setTs(new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }));
      })
      .catch((e: Error) => { setError(e.message); setLoading(false); });
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Build pick set ──────────────────────────────────────────────────────────

  const allPicks: FlatPick[] = today?.picks ?? [];
  const bySport = today?.by_sport ?? {};
  const sports  = Object.keys(bySport);

  // Active sport slice
  const sportPicks: FlatPick[] = sport === "all" ? allPicks : (bySport[sport] ?? []);

  // Available market filters for current sport slice
  const availMarkets: string[] = [
    "all",
    ...Array.from(new Set(sportPicks.map(p => p.market))),
  ];

  // Apply market + min edge filters, sort by edge desc
  const filteredPicks: FlatPick[] = sportPicks
    .filter(p => mktFilt === "all" || p.market === mktFilt)
    .filter(p => p.edge_pct >= minEdge)
    .sort((a, b) => b.edge_pct - a.edge_pct);

  // Group by market for sectioned display
  const byMarket: Record<string, FlatPick[]> = {};
  for (const p of filteredPicks) {
    if (!byMarket[p.market]) byMarket[p.market] = [];
    byMarket[p.market].push(p);
  }
  const sortedMarkets: string[] = [
    ...MARKET_ORDER.filter(m => byMarket[m]),
    ...Object.keys(byMarket).filter(m => !MARKET_ORDER.includes(m)),
  ];

  // ── Yesterday stats ────────────────────────────────────────────────────────

  const yestPl    = yest?.pl ?? 0;
  const yestWins  = yest?.wins ?? 0;
  const yestLoss  = yest?.losses ?? 0;
  const yestColor = yestPl >= 0 ? "text-[var(--green)]" : "text-[var(--red)]";

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 pb-24 md:pb-8 space-y-6">

      {/* ── Yesterday bar ── */}
      {!loading && yest && (
        <div
          className="rounded-xl border border-[var(--border-hi)] bg-[var(--bg-raised)] px-4 py-3 cursor-pointer select-none"
          onClick={() => setShowYest(v => !v)}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-[10px] font-semibold tracking-widest text-[var(--text-muted)]">
                YESTERDAY · {yest.date}
              </span>
              <span className="text-sm font-bold text-[var(--text)]">
                {yestWins}W–{yestLoss}L
              </span>
              <span className={`text-sm font-black font-mono ${yestColor}`}>
                {yestPl >= 0 ? "+" : ""}{yestPl.toFixed(2)}u
              </span>
              <span className="text-[10px] text-[var(--text-muted)]">
                ({yest.count} picks)
              </span>
            </div>
            <span className="text-[10px] text-[var(--text-muted)] shrink-0">
              {showYest ? "▲ Hide" : "▼ Results"}
            </span>
          </div>

          {showYest && yest.picks.length > 0 && (
            <div className="mt-3 pt-3 border-t border-[var(--border)]">
              {yest.picks.map(p => <ResultRow key={p.pick_id} pick={p} />)}
            </div>
          )}
        </div>
      )}

      {/* ── POTD ── */}
      {!loading && today?.potd && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm font-bold text-[var(--gold)]">★ Pick of the Day</h2>
            <span className="text-[10px] text-[var(--text-muted)]">{today.date}</span>
          </div>
          <PickCard pick={today.potd} featured={true} />
        </div>
      )}

      {/* ── Controls ── */}
      <div className="flex flex-col gap-3">

        {/* Sport tabs */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => { setSport("all"); setMktFilt("all"); }}
            className={`sport-tab ${sport === "all" ? "active" : ""}`}
          >
            All&nbsp;<span className="opacity-60">({allPicks.length})</span>
          </button>
          {sports.map(s => (
            <button
              key={s}
              onClick={() => { setSport(s); setMktFilt("all"); }}
              className={`sport-tab ${sport === s ? "active" : ""}`}
            >
              {sportLabel(s)}&nbsp;
              <span className="opacity-60">({bySport[s]?.length ?? 0})</span>
            </button>
          ))}
        </div>

        {/* Market filter */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {availMarkets.map(m => (
            <button
              key={m}
              onClick={() => setMktFilt(m)}
              className={`text-[11px] font-semibold px-3 py-1 rounded-lg border transition-all ${
                mktFilt === m
                  ? "bg-[var(--bg-overlay)] border-[var(--border-hi)] text-[var(--text-bright)]"
                  : "border-transparent text-[var(--text-muted)] hover:text-[var(--text)]"
              }`}
            >
              {m === "all" ? "All" : mktLabel(m)}
            </button>
          ))}
        </div>

        {/* Min edge slider */}
        <div className="flex items-center gap-4 text-[11px] text-[var(--text-muted)]">
          <label className="flex items-center gap-2 cursor-pointer">
            <span className="font-semibold">MIN EDGE</span>
            <input
              type="range" min={0} max={20} step={1} value={minEdge}
              onChange={e => setMinEdge(Number(e.target.value))}
              className="w-20 accent-[var(--indigo)]"
            />
            <span className="font-bold text-[var(--text-bright)] font-mono w-8">{minEdge}%</span>
          </label>
        </div>
      </div>

      {/* ── Status bar ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {loading ? (
            <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--amber)] live-dot" />
              Loading...
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-dot" />
              {filteredPicks.length} picks shown · {today?.date} · refreshed {ts}
            </div>
          )}
        </div>
        <button
          onClick={load}
          className="text-[11px] text-[var(--indigo)] font-semibold hover:opacity-70 transition-opacity"
        >
          ↻ Refresh
        </button>
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="rounded-xl border border-[var(--red)]/40 bg-[var(--red-dim)] px-4 py-3 text-sm text-[var(--red)]">
          {error}
        </div>
      )}

      {/* ── Skeleton ── */}
      {loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="rounded-2xl border border-[var(--border-hi)] overflow-hidden">
              <div className="h-10 skeleton" />
              <div className="p-4 space-y-3">
                <div className="h-6 w-3/4 skeleton rounded-lg" />
                <div className="h-4 w-1/2 skeleton rounded-lg" />
                <div className="h-3 skeleton rounded-full" />
              </div>
              <div className="h-12 skeleton" />
            </div>
          ))}
        </div>
      )}

      {/* ── Empty state ── */}
      {!loading && !error && filteredPicks.length === 0 && (
        <div className="rounded-2xl border border-[var(--border-hi)] bg-[var(--bg-raised)] px-6 py-12 text-center">
          <div className="text-4xl mb-3">📭</div>
          <div className="text-[var(--text-bright)] font-bold mb-1">No picks match filters</div>
          <div className="text-sm text-[var(--text-muted)]">
            Try lowering the min edge slider or selecting a different market.
          </div>
        </div>
      )}

      {/* ── Picks by market section ── */}
      {!loading && !error && filteredPicks.length > 0 && (
        <div className="space-y-8">
          {sortedMarkets.map(mkt => (
            <Section
              key={mkt}
              title={sectionTitle(mkt)}
              color={MARKET_COLORS[mkt] ?? "text-[var(--text)]"}
              count={byMarket[mkt].length}
            >
              {byMarket[mkt].map(p => <PickCard key={p.pick_id} pick={p} />)}
            </Section>
          ))}
        </div>
      )}

    </div>
  );
}
