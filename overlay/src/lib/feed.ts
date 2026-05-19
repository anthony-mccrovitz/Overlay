import { promises as fs } from "fs";
import path from "path";

export type CustomerPick = {
  matchup: string;
  selection: string;
  market: string;
  odds: string;
  stake: string;
  sportsbook: string;
  reasoning: string;
  result: string;
};

export type TickerItem = {
  sport: string;
  matchup: string;
  result: string;
  units: number;
};

export type RecentPick = {
  date: string;
  sport: string;
  matchup: string;
  pick: string;
  odds: string;
  result: string;
  pl: number;
};

export type EquityPoint = { date: string; units: number };

export type CustomerFeed = {
  updated_at: string;
  date: string;
  record: {
    wins: number;
    losses: number;
    pushes: number;
    units: number;
    roi_pct: number;
    win_rate_pct: number;
    streak: number;
    settled: number;
    avg_odds: string | null;
    total_card: number;
  };
  picks: { nba: CustomerPick[]; mlb: CustomerPick[] };
  featured: { pick: CustomerPick; sport: string } | null;
  ticker: TickerItem[];
  recent_picks: RecentPick[];
  equity_curve: EquityPoint[];
  seats: { taken: number; total: number };
};

export async function readFeed(): Promise<CustomerFeed | null> {
  try {
    const p = path.join(process.cwd(), "public", "data", "customer_feed.json");
    const raw = await fs.readFile(p, "utf-8");
    return JSON.parse(raw) as CustomerFeed;
  } catch {
    return null;
  }
}
