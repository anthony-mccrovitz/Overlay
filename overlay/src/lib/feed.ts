import feedJson from "@/data/customer_feed.json";

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

export type ModelRow = {
  key: string;
  sport: string;
  sport_key?: string;
  label: string;
  market?: string;
  market_label?: string;
  tier?: "t1" | "t2" | "shadow" | "paused";
  status: string;
  wins: number;
  losses: number;
  pushes: number;
  pending: number;
  settled: number;
  win_rate: number | null;
  roi: number | null;
  profit: number;
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
  models: ModelRow[];
  upcoming_models?: UpcomingModel[];
  seats: { taken: number; total: number };
};

export type UpcomingModel = {
  sport: string;
  label: string;
  market: string;
  eta: string;
  status: string;
  teaser: string;
  accent: string;
};

export async function readFeed(): Promise<CustomerFeed | null> {
  return feedJson as unknown as CustomerFeed;
}
