import { NextResponse } from 'next/server'
import { readFile } from 'fs/promises'
import path from 'path'

export const revalidate = 300

const ROOT = path.join(process.cwd(), '..')

// Mirrors src/config/models.py — status + labels
const MODEL_REGISTRY: Record<string, { status: 'live' | 'incubating' | 'retired'; label: string; sport: string; market: string }> = {
  'nba|total':                   { status: 'live',       label: 'NBA Totals',            sport: 'NBA', market: 'total' },
  'nba|moneyline':               { status: 'incubating', label: 'NBA Moneyline',          sport: 'NBA', market: 'moneyline' },
  'nba|spread':                  { status: 'incubating', label: 'NBA Spread',             sport: 'NBA', market: 'spread' },
  'nba|player_points':           { status: 'incubating', label: 'NBA Player Points',      sport: 'NBA', market: 'player_points' },
  'nba|player_rebounds':         { status: 'incubating', label: 'NBA Player Rebounds',    sport: 'NBA', market: 'player_rebounds' },
  'nba|player_assists':          { status: 'incubating', label: 'NBA Player Assists',      sport: 'NBA', market: 'player_assists' },
  'nba|player_blocks':           { status: 'incubating', label: 'NBA Player Blocks',      sport: 'NBA', market: 'player_blocks' },
  'nba|player_steals':           { status: 'incubating', label: 'NBA Player Steals',      sport: 'NBA', market: 'player_steals' },
  'nba|player_threes':           { status: 'incubating', label: 'NBA Player 3PM',         sport: 'NBA', market: 'player_threes' },
  'nba|player_pra':              { status: 'incubating', label: 'NBA Player PRA',         sport: 'NBA', market: 'player_pra' },
  'mlb|spread':                  { status: 'live',       label: 'MLB Run Line',           sport: 'MLB', market: 'spread' },
  'mlb|moneyline':               { status: 'incubating', label: 'MLB Moneyline',          sport: 'MLB', market: 'moneyline' },
  'mlb|total':                   { status: 'incubating', label: 'MLB Totals',             sport: 'MLB', market: 'total' },
  'mlb|f5_total':                { status: 'incubating', label: 'MLB F5 Totals',          sport: 'MLB', market: 'f5_total' },
  'mlb|nrfi':                    { status: 'incubating', label: 'MLB NRFI',               sport: 'MLB', market: 'nrfi' },
  'mlb|pitcher_strikeouts':      { status: 'incubating', label: 'MLB Pitcher Ks',         sport: 'MLB', market: 'pitcher_strikeouts' },
  'mlb|batter_hits':             { status: 'incubating', label: 'MLB Batter Hits',        sport: 'MLB', market: 'batter_hits' },
  'mlb|batter_total_bases':      { status: 'incubating', label: 'MLB Batter Total Bases', sport: 'MLB', market: 'batter_total_bases' },
  'mlb|batter_home_runs':        { status: 'incubating', label: 'MLB Batter HR',          sport: 'MLB', market: 'batter_home_runs' },
  'nhl|moneyline':               { status: 'incubating', label: 'NHL Moneyline',          sport: 'NHL', market: 'moneyline' },
  'nhl|puck_line':               { status: 'incubating', label: 'NHL Puck Line',          sport: 'NHL', market: 'puck_line' },
  'nhl|total':                   { status: 'incubating', label: 'NHL Totals',             sport: 'NHL', market: 'total' },
  'wnba|moneyline':              { status: 'incubating', label: 'WNBA Moneyline',         sport: 'WNBA', market: 'moneyline' },
  'wnba|spread':                 { status: 'incubating', label: 'WNBA Spread',            sport: 'WNBA', market: 'spread' },
  'wnba|total':                  { status: 'incubating', label: 'WNBA Totals',            sport: 'WNBA', market: 'total' },
  'pga|outright':                { status: 'incubating', label: 'PGA Outright',           sport: 'PGA', market: 'outright' },
  'tennis|moneyline':            { status: 'incubating', label: 'Tennis Moneyline',       sport: 'Tennis', market: 'moneyline' },
  // Legacy prop buckets — NBA/MLB props logged before sub-market split
  'nba|prop':                    { status: 'incubating', label: 'NBA Props (legacy)',      sport: 'NBA', market: 'prop' },
  'mlb|prop':                    { status: 'incubating', label: 'MLB Props (legacy)',      sport: 'MLB', market: 'prop' },
  // Other sports with picks
  'auto_racing_indycar_series|moneyline': { status: 'incubating', label: 'IndyCar Win',   sport: 'IndyCar', market: 'moneyline' },
  'mma_mixed_martial_arts|moneyline':     { status: 'incubating', label: 'MMA Moneyline', sport: 'MMA', market: 'moneyline' },
  'soccer_fifa_world_cup|moneyline':      { status: 'incubating', label: 'Soccer ML',     sport: 'Soccer', market: 'moneyline' },
  'soccer_fifa_world_cup|total':          { status: 'incubating', label: 'Soccer Totals', sport: 'Soccer', market: 'total' },
}

