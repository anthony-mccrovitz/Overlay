"use client";

import { useEffect, useState, useCallback } from "react";

const API = "/api";

// ── Types ──────────────────────────────────────────────────────────────

interface Game {
  game_id: string;
  home_team: string;
  away_team: string;
  home_win_prob: number;
  home_pitcher: string;
  away_pitcher: string;
  edge_drivers: string[];
  time?: string;
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
  { key: "mlb",   label: "MLB",   f: "F1" },
  { key: "nba",   label: "NBA",   f: "F5" },
  { key: "nfl",   label: "NFL",   f: "F6" },
  { key: "ncaab", label: "NCAAB", f: "F7" },
];

const ABBR: Record<string, string> = {
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

function abbr(name: string) {
  return ABBR[name] || name.split(" ").slice(-1)[0]?.slice(0, 3).toUpperCase() || "???";
}

function fmtOdds(o: number) {
  return o > 0 ? `+${o}` : `${o}`;
}

function fmtEdge(e: number, raw = false) {
  const v = raw ? e : e * 100;
  const s = `+${v.toFixed(1)}%`;
  if (v >= 8) return <span className="text-[var(--green)] font-bold">{s}</span>;
  if (v >= 5) return <span className="text-[var(--amber)]">{s}</span>;
  return <span className="text-[var(--blue)]">{s}</span>;
}

function edgeBg(e: number, raw = false) {
  const v = raw ? e : e * 100;
  if (v >= 8) return "bg-[var(--green-dim)]";
  if (v >= 5) return "bg-[var(--amber-dim)]";
  return "";
}

function MktLabel({ mkt }: { mkt: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    moneyline: { label: "ML",   cls: "text-[var(--cyan)] border-[var(--cyan)]/30" },
    spread:    { label: "RL",   cls: "text-[var(--green-hi)] border-[var(--green-hi)]/30" },
    total:     { label: "O/U",  cls: "text-[var(--blue)] border-[var(--blue)]/30" },
  };
  const m = map[mkt.toLowerCase()] ?? { label: mkt.toUpperCase().slice(0, 3), cls: "text-[var(--text-muted)] border-[var(--border-hi)]" };
  return (
    <span className={`border px-1.5 py-px text-[9px] font-bold tracking-wider ${m.cls}`}>
      {m.label}
    </span>
  );
}

// ── Table row components ────────────────────────────────────────────────

function PickRow({ pick, bankroll }: { pick: Pick; bankroll: number }) {
  const [open, setOpen] = useState(false);
  const e = pick.Edge;

  return (
    <>
      <tr
        className={`t-row cursor-pointer ${edgeBg(e)}`}
        onClick={() => setOpen(!open)}
      >
        {/* Team */}
        <td className="px-3 py-2 whitespace-nowrap">
          <div className="text-xs font-semibold text-[var(--text-bright)]">{pick.Team}</div>
          <div className="text-[10px] text-[var(--text-muted)] truncate max-w-[120px]">{pick.Opponent}</div>
        </td>
        {/* Market */}
        <td className="px-2 py-2 hidden sm:table-cell">
          <MktLabel mkt={pick.Market ?? "moneyline"} />
        </td>
        {/* Model prob */}
        <td className="px-2 py-2 text-right font-mono text-[11px] text-[var(--cyan)] hidden md:table-cell">
          {(pick.ModelProb * 100).toFixed(1)}%
        </td>
        {/* Implied */}
        <td className="px-2 py-2 text-right font-mono text-[11px] text-[var(--text-secondary)] hidden lg:table-cell">
          {(pick.ImpliedProb * 100).toFixed(1)}%
        </td>
        {/* Edge */}
        <td className="px-2 py-2 text-right font-mono text-[11px]">
          {fmtEdge(e)}
        </td>
        {/* Odds */}
        <td className="px-2 py-2 text-right font-mono text-[11px] text-[var(--text-bright)]">
          {fmtOdds(pick.BestOdds)}
        </td>
        {/* Book */}
        <td className="px-2 py-2 text-[10px] text-[var(--text-muted)] hidden sm:table-cell">
          {pick.Sportsbook || "—"}
        </td>
        {/* Kelly */}
        <td className="px-2 py-2 text-right font-mono text-[10px] text-[var(--text-muted)] hidden lg:table-cell">
          {pick.KellyFraction != null ? `${(pick.KellyFraction * 100).toFixed(1)}%` : "—"}
        </td>
        {/* Expand */}
        <td className="px-2 py-2 text-[var(--text-muted)] text-center w-6">
          <span className="text-[10px]">{open ? "▲" : "▼"}</span>
        </td>
      </tr>
      {open && (
        <tr className="bg-[var(--bg-panel)]">
          <td colSpan={9} className="px-4 py-3 border-b border-[var(--border-hi)]">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[10px]">
              <div>
                <div className="text-[var(--text-muted)] tracking-wider mb-0.5">MODEL PROB</div>
                <div className="text-[var(--cyan)] font-mono font-bold text-sm">{(pick.ModelProb * 100).toFixed(2)}%</div>
              </div>
              <div>
                <div className="text-[var(--text-muted)] tracking-wider mb-0.5">IMPLIED PROB</div>
                <div className="text-[var(--text-bright)] font-mono font-bold text-sm">{(pick.ImpliedProb * 100).toFixed(2)}%</div>
              </div>
              <div>
                <div className="text-[var(--text-muted)] tracking-wider mb-0.5">KELLY FRACTION</div>
                <div className="text-[var(--amber)] font-mono font-bold text-sm">
                  {pick.KellyFraction != null ? `${(pick.KellyFraction * 100).toFixed(2)}%` : "N/A"}
                </div>
              </div>
              {bankroll > 0 && pick.BetSize != null && pick.BetSize > 0 && (
                <div>
                  <div className="text-[var(--text-muted)] tracking-wider mb-0.5">BET SIZE ($BKR={bankroll})</div>
                  <div className="text-[var(--green)] font-mono font-bold text-sm">
                    ${pick.BetSize.toFixed(0)}
                    {pick.ExpectedProfit != null && pick.ExpectedProfit > 0 && (
                      <span className="ml-2 text-[10px] font-normal text-[var(--text-muted)]">+${pick.ExpectedProfit.toFixed(2)} EV</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function PropRow({ prop, bankroll }: { prop: Prop; bankroll: number }) {
  const [open, setOpen] = useState(false);
  const mktLabel = prop.market.replace("pitcher_", "").replace(/_/g, " ").toUpperCase();
  return (
    <>
      <tr className={`t-row cursor-pointer ${edgeBg(prop.EdgePct, true)}`} onClick={() => setOpen(!open)}>
        <td className="px-3 py-2 whitespace-nowrap">
          <div className="text-xs font-semibold text-[var(--text-bright)]">{prop.player}</div>
          <div className="text-[10px] text-[var(--text-muted)]">{prop.team} vs {prop.opponent}</div>
        </td>
        <td className="px-2 py-2 hidden sm:table-cell">
          <span className="border border-[var(--purple)]/30 px-1.5 py-px text-[9px] font-bold tracking-wider text-[var(--purple)]">
            {prop.direction} {prop.line}
          </span>
        </td>
        <td className="px-2 py-2 text-right font-mono text-[11px] text-[var(--cyan)] hidden md:table-cell">
          {(prop.ModelProb * 100).toFixed(1)}%
        </td>
        <td className="px-2 py-2 text-right font-mono text-[11px] text-[var(--text-secondary)] hidden lg:table-cell">
          {(prop.ImpliedProb * 100).toFixed(1)}%
        </td>
        <td className="px-2 py-2 text-right font-mono text-[11px]">
          {fmtEdge(prop.EdgePct, true)}
        </td>
        <td className="px-2 py-2 text-right font-mono text-[11px] text-[var(--text-bright)]">
          {fmtOdds(prop.BestOdds)}
        </td>
        <td className="px-2 py-2 text-[10px] text-[var(--text-muted)] hidden sm:table-cell">
          {prop.Sportsbook || "—"}
        </td>
        <td className="px-2 py-2 text-[10px] text-[var(--text-muted)] hidden lg:table-cell">
          {prop.projected != null ? `proj ${prop.projected.toFixed(1)}` : "—"}
        </td>
        <td className="px-2 py-2 text-center w-6 text-[10px] text-[var(--text-muted)]">
          {open ? "▲" : "▼"}
        </td>
      </tr>
      {open && (
        <tr className="bg-[var(--bg-panel)]">
          <td colSpan={9} className="px-4 py-3 border-b border-[var(--border-hi)]">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-[10px]">
              <div>
                <div className="text-[var(--text-muted)] mb-0.5">MARKET</div>
                <div className="text-[var(--purple)] font-semibold">{mktLabel}</div>
              </div>
              <div>
                <div className="text-[var(--text-muted)] mb-0.5">PROJECTED</div>
                <div className="text-[var(--text-bright)] font-mono">{prop.projected != null ? prop.projected.toFixed(2) : "N/A"}</div>
              </div>
              {bankroll > 0 && prop.BetSize != null && prop.BetSize > 0 && (
                <div>
                  <div className="text-[var(--text-muted)] mb-0.5">BET SIZE</div>
                  <div className="text-[var(--green)] font-mono">${prop.BetSize.toFixed(0)}</div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function NrfiRow({ g }: { g: NrfiGame }) {
  const [open, setOpen] = useState(false);
  const isNrfi = g.direction === "NRFI";
  return (
    <>
      <tr className="t-row cursor-pointer" onClick={() => setOpen(!open)}>
        <td className="px-3 py-2 whitespace-nowrap">
          <div className="text-xs font-semibold text-[var(--text-bright)]">{g.away_team} @ {g.home_team}</div>
          <div className="text-[10px] text-[var(--text-muted)]">{g.away_sp || "TBD"} vs {g.home_sp || "TBD"}</div>
        </td>
        <td className="px-2 py-2 hidden sm:table-cell">
          <span className={`border px-1.5 py-px text-[9px] font-bold tracking-wider ${isNrfi ? "border-[var(--green-hi)]/30 text-[var(--green-hi)]" : "border-[var(--red)]/30 text-[var(--red)]"}`}>
            {g.direction}
          </span>
        </td>
        <td className="px-2 py-2 text-right font-mono text-[11px] text-[var(--cyan)] hidden md:table-cell">
          {g.projected_nrfi != null ? `${(g.projected_nrfi * 100).toFixed(0)}%` : "—"}
        </td>
        <td className="px-2 py-2 text-right font-mono text-[11px] text-[var(--text-secondary)] hidden lg:table-cell">
          {g.implied_nrfi != null ? `${(g.implied_nrfi * 100).toFixed(0)}%` : "—"}
        </td>
        <td className="px-2 py-2 text-right font-mono text-[11px]">
          {g.EdgePct != null ? fmtEdge(g.EdgePct, true) : <span className="text-[var(--text-muted)]">—</span>}
        </td>
        <td className="px-2 py-2 text-right font-mono text-[11px] text-[var(--text-bright)]">
          {g.BestOdds != null ? fmtOdds(g.BestOdds) : "—"}
        </td>
        <td className="px-2 py-2 text-[10px] text-[var(--text-muted)] hidden sm:table-cell">
          {g.Sportsbook || "—"}
        </td>
        <td className="px-2 py-2 hidden lg:table-cell" />
        <td className="px-2 py-2 text-center w-6 text-[10px] text-[var(--text-muted)]">
          {open ? "▲" : "▼"}
        </td>
      </tr>
      {open && (
        <tr className="bg-[var(--bg-panel)]">
          <td colSpan={9} className="px-4 py-3 border-b border-[var(--border-hi)]">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[10px]">
              <div>
                <div className="text-[var(--text-muted)] mb-0.5">PROJ NRFI %</div>
                <div className="text-[var(--cyan)] font-mono">{g.projected_nrfi != null ? `${(g.projected_nrfi * 100).toFixed(1)}%` : "N/A"}</div>
              </div>
              <div>
                <div className="text-[var(--text-muted)] mb-0.5">IMPLIED NRFI %</div>
                <div className="text-[var(--text-bright)] font-mono">{g.implied_nrfi != null ? `${(g.implied_nrfi * 100).toFixed(1)}%` : "N/A"}</div>
              </div>
              <div>
                <div className="text-[var(--text-muted)] mb-0.5">HOME SP</div>
                <div className="text-[var(--text-secondary)]">{g.home_sp || "TBD"}</div>
              </div>
              <div>
                <div className="text-[var(--text-muted)] mb-0.5">AWAY SP</div>
                <div className="text-[var(--text-secondary)]">{g.away_sp || "TBD"}</div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function GameRow({ g }: { g: Game }) {
  const [open, setOpen] = useState(false);
  const homePct = Math.round(g.home_win_prob * 100);
  const awayPct = 100 - homePct;
  const fav = homePct >= 50 ? "home" : "away";

  return (
    <>
      <tr className="t-row cursor-pointer" onClick={() => setOpen(!open)}>
        <td className="px-3 py-2">
          <div className="flex items-center gap-2">
            <span className={`font-mono text-[10px] font-bold ${fav === "away" ? "text-[var(--cyan)]" : "text-[var(--text-secondary)]"}`}>
              {abbr(g.away_team)}
            </span>
            <span className="text-[var(--text-muted)] text-[10px]">@</span>
            <span className={`font-mono text-[10px] font-bold ${fav === "home" ? "text-[var(--cyan)]" : "text-[var(--text-secondary)]"}`}>
              {abbr(g.home_team)}
            </span>
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            <div className="flex-1 h-1 bg-[var(--bg-overlay)] overflow-hidden">
              <div className="h-full bg-[var(--cyan)] prob-bar" style={{ width: `${awayPct}%` }} />
            </div>
          </div>
        </td>
        <td className="px-2 py-2 font-mono text-[11px] text-[var(--text-secondary)] hidden sm:table-cell">
          {awayPct}% / {homePct}%
        </td>
        <td className="px-2 py-2 text-[10px] text-[var(--text-muted)] hidden md:table-cell">
          {g.away_pitcher || "TBD"}
        </td>
        <td className="px-2 py-2 text-[10px] text-[var(--text-muted)] hidden md:table-cell">
          {g.home_pitcher || "TBD"}
        </td>
        <td className="px-2 py-2 text-[10px] text-[var(--text-muted)] hidden lg:table-cell">
          {g.edge_drivers.length > 0 ? `${g.edge_drivers.length} signal${g.edge_drivers.length > 1 ? "s" : ""}` : "—"}
        </td>
        <td className="px-2 py-2 text-center w-6 text-[10px] text-[var(--text-muted)]">
          {open ? "▲" : "▼"}
        </td>
      </tr>
      {open && g.edge_drivers.length > 0 && (
        <tr className="bg-[var(--bg-panel)]">
          <td colSpan={6} className="px-4 py-3 border-b border-[var(--border-hi)]">
            <div className="space-y-1">
              {g.edge_drivers.map((d, i) => (
                <div key={i} className="text-[10px] text-[var(--text-secondary)] flex items-start gap-2">
                  <span className="text-[var(--cyan)] mt-px">›</span>
                  {d}
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Section table ──────────────────────────────────────────────────────

function PicksTable({ data, bankroll, section }: {
  data: PicksData;
  bankroll: number;
  section: "moneyline" | "spread" | "totals" | "props" | "nrfi" | "games";
}) {
  const picks   = section === "moneyline" ? data.moneyline
    : section === "spread"   ? data.spread
    : section === "totals"   ? data.totals
    : [];
  const props   = section === "props" ? data.props : [];
  const nrfi    = section === "nrfi" ? data.nrfi : [];
  const games   = section === "games" ? data.games : [];

  const labels: Record<string, { title: string; color: string; count: number }> = {
    moneyline: { title: "MONEYLINE SIGNALS", color: "text-[var(--cyan)]",     count: data.moneyline.length },
    spread:    { title: "RUN LINE SIGNALS",  color: "text-[var(--green-hi)]", count: data.spread.length },
    totals:    { title: "OVER/UNDER SIGNALS",color: "text-[var(--blue)]",     count: data.totals.length },
    props:     { title: "PLAYER PROPS",      color: "text-[var(--purple)]",   count: data.props.length },
    nrfi:      { title: "NRFI / YRFI",       color: "text-[var(--amber)]",    count: data.nrfi.length },
    games:     { title: "ALL GAMES",         color: "text-[var(--text-secondary)]", count: data.games.length },
  };

  const { title, color, count } = labels[section];

  // Column headers differ by section
  const isGames = section === "games";
  const isProps = section === "props";
  const isNrfi  = section === "nrfi";

  return (
    <div className="border border-[var(--border-hi)]">
      {/* Section header */}
      <div className="panel-header flex items-center">
        <span className={`text-[10px] font-bold tracking-widest ${color}`}>▌ {title}</span>
        <span className="ml-2 text-[9px] text-[var(--text-muted)] border border-[var(--border-hi)] px-1.5 py-px">{count}</span>
        {count === 0 && (
          <span className="ml-auto text-[9px] text-[var(--text-muted)]">NO SIGNALS TODAY</span>
        )}
      </div>

      {count === 0 ? (
        <div className="px-4 py-5 text-center text-[10px] text-[var(--text-muted)] tracking-wider">
          — NO {title} FOUND FOR THIS DATE —
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[var(--border-hi)]">
                {isGames ? <>
                  <th className="px-3 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium">MATCHUP</th>
                  <th className="px-2 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">WIN PROB</th>
                  <th className="px-2 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">AWAY SP</th>
                  <th className="px-2 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">HOME SP</th>
                  <th className="px-2 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden lg:table-cell">SIGNALS</th>
                  <th className="w-6" />
                </> : <>
                  <th className="px-3 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium">
                    {isProps ? "PLAYER" : isNrfi ? "MATCHUP" : "TEAM"}
                  </th>
                  <th className="px-2 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">
                    {isProps ? "BET" : isNrfi ? "DIRECTION" : "MKT"}
                  </th>
                  <th className="px-2 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden md:table-cell">
                    {isNrfi ? "PROJ%" : "MODEL"}
                  </th>
                  <th className="px-2 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden lg:table-cell">IMPLIED</th>
                  <th className="px-2 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">EDGE</th>
                  <th className="px-2 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium">ODDS</th>
                  <th className="px-2 py-1.5 text-left text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden sm:table-cell">BOOK</th>
                  <th className="px-2 py-1.5 text-right text-[9px] text-[var(--text-muted)] tracking-widest font-medium hidden lg:table-cell">
                    {isProps ? "PROJ" : "KELLY%"}
                  </th>
                  <th className="w-6" />
                </>}
              </tr>
            </thead>
            <tbody>
              {picks.map((p, i) => <PickRow key={i} pick={p} bankroll={bankroll} />)}
              {props.map((p, i) => <PropRow key={i} prop={p} bankroll={bankroll} />)}
              {nrfi.map((g, i) => <NrfiRow key={i} g={g} />)}
              {games.map((g) => <GameRow key={g.game_id} g={g} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [data, setData]       = useState<PicksData | null>(null);
  const [sport, setSport]     = useState("mlb");
  const [bankroll, setBankroll] = useState(500);
  const [bkrEdit, setBkrEdit]  = useState(false);
  const [loading, setLoading]  = useState(true);
  const [error, setError]      = useState("");
  const [ts, setTs]            = useState("");

  const fetchData = useCallback(() => {
    setLoading(true);
    setError("");
    fetch(`${API}/picks/${sport}?bankroll=${bankroll}&min_edge=0.03`)
      .then((r) => r.json())
      .then((d) => {
        setData(d);
        setLoading(false);
        setTs(new Date().toISOString().replace("T", " ").slice(0, 19) + " UTC");
      })
      .catch((e) => { setError(e.message); setLoading(false); });
  }, [sport, bankroll]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const totalSignals = data
    ? data.moneyline.length + data.spread.length + data.totals.length + data.props.length + data.nrfi.length
    : 0;

  const avgEdge = data && totalSignals > 0
    ? (() => {
        const picks = [...data.moneyline, ...data.spread, ...data.totals];
        const props = data.props;
        if (picks.length + props.length === 0) return null;
        const total = picks.reduce((a, p) => a + p.Edge * 100, 0)
                    + props.reduce((a, p) => a + p.EdgePct, 0);
        return (total / (picks.length + props.length)).toFixed(1);
      })()
    : null;

  return (
    <div className="flex flex-col">

      {/* ── Control bar ── */}
      <div className="border-b border-[var(--border-hi)] bg-[var(--bg-panel)] sticky top-9 z-40">
        <div className="max-w-6xl mx-auto px-3">
          {/* Sport tabs */}
          <div className="flex items-center h-9 gap-0 overflow-x-auto no-scrollbar">
            {SPORTS.map((s) => (
              <button
                key={s.key}
                onClick={() => setSport(s.key)}
                className={`flex items-center gap-1 px-3 h-9 text-[11px] font-medium tracking-wider border-b-2 transition-colors whitespace-nowrap pressable ${
                  sport === s.key
                    ? "border-[var(--cyan)] text-[var(--cyan)] bg-[var(--cyan-dim)]"
                    : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--bg-overlay)]"
                }`}
              >
                <span className="text-[9px] text-[var(--text-muted)] hidden sm:inline">{s.f}</span>
                {s.label}
              </button>
            ))}

            {/* Status strip */}
            <div className="ml-auto flex items-center gap-3 text-[10px] flex-shrink-0">
              {ts && <span className="text-[var(--text-muted)] hidden md:block">{ts}</span>}
              {data?.display_date && (
                <span className="text-[var(--text-secondary)]">{data.display_date.toUpperCase()}</span>
              )}
              <span className="text-[var(--text-muted)]">
                SIGNALS: <span className="text-[var(--cyan)] font-bold">{totalSignals}</span>
              </span>
              {avgEdge && (
                <span className="text-[var(--text-muted)] hidden sm:block">
                  AVG EDGE: <span className="text-[var(--green)] font-bold">+{avgEdge}%</span>
                </span>
              )}
              {/* Bankroll */}
              <button
                onClick={() => setBkrEdit(!bkrEdit)}
                className={`border px-2 py-0.5 text-[9px] tracking-wider transition-colors pressable ${
                  bkrEdit ? "border-[var(--cyan)] text-[var(--cyan)]" : "border-[var(--border-hi)] text-[var(--text-muted)] hover:border-[var(--border-hi)] hover:text-[var(--text-secondary)]"
                }`}
              >
                BKR: ${bankroll}
              </button>
              {/* Refresh */}
              <button
                onClick={fetchData}
                className="border border-[var(--border-hi)] px-2 py-0.5 text-[9px] text-[var(--text-muted)] hover:text-[var(--text)] hover:border-[var(--cyan)] tracking-wider transition-colors pressable"
                title="Refresh"
              >
                {loading ? "..." : "↻ REFRESH"}
              </button>
            </div>
          </div>

          {/* Bankroll editor */}
          {bkrEdit && (
            <div className="border-t border-[var(--border-hi)] py-2 flex items-center gap-3">
              <span className="text-[9px] text-[var(--text-muted)] tracking-widest">BANKROLL INPUT ($):</span>
              <input
                type="number"
                value={bankroll}
                onChange={(e) => setBankroll(Number(e.target.value))}
                className="bg-transparent border-b border-[var(--cyan)] text-[var(--cyan)] font-mono text-sm outline-none w-24 pb-px"
                autoFocus
              />
              <span className="text-[9px] text-[var(--text-muted)]">KELLY SIZING ACTIVE WHEN SET</span>
            </div>
          )}
        </div>
      </div>

      {/* ── Content ── */}
      <div className="max-w-6xl mx-auto w-full px-3 py-4 space-y-px">

        {/* Error */}
        {error && (
          <div className="border border-[var(--red)]/30 bg-[var(--red-dim)] px-4 py-3 text-[11px] text-[var(--red)] font-mono">
            ERROR: {error}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-px">
            {[80, 200, 160, 200, 80].map((h, i) => (
              <div key={i} className="skeleton border border-[var(--border-hi)]" style={{ height: h }} />
            ))}
          </div>
        )}

        {/* No data */}
        {!loading && data && totalSignals === 0 && data.games.length === 0 && (
          <div className="border border-[var(--border-hi)] bg-[var(--bg-panel)] px-4 py-8 text-center">
            <div className="text-[10px] text-[var(--text-muted)] tracking-widest mb-2">NO DATA</div>
            <div className="text-sm text-[var(--text-secondary)]">
              {data.message ?? `No picks found for ${sport.toUpperCase()}. Check back during the season.`}
            </div>
          </div>
        )}

        {/* Data tables */}
        {!loading && data && (totalSignals > 0 || data.games.length > 0) && (
          <>
            <PicksTable data={data} bankroll={bankroll} section="moneyline" />
            <PicksTable data={data} bankroll={bankroll} section="spread" />
            <PicksTable data={data} bankroll={bankroll} section="totals" />
            <PicksTable data={data} bankroll={bankroll} section="props" />
            <PicksTable data={data} bankroll={bankroll} section="nrfi" />
            {data.games.length > 0 && (
              <PicksTable data={data} bankroll={bankroll} section="games" />
            )}
          </>
        )}

        {/* Footer */}
        {!loading && (
          <div className="pt-2 pb-4 text-[9px] text-[var(--text-muted)] tracking-wider text-center">
            NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+ · CLICK ANY ROW TO EXPAND
          </div>
        )}
      </div>
    </div>
  );
}
