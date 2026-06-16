// Server-only readers for the generated World Cup data. JSON lives in
// src/data/wc/ (written by `python3 chef.py wc`) and is read at request time —
// same pattern as the slate API route. Degrades gracefully if not generated.
import { readFile } from "fs/promises";
import { join } from "path";
import type { WCAccuracy, WCFixture, WCFutures, WCGoldenBoot, WCGroups, WCMeta } from "@/lib/wc";

async function read<T>(name: string): Promise<T | null> {
  try {
    const p = join(process.cwd(), "src", "data", "wc", name);
    return JSON.parse(await readFile(p, "utf-8")) as T;
  } catch {
    return null;
  }
}

export const getFixtures   = () => read<WCFixture[]>("fixtures.json");
export const getFutures    = () => read<WCFutures>("futures.json");
export const getGoldenBoot = () => read<WCGoldenBoot>("golden_boot.json");
export const getGroups     = () => read<WCGroups>("groups.json");
export const getMeta       = () => read<WCMeta>("meta.json");
export const getAccuracy   = () => read<WCAccuracy>("accuracy.json");

export interface WCPickOfDay {
  date: string;
  match: string;        // "Mexico v South Africa"
  selection: string;    // team name, or "Draw"
  prob: number;         // model/blend win prob for that selection (0..1)
  edgePp: number;       // edge over the market, in percentage points
  price: number | null; // American odds for the selection, if priced
  city: string | null;
  time: string | null;
}

/**
 * The World Cup "pick of the day": the highest-edge fixture on the next match
 * day with games (today if today has fixtures, otherwise the soonest upcoming
 * day). Used to put a real, current free play in the lead-capture welcome
 * email. Returns null if WC data isn't generated or the tournament is over.
 */
export async function getWorldCupPickOfDay(today?: string): Promise<WCPickOfDay | null> {
  const fixtures = await getFixtures();
  if (!fixtures || fixtures.length === 0) return null;

  const todayStr = today ?? new Date().toISOString().slice(0, 10);
  const upcoming = fixtures.filter((f) => f.date >= todayStr);
  if (upcoming.length === 0) return null; // tournament finished

  const targetDate = upcoming.reduce((min, f) => (f.date < min ? f.date : min), upcoming[0].date);
  const sameDay = upcoming.filter((f) => f.date === targetDate && f.edge);
  if (sameDay.length === 0) return null;

  const best = sameDay.reduce((a, b) => (b.edge!.pp > a.edge!.pp ? b : a));
  const side = best.edge!.side;
  const probs = best.blend ?? best.model;
  const prob = side === "home" ? probs.home_win : side === "away" ? probs.away_win : probs.draw;
  const selection = side === "home" ? best.home : side === "away" ? best.away : "Draw";
  const price = best.market?.prices ? best.market.prices[side] ?? null : null;

  return {
    date: best.date,
    match: `${best.home} v ${best.away}`,
    selection,
    prob,
    edgePp: best.edge!.pp,
    price,
    city: best.context?.city ?? null,
    time: best.time ?? null,
  };
}
