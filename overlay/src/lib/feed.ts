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

export type CustomerFeed = {
  updated_at: string;
  date: string;
  record: {
    wins: number;
    losses: number;
    pushes: number;
    units: number;
    roi_pct: number;
    streak: number;
    settled: number;
  };
  picks: { nba: CustomerPick[]; mlb: CustomerPick[] };
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
