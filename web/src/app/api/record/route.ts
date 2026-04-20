import { NextResponse } from "next/server";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

const STATS_FILE_PRIMARY  = join(process.cwd(), "public", "data", "public_stats.json");
const STATS_FILE_FALLBACK = join(process.cwd(), "..", "data", "public_stats.json");
const STATS_FILE = existsSync(STATS_FILE_PRIMARY) ? STATS_FILE_PRIMARY : STATS_FILE_FALLBACK;

function loadStats() {
  try {
    if (existsSync(STATS_FILE)) {
      const raw = JSON.parse(readFileSync(STATS_FILE, "utf-8"));
      const s = raw.summary ?? {};
      return {
        updated_at: raw.updated_at ?? null,
        summary: {
          total_picks:   s.total_picks   ?? 0,
          settled:       s.settled       ?? 0,
          pending:       s.pending       ?? 0,
          wins:          s.wins          ?? 0,
          losses:        s.losses        ?? 0,
          pushes:        s.pushes        ?? 0,
          win_rate:      s.win_rate      ?? 0,
          units_profit:  s.units_profit  ?? 0,
          roi:           s.roi           ?? 0,
          streak:        s.streak        ?? 0,
        },
        nrfi: raw.nrfi ?? null,
        by_market: raw.by_market ?? {},
        by_sport:  raw.by_sport  ?? {},
        backtest_mlb: raw.backtest_mlb ?? [],
        recent_picks: (raw.recent_picks ?? []).map((p: Record<string, unknown>) => ({
          date:      p.date     ?? null,
          sport:     p.sport    ?? "mlb",
          market:    p.market   ?? null,
          team:      p.team     ?? null,
          matchup:   p.matchup  ?? null,
          odds:      p.odds     ?? null,
          result:    p.result   ?? null,
          profit:    p.profit   ?? null,
          edge_pct:  p.edge_pct ?? null,
        })),
      };
    }
  } catch {
    // fall through
  }
  return {
    updated_at: null,
    summary: { total_picks: 0, settled: 0, pending: 0, wins: 0, losses: 0, pushes: 0, win_rate: 0, units_profit: 0, roi: 0, streak: 0 },
    nrfi: null, by_market: {}, by_sport: {}, backtest_mlb: [], recent_picks: [],
  };
}

export async function GET() {
  return NextResponse.json(loadStats(), {
    headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600" },
  });
}
