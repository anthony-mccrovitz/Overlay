import { NextRequest, NextResponse } from 'next/server'
import { readFile } from 'fs/promises'
import path from 'path'

export const revalidate = 300

const ROOT = path.join(process.cwd(), '..')

// Normalize legacy sport keys to canonical form
function normalizeSportKey(s: string): string {
  if (s === 'mlb') return 'baseball_mlb'
  if (s === 'nba') return 'basketball_nba'
  if (s === 'nhl') return 'icehockey_nhl'
  if (s === 'ncaab') return 'basketball_ncaab'
  return s
}

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams
  const sport = sp.get('sport') || 'all'
  const market = sp.get('market') || 'all'
  const cardOnly = sp.get('card_only') === 'true'
  const days = parseInt(sp.get('days') || '90')

  let picks: Record<string, unknown>[] = []
  try {
    const raw = await readFile(path.join(ROOT, 'data', 'pnl', 'picks.json'), 'utf-8')
    const parsed = JSON.parse(raw)
    picks = Array.isArray(parsed) ? parsed : (parsed.picks || [])
  } catch { picks = [] }

  const cutoff = new Date()
  cutoff.setDate(cutoff.getDate() - days)

  const filtered = picks.filter((p: Record<string, unknown>) => {
    if (cardOnly && !p.card_pick) return false
    if (sport !== 'all' && normalizeSportKey(p.sport as string) !== sport) return false
    if (market !== 'all' && p.market !== market) return false
    if (!p.date) return false
    const d = new Date(p.date as string)
    if (isNaN(d.getTime())) return false
    if (days < 9999 && d < cutoff) return false
    return true
  })

  // Compute by_date series for charts
  // Only win/loss count as settled — exclude push and void
  const settled = filtered.filter((p: Record<string, unknown>) => p.result === 'win' || p.result === 'loss')
  const byDate: Record<string, { profit: number; n: number; wins: number }> = {}
  for (const p of settled) {
    const d = p.date as string
    if (!byDate[d]) byDate[d] = { profit: 0, n: 0, wins: 0 }
    byDate[d].profit += (p.profit as number) || 0
    byDate[d].n++
    if (p.result === 'win') byDate[d].wins++
  }

  let cum = 0
  const byDateArr = Object.keys(byDate).sort().map(date => {
    cum += byDate[date].profit
    return { date, daily_profit: byDate[date].profit, cumulative_profit: cum, n: byDate[date].n, wins: byDate[date].wins }
  })

  const wins = settled.filter((p: Record<string, unknown>) => p.result === 'win').length
  const losses = settled.filter((p: Record<string, unknown>) => p.result === 'loss').length
  const totalProfit = settled.reduce((acc: number, p: Record<string, unknown>) => acc + ((p.profit as number) || 0), 0)

  return NextResponse.json({
    picks: filtered,
    by_date: byDateArr,
    summary: {
      wins,
      losses,
      pushes: filtered.filter((p: Record<string, unknown>) => p.result === 'push').length,
      profit: Math.round(totalProfit * 100) / 100,
      roi: settled.length > 0 ? Math.round((totalProfit / settled.length) * 10000) / 10000 : 0,
      total: filtered.length,
    }
  })
}
