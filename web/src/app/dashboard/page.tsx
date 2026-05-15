"use client";

import { useEffect, useState, useCallback } from "react";

const API = "/api";

// ── Types ────────────────────────────────────────────────────────────────────

interface Pick {
  Team: string; Opponent: string; ModelProb: number; ImpliedProb: number;
  Edge: number; BestOdds: number; Sportsbook: string; Market?: string;
  BetSize?: number; KellyFraction?: number; ExpectedProfit?: number;
}
interface Prop {
  player: string; team: string; opponent: string; market: string; line: number;
  direction: string; projected: number|null; ModelProb: number; ImpliedProb: number;
  EdgePct: number; BestOdds: number; Sportsbook: string; label: string;
  BetSize?: number; ExpectedProfit?: number;
}
interface NrfiGame {
  direction: string; home_team: string; away_team: string; home_sp: string; away_sp: string;
  projected_nrfi: number|null; implied_nrfi: number|null;
  EdgePct: number|null; BestOdds: number|null; Sportsbook: string; label: string;
}
interface PicksData {
  sport: string; date?: string; display_date?: string;
  moneyline: Pick[]; spread: Pick[]; totals: Pick[];
  props: Prop[]; nrfi: NrfiGame[]; message?: string;
}

const SPORTS = [
  { key: "mlb", label: "MLB" },
  { key: "nba", label: "NBA" },
];

const MARKETS = [
  { key: "all",      label: "All" },
  { key: "moneyline",label: "Moneyline" },
  { key: "spread",   label: "Spread" },
  { key: "totals",   label: "Totals" },
  { key: "props",    label: "Props" },
  { key: "nrfi",     label: "NRFI" },
];

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtOdds(o: number) { return o > 0 ? `+${o}` : `${o}`; }

function edgeTier(v: number): "hot"|"high"|"med"|"low" {
  if (v >= 10) return "hot";
  if (v >= 7)  return "high";
  if (v >= 4)  return "med";
  return "low";
}

function mktBadgeClass(mkt: string) {
  switch (mkt.toLowerCase()) {
    case "moneyline": return "ml";
    case "spread":    return "rl";
    case "total":     return "ou";
    case "prop":      return "prop";
    case "nrfi":      return "nrfi";
    default:          return "ml";
  }
}

function mktLabel(mkt: string) {
  const m: Record<string,string> = { moneyline:"ML", spread:"RL", total:"O/U", prop:"PROP", nrfi:"NRFI" };
  return m[mkt.toLowerCase()] ?? mkt.toUpperCase().slice(0, 4);
}

// ── Probability bar ──────────────────────────────────────────────────────────

function ProbBar({ model, implied, color = "indigo" }: { model: number; implied: number; color?: string }) {
  const [w, setW] = useState(0);
  useEffect(() => { const t = setTimeout(() => setW(model * 100), 120); return () => clearTimeout(t); }, [model]);

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
        <div className={`prob-fill ${color}`} style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}

// ── Pick card ────────────────────────────────────────────────────────────────

