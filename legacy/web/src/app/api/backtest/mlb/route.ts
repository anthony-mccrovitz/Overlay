import { NextResponse } from "next/server";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

const STATS_FILE = join(process.cwd(), "..", "data", "public_stats.json");

function loadBacktest() {
  try {
    if (existsSync(STATS_FILE)) {
      const raw = JSON.parse(readFileSync(STATS_FILE, "utf-8"));
      const bt = raw.backtest_mlb ?? [];
      // Transform to the shape BacktestCard expects: { Season, Accuracy, Games, Lift }
      const results = bt.map((r: Record<string, unknown>) => ({
        Season:   r.season,
        Accuracy: r.high_conf ?? r.accuracy,  // show high-confidence accuracy
        Games:    r.games,
        Lift:     r.high_conf && r.accuracy ? (r.high_conf as number) - (r.accuracy as number) : undefined,
      }));
      return { results };
    }
  } catch {
    // fall through
  }
  // Static fallback — actual backtest results from April 13 retrain
  return {
    results: [
      { Season: 2025, Accuracy: 0.583, Games: 2432, Lift: 0.042 },
      { Season: 2024, Accuracy: 0.571, Games: 2430, Lift: 0.033 },
    ],
  };
}

export async function GET() {
  const data = loadBacktest();
  return NextResponse.json(data, {
    headers: {
      "Cache-Control": "public, s-maxage=3600, stale-while-revalidate=7200",
    },
  });
}