// Normalize sport key from picks.json → registry sport key
function normalizeSport(s: string): string {
  // Exact matches first (full sport keys used in registry)
  if (s === 'auto_racing_indycar_series') return 'auto_racing_indycar_series'
  if (s === 'mma_mixed_martial_arts') return 'mma_mixed_martial_arts'
  if (s.startsWith('soccer_')) return s  // keep full soccer key for registry lookup
  // Strip sport-type prefixes for common sports
  return s
    .replace(/^baseball_/, '')
    .replace(/^basketball_/, '')
    .replace(/^icehockey_/, '')
    .replace(/^golf_.*/, 'pga')
    .replace(/^tennis_.*/, 'tennis')
    .toLowerCase()
}

// Normalize market key from picks.json → registry market key
function normalizeMarket(m: string): string {
  const map: Record<string, string> = {
    runline: 'spread',
    run_line: 'spread',
    puck_line: 'puck_line',
    player_points_rebounds_assists: 'player_pra',
    // IndyCar / racing use "win" market
    win: 'moneyline',
    // PGA uses "outright" already — no remap needed
  }
  return map[m] || m
}

export async function GET() {
  let picks: Record<string, unknown>[] = []
  try {
    const raw = await readFile(path.join(ROOT, 'data', 'pnl', 'picks.json'), 'utf-8')
    const parsed = JSON.parse(raw)
    picks = Array.isArray(parsed) ? parsed : (parsed.picks || [])
  } catch { picks = [] }

  // Aggregate by model key
  const agg: Record<string, { wins: number; losses: number; pushes: number; profit: number; pending: number; card_wins: number; card_losses: number; card_profit: number }> = {}

  for (const key of Object.keys(MODEL_REGISTRY)) {
    agg[key] = { wins: 0, losses: 0, pushes: 0, profit: 0, pending: 0, card_wins: 0, card_losses: 0, card_profit: 0 }
  }

  for (const p of picks) {
    const sport = normalizeSport((p.sport as string) || '')
    const market = normalizeMarket((p.market as string) || '')
    const key = `${sport}|${market}`

    if (!agg[key]) continue

    const result = (p.result as string) || ''
    const profit = (p.profit as number) || 0
    const isCard = !!p.card_pick

    if (result === 'win') {
      agg[key].wins++
      agg[key].profit += profit
      if (isCard) { agg[key].card_wins++; agg[key].card_profit += profit }
    } else if (result === 'loss') {
      agg[key].losses++
      agg[key].profit += profit
      if (isCard) { agg[key].card_losses++; agg[key].card_profit += profit }
    } else if (result === 'push') {
      agg[key].pushes++
    } else {
      agg[key].pending++
    }
  }

  const models = Object.entries(MODEL_REGISTRY).map(([key, meta]) => {
    const stats = agg[key]
    const settled = stats.wins + stats.losses
    const winRate = settled > 0 ? stats.wins / settled : null
    const roi = settled > 0 ? stats.profit / settled : null
    const cardSettled = stats.card_wins + stats.card_losses
    return {
      key,
      ...meta,
      wins: stats.wins,
      losses: stats.losses,
      pushes: stats.pushes,
      pending: stats.pending,
      profit: Math.round(stats.profit * 100) / 100,
      win_rate: winRate != null ? Math.round(winRate * 1000) / 10 : null,
      roi: roi != null ? Math.round(roi * 1000) / 10 : null,
      card_wins: stats.card_wins,
      card_losses: stats.card_losses,
      card_profit: Math.round(stats.card_profit * 100) / 100,
      card_settled: cardSettled,
      settled,
    }
  })

  // Sort: live first, then by settled desc
  models.sort((a, b) => {
    if (a.status !== b.status) {
      if (a.status === 'live') return -1
      if (b.status === 'live') return 1
    }
    return b.settled - a.settled
  })

  const liveModels = models.filter(m => m.status === 'live')
  const totalCardWins = liveModels.reduce((s, m) => s + m.card_wins, 0)
  const totalCardLosses = liveModels.reduce((s, m) => s + m.card_losses, 0)
  const totalCardProfit = liveModels.reduce((s, m) => s + m.card_profit, 0)

  return NextResponse.json({
    models,
    summary: {
      live_count: liveModels.length,
      incubating_count: models.filter(m => m.status === 'incubating').length,
      card_wins: totalCardWins,
      card_losses: totalCardLosses,
      card_profit: Math.round(totalCardProfit * 100) / 100,
    }
  })
}