function PickCard({ pick, featured = false }: { pick: Pick; featured?: boolean }) {
  const [open, setOpen] = useState(false);
  const edgePct = pick.Edge * 100;
  const tier    = edgeTier(edgePct);
  const mkt     = pick.Market?.toLowerCase() ?? "moneyline";

  return (
    <div className={`pick-card ${featured ? "featured" : ""}`} onClick={() => setOpen(o => !o)}>
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <span className={`mkt-badge ${mktBadgeClass(mkt)}`}>{mktLabel(mkt)}</span>
          {featured && <span className="text-[9px] font-bold tracking-widest text-[var(--gold)]">★ TOP PICK</span>}
        </div>
        <span className={`edge-badge ${tier}`}>
          {tier === "hot" ? "🔥 " : tier === "high" ? "↑ " : ""}
          +{edgePct.toFixed(1)}% edge
        </span>
      </div>

      {/* Main body */}
      <div className="px-4 py-4">
        <div className="mb-3">
          <div className="text-lg font-black text-[var(--text-bright)] leading-tight">{pick.Team}</div>
          <div className="text-sm text-[var(--text-muted)] mt-0.5">vs {pick.Opponent}</div>
        </div>
        <ProbBar model={pick.ModelProb} implied={pick.ImpliedProb} color={tier === "hot" || tier === "high" ? "high" : "indigo"} />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)] bg-[var(--bg-overlay)]">
        <div className="flex items-center gap-3">
          <span className="text-xl font-black text-[var(--amber)] font-mono">{fmtOdds(pick.BestOdds)}</span>
          {pick.Sportsbook && <span className="text-[10px] text-[var(--text-muted)] font-medium">{pick.Sportsbook.toUpperCase()}</span>}
        </div>
        <div className="flex items-center gap-3 text-[10px] text-[var(--text-muted)]">
          {pick.KellyFraction != null && (
            <span>Kelly <span className="text-[var(--cyan)] font-bold">{(pick.KellyFraction*100).toFixed(1)}%</span></span>
          )}
          <span className="text-[var(--border-hi)]">{open ? "▲" : "▼"}</span>
        </div>
      </div>

      {/* Expanded */}
      {open && (
        <div className="px-4 py-4 border-t border-[var(--border)] grid grid-cols-2 sm:grid-cols-4 gap-4 bg-[var(--bg-panel)]" onClick={e => e.stopPropagation()}>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">MODEL PROB</div>
            <div className="text-[var(--indigo)] font-black font-mono">{(pick.ModelProb*100).toFixed(2)}%</div>
          </div>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">IMPLIED PROB</div>
            <div className="text-[var(--text-bright)] font-bold font-mono">{(pick.ImpliedProb*100).toFixed(2)}%</div>
          </div>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">KELLY FRACTION</div>
            <div className="text-[var(--amber)] font-bold font-mono">
              {pick.KellyFraction != null ? `${(pick.KellyFraction*100).toFixed(2)}%` : "N/A"}
            </div>
          </div>
          {pick.BetSize != null && pick.BetSize > 0 && (
            <div>
              <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">KELLY BET</div>
              <div className="text-[var(--green)] font-bold font-mono">
                ${pick.BetSize.toFixed(0)}
                {pick.ExpectedProfit != null && <span className="text-[var(--text-muted)] font-normal ml-1 text-[10px]">+${pick.ExpectedProfit.toFixed(2)} EV</span>}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Prop card ─────────────────────────────────────────────────────────────────

function PropCard({ prop }: { prop: Prop }) {
  const [open, setOpen] = useState(false);
  const tier = edgeTier(prop.EdgePct);
  const mktDisplay = prop.market.replace(/^(pitcher_|batter_)/, "").replace(/_/g, " ").toUpperCase();
  const isOver = prop.direction.toUpperCase() === "OVER";

  return (
    <div className="pick-card" onClick={() => setOpen(o => !o)}>
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <span className="mkt-badge prop">PROP</span>
          <span className="text-[10px] text-[var(--text-muted)]">{mktDisplay}</span>
        </div>
        <span className={`edge-badge ${tier}`}>+{prop.EdgePct.toFixed(1)}% edge</span>
      </div>

      <div className="px-4 py-4">
        <div className="mb-3">
          <div className="text-lg font-black text-[var(--text-bright)] leading-tight">{prop.player}</div>
          <div className="flex items-center gap-2 mt-1">
            <span className={`text-sm font-bold ${isOver ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
              {prop.direction} {prop.line}
            </span>
            <span className="text-xs text-[var(--text-muted)]">{prop.team} vs {prop.opponent}</span>
          </div>
        </div>
        <ProbBar model={prop.ModelProb} implied={prop.ImpliedProb} />
      </div>

      <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)] bg-[var(--bg-overlay)]">
        <div className="flex items-center gap-3">
          <span className="text-xl font-black text-[var(--amber)] font-mono">{fmtOdds(prop.BestOdds)}</span>
          {prop.Sportsbook && <span className="text-[10px] text-[var(--text-muted)]">{prop.Sportsbook.toUpperCase()}</span>}
        </div>
        {prop.projected != null && (
          <span className="text-[10px] text-[var(--text-muted)]">
            Proj <span className="text-[var(--cyan)] font-bold">{prop.projected.toFixed(1)}</span>
          </span>
        )}
      </div>

      {open && (
        <div className="px-4 py-4 border-t border-[var(--border)] grid grid-cols-2 sm:grid-cols-3 gap-4 bg-[var(--bg-panel)]" onClick={e => e.stopPropagation()}>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">MODEL PROB</div>
            <div className="text-[var(--indigo)] font-black font-mono">{(prop.ModelProb*100).toFixed(2)}%</div>
          </div>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">IMPLIED PROB</div>
            <div className="text-[var(--text-bright)] font-bold font-mono">{(prop.ImpliedProb*100).toFixed(2)}%</div>
          </div>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">MARKET</div>
            <div className="text-[var(--purple)] font-bold">{mktDisplay}</div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── NRFI card ─────────────────────────────────────────────────────────────────

function NrfiCard({ g }: { g: NrfiGame }) {
  const [open, setOpen] = useState(false);
  const isNrfi = g.direction === "NRFI";
  const edge   = g.EdgePct ?? 0;
  const tier   = edgeTier(edge);

  return (
    <div className="pick-card" onClick={() => setOpen(o => !o)}>
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border)]">
        <span className="mkt-badge nrfi">{g.direction}</span>
        {edge > 0 && <span className={`edge-badge ${tier}`}>+{edge.toFixed(1)}% edge</span>}
      </div>

      <div className="px-4 py-4">
        <div className="text-lg font-black text-[var(--text-bright)] leading-tight mb-1">
          {g.away_team} <span className="text-[var(--text-muted)] font-normal text-sm">@</span> {g.home_team}
        </div>
        <div className="text-xs text-[var(--text-muted)] mb-3">
          {g.away_sp || "TBD"} vs {g.home_sp || "TBD"}
        </div>
        {g.projected_nrfi != null && g.implied_nrfi != null && (
          <ProbBar model={g.projected_nrfi} implied={g.implied_nrfi} color={isNrfi ? "high" : "indigo"} />
        )}
      </div>

      <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)] bg-[var(--bg-overlay)]">
        <div className="flex items-center gap-3">
          {g.BestOdds != null && <span className="text-xl font-black text-[var(--amber)] font-mono">{fmtOdds(g.BestOdds)}</span>}
          {g.Sportsbook && <span className="text-[10px] text-[var(--text-muted)]">{g.Sportsbook.toUpperCase()}</span>}
        </div>
      </div>

      {open && (
        <div className="px-4 py-4 border-t border-[var(--border)] grid grid-cols-2 gap-4 bg-[var(--bg-panel)]" onClick={e => e.stopPropagation()}>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">PROJ NRFI%</div>
            <div className="text-[var(--cyan)] font-black font-mono">{g.projected_nrfi != null ? `${(g.projected_nrfi*100).toFixed(1)}%` : "N/A"}</div>
          </div>
          <div>
            <div className="text-[9px] font-semibold tracking-widest text-[var(--text-muted)] mb-1">IMPLIED NRFI%</div>
            <div className="text-[var(--text-bright)] font-bold font-mono">{g.implied_nrfi != null ? `${(g.implied_nrfi*100).toFixed(1)}%` : "N/A"}</div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Card grid section ─────────────────────────────────────────────────────────

function Section({ title, color, count, children }: { title: string; color: string; count: number; children: React.ReactNode }) {
  if (count === 0) return null;
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <h2 className={`text-sm font-bold ${color}`}>{title}</h2>
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${color.replace("text-", "border-").replace("]", "/30]")} bg-[var(--bg-raised)]`}>{count}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {children}
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [data, setData]       = useState<PicksData|null>(null);
  const [sport, setSport]     = useState("mlb");
  const [market, setMarket]   = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [ts, setTs]           = useState("");

  const load = useCallback(() => {
    setLoading(true); setError("");
    fetch(`${API}/picks/${sport}?bankroll=1000&min_edge=0.03`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); setTs(new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [sport]);

  useEffect(() => { load(); }, [load]);

  const d = data;
  const ml    = d?.moneyline ?? [];
  const sp    = d?.spread ?? [];
  const tot   = d?.totals ?? [];
  const props = d?.props ?? [];
  const nrfi  = d?.nrfi ?? [];

  // Sort each section by edge descending
  const sortML   = [...ml].sort((a, b)  => b.Edge - a.Edge);
  const sortSP   = [...sp].sort((a, b)  => b.Edge - a.Edge);
  const sortTot  = [...tot].sort((a, b) => b.Edge - a.Edge);
  const sortProp = [...props].sort((a, b) => b.EdgePct - a.EdgePct);
  const sortNrfi = [...nrfi].sort((a, b) => (b.EdgePct ?? 0) - (a.EdgePct ?? 0));

  // Featured pick: highest edge across all game picks
  const allGamePicks = [...sortML, ...sortSP, ...sortTot];
  const featuredPick = allGamePicks[0] ?? null;

  const totalCount = ml.length + sp.length + tot.length + props.length + nrfi.length;

  const show = (mkt: string) => market === "all" || market === mkt;

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 pb-24 md:pb-8 space-y-6">

      {/* ── Controls ── */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        {/* Sport */}
        <div className="flex items-center gap-2">
          {SPORTS.map(s => (
            <button key={s.key} onClick={() => setSport(s.key)}
              className={`sport-tab ${sport === s.key ? "active" : ""}`}>
              {s.label}
            </button>
          ))}
        </div>

        {/* Market filter */}
        <div className="flex items-center gap-1.5 flex-wrap sm:ml-auto">
          {MARKETS.map(m => (
            <button key={m.key} onClick={() => setMarket(m.key)}
              className={`text-[11px] font-semibold px-3 py-1 rounded-lg border transition-all ${
                market === m.key
                  ? "bg-[var(--bg-overlay)] border-[var(--border-hi)] text-[var(--text-bright)]"
                  : "border-transparent text-[var(--text-muted)] hover:text-[var(--text)]"
              }`}>
              {m.label}
            </button>
          ))}
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
              {totalCount} picks · updated {ts}
            </div>
          )}
          {d?.display_date && <span className="text-xs text-[var(--text-muted)]">— {d.display_date}</span>}
        </div>
        <button onClick={load} className="text-[11px] text-[var(--indigo)] font-semibold hover:opacity-70 transition-opacity">↻ Refresh</button>
      </div>

      {/* ── Error state ── */}
      {error && (
        <div className="rounded-xl border border-[var(--red)]/40 bg-[var(--red-dim)] px-4 py-3 text-sm text-[var(--red)]">
          {error}
        </div>
      )}

      {/* ── Message (no picks) ── */}
      {!loading && !error && d?.message && totalCount === 0 && (
        <div className="rounded-2xl border border-[var(--border-hi)] bg-[var(--bg-raised)] px-6 py-12 text-center">
          <div className="text-4xl mb-3">📭</div>
          <div className="text-[var(--text-bright)] font-bold mb-1">No picks today</div>
          <div className="text-sm text-[var(--text-muted)]">{d.message}</div>
        </div>
      )}

      {/* ── Skeleton ── */}
      {loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {[1,2,3,4].map(i => (
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

      {/* ── Featured pick ── */}
      {!loading && featuredPick && market === "all" && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm font-bold text-[var(--gold)]">★ Best Edge Today</h2>
          </div>
          <PickCard pick={featuredPick} featured={true} />
        </div>
      )}

      {/* ── Cards by market ── */}
      {!loading && !error && (
        <div className="space-y-8">
          {show("moneyline") && (
            <Section title="Moneyline" color="text-[var(--cyan)]" count={sortML.length}>
              {sortML.map((p, i) => <PickCard key={i} pick={p} />)}
            </Section>
          )}
          {show("spread") && (
            <Section title="Spread / Run Line" color="text-[var(--green)]" count={sortSP.length}>
              {sortSP.map((p, i) => <PickCard key={i} pick={p} />)}
            </Section>
          )}
          {show("totals") && (
            <Section title="Totals (O/U)" color="text-[var(--blue)]" count={sortTot.length}>
              {sortTot.map((p, i) => <PickCard key={i} pick={p} />)}
            </Section>
          )}
          {show("props") && (
            <Section title="Player Props" color="text-[var(--purple)]" count={sortProp.length}>
              {sortProp.map((p, i) => <PropCard key={i} prop={p} />)}
            </Section>
          )}
          {show("nrfi") && (
            <Section title="NRFI / YRFI" color="text-[var(--amber)]" count={sortNrfi.length}>
              {sortNrfi.map((g, i) => <NrfiCard key={i} g={g} />)}
            </Section>
          )}
        </div>
      )}

      {/* ── No results for filter ── */}
      {!loading && !error && totalCount > 0 && market !== "all" && (() => {
        const cnt = market === "moneyline" ? ml.length : market === "spread" ? sp.length : market === "totals" ? tot.length : market === "props" ? props.length : nrfi.length;
        if (cnt > 0) return null;
        return (
          <div className="rounded-2xl border border-[var(--border-hi)] bg-[var(--bg-raised)] px-6 py-10 text-center">
            <div className="text-3xl mb-2">🔍</div>
            <div className="text-[var(--text-bright)] font-bold mb-1">No {market} picks today</div>
            <div className="text-sm text-[var(--text-muted)]">Model didn&apos;t find an edge in this market for today&apos;s slate.</div>
          </div>
        );
      })()}
    </div>
  );
}
