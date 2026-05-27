import { NextResponse } from "next/server";
import { readFileSync, existsSync, readdirSync } from "fs";
import { join } from "path";

const OUTPUT_ROOT = join(process.cwd(), "..", "output", "picks");

// Canonical short-key → output directory name mapping.
// Dynamic scan adds any unrecognized sport dirs at runtime.
const SPORT_DIR_MAP: Record<string, string> = {
  mlb:          "baseball_mlb",
  nba:          "basketball_nba",
  nhl:          "icehockey_nhl",
  wnba:         "basketball_wnba",
  ncaab:        "basketball_ncaab",
  nfl:          "americanfootball_nfl",
  // Tennis / Soccer use their Odds API sport key directly as both short key and dir
  tennis:       "tennis_atp_french_open",
  soccer:       "soccer_epl",
  "soccer_epl":                  "soccer_epl",
  "soccer_spain_la_liga":        "soccer_spain_la_liga",
  "soccer_italy_serie_a":        "soccer_italy_serie_a",
  "soccer_germany_bundesliga":   "soccer_germany_bundesliga",
  "soccer_france_ligue_1":       "soccer_france_ligue_1",
  "soccer_england_championship": "soccer_england_championship",
  "soccer_fifa_world_cup":       "soccer_fifa_world_cup",
  "tennis_atp_french_open":      "tennis_atp_french_open",
  "tennis_atp_wimbledon":        "tennis_atp_wimbledon",
  "tennis_atp_us_open":          "tennis_atp_us_open",
  "tennis_wta_french_open":      "tennis_wta_french_open",
  pga:          "golf_pga_championship",
  ufc:          "mma_mixed_martial_arts",
  indycar:      "motorsport_formula_1",
};

function resolveSportDir(sport: string): string | null {
  const lower = sport.toLowerCase();
  if (SPORT_DIR_MAP[lower]) return SPORT_DIR_MAP[lower];
  // Dynamic: if a folder with that name exists under OUTPUT_ROOT, use it directly
  const { existsSync: _ex } = require("fs");
  if (_ex(join(OUTPUT_ROOT, lower))) return lower;
  return null;
}

function getLatestDateDir(sportDir: string): string | null {
  const dir = join(OUTPUT_ROOT, sportDir);
  if (!existsSync(dir)) return null;
  const entries = readdirSync(dir)
    .filter((d) => /^\d{8}$/.test(d))
    .sort()
    .reverse();
  return entries[0] ?? null;
}

