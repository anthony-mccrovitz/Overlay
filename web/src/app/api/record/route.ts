import { NextResponse } from "next/server";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

// Path to the Python pipeline's public stats file.
// Works locally (file is in repo root) and on Vercel (committed to repo).
const STATS_FILE = join(process.cwd(), "..", "data", "public_stats.json");

const FALLBACK = {
  summary: {
    total_picks: 0,
    settled_picks: 0,
    wins: 0,
    losses: 0,
    win_rate: 0,
    units_staked: 0,
    units_profit: 0,
    roi: 0,
    streak: 0,
  },
};

function loadStats() {
  try {
    if (existsSync(STATS_FILE)) {
      const raw = JSON.parse(readFileSync(STATS_FILE, "utf-8"));
      const s = raw.summary || {};
      return {
        summary: {
          total_picks:   s.total_picks   ?? 0,
          settled_picks: s.settled       ?? 0,
          wins:          s.wins          ?? 0,
          losses:        s.losses        ?? 0,
          win_rate:      s.win_rate      ?? 0,
          units_staked:  s.settled       ?? 0,  // 1u flat stake per pick
          units_profit:  s.units_profit  ?? 0,
          roi:           s.roi           ?? 0,
          streak:        s.streak        ?? 0,
        },
        updated_at:   raw.updated_at,
        recent_picks: raw.recent_picks ?? [],
      };
    }
  } catch {
    // fall through
  }
  return FALLBACK;
}

export async function GET() {
  const data = loadStats();
  return NextResponse.json(data, {
    headers: {
      // Cache for 5 minutes — grades run once per day
      "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600",
    },
  });
}