function readJsonFile(path: string): unknown[] {
  if (!existsSync(path)) return [];
  try {
    const content = readFileSync(path, "utf-8")
      .replace(/:\s*NaN/g, ": null")
      .replace(/:\s*Infinity/g, ": null")
      .replace(/:\s*-Infinity/g, ": null");
    const parsed = JSON.parse(content);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function americanOddsToImplied(odds: number): number {
  if (odds > 0) return 100 / (odds + 100);
  return Math.abs(odds) / (Math.abs(odds) + 100);
}

function kellyFraction(modelProb: number, impliedProb: number): number {
  const decimalOdds = 1 / impliedProb;
  const b = decimalOdds - 1;
  const p = modelProb;
  const q = 1 - p;
  const f = (b * p - q) / b;
  return Math.max(0, f * 0.25); // quarter-Kelly
}

// ── Types ──────────────────────────────────────────────────────────────

interface RawPick {
  Team: string;
  Opponent?: string;
  ModelProb?: number | null;
  ImpliedProb?: number | null;
  Edge?: number | null;
  BestOdds?: number | null;
  Sportsbook?: string | null;
  Market?: string | null;
  Why?: string | null;
  Matchup?: string | null;
  HomeTeam?: string | null;
  CommenceTime?: string | null;
  GameID?: string | null;
  Direction?: string | null;
  MarketLine?: number | null;
  model_tier?: string | null;
  weather_context?: string | null;
}

interface RawProp {
  player: string;
  team?: string;
  opp?: string;
  market?: string;
  line?: number | null;
  direction?: string;
  projected?: number | null;
  model_prob?: number | null;
  implied_prob?: number | null;
  edge_pct?: number | null;
  odds?: number | null;
  book?: string | null;
  label?: string;
}

interface RawNrfi {
  direction?: string;
  home_team?: string;
  away_team?: string;
  home_sp?: string;
  away_sp?: string;
  projected_nrfi?: number | null;
  implied_nrfi?: number | null;
  edge_pct?: number | null;
  odds?: number | null;
  book?: string | null;
  label?: string;
}

// ── Transformers ───────────────────────────────────────────────────────

function transformPick(p: RawPick, mkt: string, bankroll: number) {
  const isTotal = mkt === "total";
  const odds = p.BestOdds ?? -110;
  const implied = isTotal
    ? americanOddsToImplied(odds)
    : (p.ImpliedProb ?? americanOddsToImplied(odds));
  const prob = isTotal
    ? implied + 0.03
    : (p.ModelProb ?? 0.5);
  const edge = isTotal ? 0.03 : (p.Edge ?? 0);
  const kf = kellyFraction(prob, implied);
  const betSize = bankroll > 0 && !isTotal ? bankroll * kf : 0;
  const decOdds = 1 / implied;
  const expectedProfit = betSize > 0 ? betSize * (prob * decOdds - 1) : 0;

  return {
    Team: p.Team,
    Opponent: p.Opponent ?? p.Matchup ?? "",
    ModelProb: prob,
    ImpliedProb: implied,
    Edge: edge,
    BestOdds: odds,
    Sportsbook: p.Sportsbook ?? "",
    Market: mkt,
    BetSize: betSize > 0.5 ? betSize : undefined,
    KellyFraction: kf,
    ExpectedProfit: expectedProfit > 0 ? expectedProfit : undefined,
    model_tier: p.model_tier ?? null,
    weather_context: p.weather_context ?? null,
  };
}

function transformProp(p: RawProp, bankroll: number) {
  const odds = p.odds ?? -110;
  const implied = p.implied_prob ?? americanOddsToImplied(odds);
  const prob = p.model_prob ?? implied;
  const edgePct = p.edge_pct ?? ((prob - implied) * 100);
  const kf = kellyFraction(prob, implied);
  const betSize = bankroll > 0 ? bankroll * kf : 0;
  const decOdds = 1 / implied;
  const expectedProfit = betSize > 0 ? betSize * (prob * decOdds - 1) : 0;

  return {
    player: p.player,
    team: p.team ?? "",
    opponent: p.opp ?? "",
    market: p.market ?? "prop",
    line: p.line ?? 0,
    direction: p.direction ?? "OVER",
    projected: p.projected ?? null,
    ModelProb: prob,
    ImpliedProb: implied,
    EdgePct: edgePct,
    BestOdds: odds,
    Sportsbook: p.book ?? "",
    label: p.label ?? `${p.player} ${p.direction ?? "OVER"} ${p.line}`,
    BetSize: betSize > 0.5 ? betSize : undefined,
    ExpectedProfit: expectedProfit > 0 ? expectedProfit : undefined,
  };
}

function transformNrfi(g: RawNrfi) {
  return {
    direction: g.direction ?? "NRFI",
    home_team: g.home_team ?? "",
    away_team: g.away_team ?? "",
    home_sp: g.home_sp ?? "TBD",
    away_sp: g.away_sp ?? "TBD",
    projected_nrfi: g.projected_nrfi ?? null,
    implied_nrfi: g.implied_nrfi ?? null,
    EdgePct: g.edge_pct ?? null,
    BestOdds: g.odds ?? null,
    Sportsbook: g.book ?? "",
    label: g.label ?? `${g.away_team} @ ${g.home_team} ${g.direction ?? "NRFI"}`,
  };
}

// ── Route ──────────────────────────────────────────────────────────────

export async function GET(
  request: Request,
  { params }: { params: Promise<{ sport: string }> }
) {
  const { sport } = await params;
  const { searchParams } = new URL(request.url);
  const bankroll = parseFloat(searchParams.get("bankroll") ?? "0");
  const minEdge = parseFloat(searchParams.get("min_edge") ?? "0.03");

  const sportDir = resolveSportDir(sport);
  if (!sportDir) {
    return NextResponse.json({ error: `Unknown sport: ${sport}` }, { status: 404 });
  }

  // Try today's date folder first, then fall back to latest
  const todayStr = new Date().toLocaleDateString("en-CA").replace(/-/g, ""); // YYYYMMDD local
  const allDirs = (() => {
    const dir = join(OUTPUT_ROOT, sportDir);
    if (!existsSync(dir)) return [];
    return readdirSync(dir).filter((d) => /^\d{8}$/.test(d)).sort().reverse();
  })();

  const dateDir = allDirs[0] ?? null;

  if (!dateDir) {
    return NextResponse.json({
      sport, date: null, moneyline: [], spread: [], totals: [], props: [], nrfi: [], games: [],
      message: `No picks found for ${sport.toUpperCase()}. Check back during the season.`,
    });
  }

  const dir = join(OUTPUT_ROOT, sportDir, dateDir);

  // Read picks from latest folder
  const rawPicks = readJsonFile(join(dir, "picks.json")) as RawPick[];

  // For props/nrfi: use latest folder if files exist, otherwise fall back to the previous date
  function findLatestWithFile(filename: string): unknown[] {
    for (const d of allDirs) {
      const path = join(OUTPUT_ROOT, sportDir!, d, filename);
      if (existsSync(path)) return readJsonFile(path);
    }
    return [];
  }

  const rawProps = findLatestWithFile("props.json") as RawProp[];
  const rawNrfi  = findLatestWithFile("nrfi.json") as RawNrfi[];

  // ── Split picks.json into 3 markets ──
  const mlPicks = rawPicks
    .filter((p) => (p.Market ?? "").toLowerCase() === "moneyline" && (p.Edge ?? 0) >= minEdge)
    .map((p) => transformPick(p, "moneyline", bankroll))
    .sort((a, b) => b.Edge - a.Edge);

  const spreadPicks = rawPicks
    .filter((p) => (p.Market ?? "").toLowerCase() === "spread" && (p.Edge ?? 0) >= minEdge)
    .map((p) => transformPick(p, "spread", bankroll))
    .sort((a, b) => b.Edge - a.Edge);

  const totalsPicks = rawPicks
    .filter((p) => {
      const mkt = (p.Market ?? "").toLowerCase();
      return mkt === "total" && p.BestOdds != null;
    })
    .map((p) => transformPick(p, "total", bankroll));

  // ── Props ──
  const props = rawProps
    .sort((a, b) => (b.edge_pct ?? 0) - (a.edge_pct ?? 0))
    .map((p) => transformProp(p, bankroll));

  // ── NRFI ──
  const nrfi = rawNrfi
    .sort((a, b) => (b.projected_nrfi ?? 0) - (a.projected_nrfi ?? 0))
    .map(transformNrfi);

  // ── Games list (from all picks combined) ──
  const gameMap = new Map<string, {
    game_id: string; home_team: string; away_team: string;
    home_win_prob: number; home_pitcher: string; away_pitcher: string;
    edge_drivers: string[]; time?: string;
  }>();

  for (const p of rawPicks) {
    const matchupStr = p.Matchup ?? p.Opponent ?? "";
    const parts = matchupStr.split(" @ ");
    const away = (parts[0] ?? p.Team ?? "").trim();
    const home = (parts[1] ?? p.HomeTeam ?? "").trim();
    if (!away || !home) continue;
    const key = `${away}@${home}`;
    if (!gameMap.has(key)) {
      gameMap.set(key, {
        game_id: p.GameID ?? key, home_team: home, away_team: away,
        home_win_prob: 0.5, home_pitcher: "", away_pitcher: "",
        edge_drivers: [], time: p.CommenceTime ?? undefined,
      });
    }
    const game = gameMap.get(key)!;
    if (p.Market?.toLowerCase() === "moneyline" && (p.ModelProb ?? 0) > 0) {
      const isHome = p.Team === home || p.Team === p.HomeTeam;
      game.home_win_prob = isHome ? (p.ModelProb ?? 0.5) : 1 - (p.ModelProb ?? 0.5);
    }
    if (p.Why?.trim()) {
      const driver = `${(p.Market ?? "").toUpperCase()}: ${p.Why.trim()}`;
      if (!game.edge_drivers.includes(driver)) game.edge_drivers.push(driver);
    }
  }

  // Also add NRFI games to the game map
  for (const g of rawNrfi) {
    const away = g.away_team ?? "";
    const home = g.home_team ?? "";
    if (!away || !home) continue;
    const key = `${away}@${home}`;
    if (!gameMap.has(key)) {
      gameMap.set(key, {
        game_id: key, home_team: home, away_team: away,
        home_win_prob: 0.5, home_pitcher: g.home_sp ?? "", away_pitcher: g.away_sp ?? "",
        edge_drivers: [], time: undefined,
      });
    } else {
      const game = gameMap.get(key)!;
      if (!game.home_pitcher) game.home_pitcher = g.home_sp ?? "";
      if (!game.away_pitcher) game.away_pitcher = g.away_sp ?? "";
    }
  }

  const games = Array.from(gameMap.values()).sort((a, b) =>
    (a.time ?? "").localeCompare(b.time ?? "")
  );

  // ── Display date ──
  const y = dateDir.slice(0, 4), mo = dateDir.slice(4, 6), d = dateDir.slice(6, 8);
  const displayDate = new Date(`${y}/${mo}/${d}`).toLocaleDateString("en-US", {
    weekday: "short", month: "short", day: "numeric",
  });

  return NextResponse.json(
    {
      sport,
      date: dateDir,
      display_date: displayDate,
      moneyline: mlPicks,
      spread: spreadPicks,
      totals: totalsPicks,
      props,
      nrfi,
      games,
    },
    { headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600" } }
  );
}
