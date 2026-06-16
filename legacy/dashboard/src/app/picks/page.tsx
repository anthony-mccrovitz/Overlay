'use client'
import { useEffect, useState, useMemo } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import PickCard from '@/components/PickCard'
import PickOfTheDay from '@/components/PickOfTheDay'

const SPORT_LABELS: Record<string, string> = {
  baseball_mlb: 'MLB', basketball_nba: 'NBA', basketball_wnba: 'WNBA',
  icehockey_nhl: 'NHL', auto_racing_formula_one: 'F1',
  auto_racing_indycar_series: 'IndyCar', auto_racing_nascar_cup_series: 'NASCAR',
  soccer_fifa_world_cup: 'Soccer', mma_mixed_martial_arts: 'UFC',
  golf_pga_championship: 'PGA', golf_pga: 'PGA', golf_masters: 'Masters',
  mlb: 'MLB', nba: 'NBA', ncaab: 'NCAAB',
}

function sportLabel(key: string) {
  if (SPORT_LABELS[key]) return SPORT_LABELS[key]
  // Any tennis_* event → "Tennis"
  if (key.startsWith('tennis_')) return 'Tennis'
  // Any soccer_* → "Soccer"
  if (key.startsWith('soccer_')) return 'Soccer'
  return key.replace(/_/g, ' ').toUpperCase()
}

export interface NormalizedPick {
  _id: string
  sport: string
  market: string
  direction: string
  team: string
  matchup: string
  odds: number
  line: number | null
  sportsbook: string
  model_prob: number | null
  implied_prob: number | null
  edge_pct: number | null
  stake: number
  card_pick: boolean
  result: string | null
  profit: number | null
  date: string
  why: string | null
  label: string | null
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizePick(p: any, sport: string): NormalizedPick {
  // Determine odds (handle BestOdds, best_odds, odds)
  const odds = p.BestOdds ?? p.best_odds ?? p.odds ?? 0

  // Compute edge_pct — prefer ModelProb-ImpliedProb (unambiguous) over Edge field
  // which is stored inconsistently (ratio for ML, already-% for RL, etc.)
  let edge_pct: number | null = p.edge_pct ?? null
  const mp = p.model_prob ?? p.ModelProb ?? null
  const ip = p.implied_prob ?? p.ImpliedProb ?? null
  if (edge_pct === null && mp != null && ip != null)
    edge_pct = Math.round((mp - ip) * 10000) / 100
  // Last resort: Edge field — only use if it looks like a ratio (< 1)
  if (edge_pct === null && p.Edge != null)
    edge_pct = p.Edge < 1 ? Math.round(p.Edge * 10000) / 100 : Math.round(p.Edge * 100) / 100

  // Determine model_prob
  const model_prob = p.model_prob ?? (p.ModelProb ?? null)
  const implied_prob = p.implied_prob ?? (p.ImpliedProb ?? null)

  // Determine sportsbook
  const sportsbook = p.sportsbook ?? p.Sportsbook ?? p.book ?? '—'

  // Determine market
  const market = (p.market ?? p.Market ?? 'unknown').toLowerCase()

  // Determine direction/team display
  const direction = p.direction ?? p.Direction ?? p.driver ?? p.player ?? p.Team ?? ''
  const team = p.team ?? p.Team ?? p.player ?? p.driver ?? direction

  // Determine matchup
  const matchup = p.matchup ?? p.Matchup ??
    (p.home_team && p.away_team ? `${p.away_team} @ ${p.home_team}` : null) ??
    (p.Team && p.Opponent ? `${p.Team} vs ${p.Opponent}` : null) ??
    p.label ?? team

  const line = p.line ?? p.BetLine ?? p.bet_line ?? p.Spread ?? null

  return {
    _id: `${sport}-${market}-${direction}-${odds}-${Math.random()}`,
    sport: p.sport ?? sport,
    market,
    direction: direction || team,
    team,
    matchup: matchup || team,
    odds,
    line,
    sportsbook,
    model_prob,
    implied_prob,
    edge_pct,
    stake: p.stake ?? 1,
    card_pick: p.card_pick ?? false,
    result: p.result ?? null,
    profit: p.profit ?? null,
    date: p.date ?? '',
    why: p.Why ?? p.why ?? p.validation ?? p.notes ?? null,
    label: p.label ?? null,
  }
}

interface ApiResponse {
  date: string
  sports: Record<string, Record<string, unknown[]>>
}

// No sports skipped — show all model output, historical record purge is separate
const SKIP_SPORTS = new Set<string>([])
// Files that are duplicates or non-pick data
const SKIP_FILES = new Set(['sim_summary', 'picks_card'])

function flattenPicks(sports: Record<string, Record<string, unknown[]>>): NormalizedPick[] {
  const out: NormalizedPick[] = []
  for (const [sport, files] of Object.entries(sports)) {
    if (SKIP_SPORTS.has(sport)) continue
    for (const [fileKey, picks] of Object.entries(files)) {
      if (SKIP_FILES.has(fileKey)) continue
      for (const p of picks) {
        out.push(normalizePick(p, sport))
      }
    }
  }
  // Sort by edge descending — highest edge picks first
  out.sort((a, b) => {
    const ea = a.edge_pct ?? -999
    const eb = b.edge_pct ?? -999
    return eb - ea
  })
  return out
}

const PAGE_SIZE = 50

export default function PicksPage() {
  const [data, setData] = useState<ApiResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('all')
  const [minEdge, setMinEdge] = useState(5)
  const [market, setMarket] = useState('all')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const [date, setDate] = useState(() => {
    const now = new Date()
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}`
  })

  const load = async (d: string) => {
    setLoading(true)
    setVisibleCount(PAGE_SIZE)
    try {
      const res = await fetch(`/api/picks?date=${d}`)
      setData(await res.json())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(date) }, [date])

  const allPicks = useMemo(() => data ? flattenPicks(data.sports) : [], [data])
  // Deduplicate sport tabs by display label (all tennis_* → one "Tennis" tab)
  const sports = useMemo(() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const p of allPicks) {
      const lbl = sportLabel(p.sport)
      if (!seen.has(lbl)) { seen.add(lbl); out.push(p.sport) }
    }
    return out.sort((a, b) => sportLabel(a).localeCompare(sportLabel(b)))
  }, [allPicks])
  const allMarkets = useMemo(() => [...new Set(allPicks.map(p => p.market))].filter(Boolean).sort(), [allPicks])

  const filtered = useMemo(() => allPicks.filter(p => {
    // Tab match by label so "Tennis" tab catches all tennis_* sport keys
    if (tab !== 'all' && sportLabel(p.sport) !== sportLabel(tab)) return false
    if (market !== 'all' && p.market !== market) return false
    if (minEdge > 0 && (p.edge_pct === null || p.edge_pct < minEdge)) return false
    return true
  }), [allPicks, tab, market, minEdge])

  // Paginated slice — sorted by edge already from flattenPicks
  const visible = useMemo(() => filtered.slice(0, visibleCount), [filtered, visibleCount])

  const grouped = useMemo(() => {
    const g: Record<string, NormalizedPick[]> = {}
    for (const p of visible) {
      if (!g[p.sport]) g[p.sport] = []
      g[p.sport].push(p)
    }
    return g
  }, [visible])

  // Pick of the day: live model picks first, then highest edge
  const pickOfTheDay = useMemo(() => {
    const candidates = allPicks.filter(p => (p.edge_pct ?? 0) > 0)
    if (candidates.length === 0) return null
    const live = candidates.filter(p => p.card_pick)
    const pool = live.length > 0 ? live : candidates
    return pool.reduce((best, p) => (p.edge_pct ?? 0) > (best.edge_pct ?? 0) ? p : best)
  }, [allPicks])

  const todayLabel = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

  return (
    <div style={{ maxWidth: 920 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-bright)', margin: 0 }}>Today&apos;s Picks</h1>
          <p style={{ color: 'var(--text-muted)', margin: '4px 0 0', fontSize: 12 }}>{todayLabel}</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input type="date" value={`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}`}
            onChange={e => { const v = e.target.value.replace(/-/g,''); if (v.length === 8) { setDate(v); load(v) } }}
            style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-hi)', color: 'var(--text)', borderRadius: 8, padding: '6px 10px', fontSize: 12 }} />
          <button onClick={() => load(date)} style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-hi)', color: 'var(--text-secondary)', borderRadius: 8, padding: '6px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* Pick of the Day */}
      {!loading && pickOfTheDay && <PickOfTheDay pick={pickOfTheDay} />}

      {/* Sport tabs */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
        {['all', ...sports].map(s => (
          <button key={s} onClick={() => setTab(s)} style={{
            padding: '5px 14px', borderRadius: 999, fontSize: 12, fontWeight: 600, cursor: 'pointer',
            border: '1px solid', transition: 'all 0.15s',
            background: tab === s ? 'var(--indigo)' : 'transparent',
            borderColor: tab === s ? 'var(--indigo)' : 'var(--border-hi)',
            color: tab === s ? '#fff' : 'var(--text-secondary)',
          }}>
            {s === 'all' ? `All (${allPicks.length})` : sportLabel(s)}
          </button>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={market} onChange={e => { setMarket(e.target.value); setVisibleCount(PAGE_SIZE) }}
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-hi)', color: 'var(--text)', borderRadius: 8, padding: '6px 10px', fontSize: 12 }}>
          <option value="all">All markets</option>
          {allMarkets.map(m => <option key={m} value={m}>{m.replace(/_/g,' ')}</option>)}
        </select>
        <select value={minEdge} onChange={e => { setMinEdge(Number(e.target.value)); setVisibleCount(PAGE_SIZE) }}
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-hi)', color: 'var(--text)', borderRadius: 8, padding: '6px 10px', fontSize: 12 }}>
          <option value={0}>All edges</option>
          <option value={3}>≥3% edge</option>
          <option value={5}>≥5% edge (default)</option>
          <option value={8}>≥8% edge</option>
          <option value={10}>≥10% edge</option>
          <option value={15}>≥15% edge</option>
        </select>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {visible.length} of {filtered.length} picks
        </span>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
          <Loader2 size={24} style={{ color: 'var(--indigo)', animation: 'spin 1s linear infinite' }} />
          <style>{`@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }`}</style>
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
          <p style={{ fontSize: 16, marginBottom: 8 }}>No picks for {date.slice(0,4)}-{date.slice(4,6)}-{date.slice(6,8)}</p>
          <p style={{ fontSize: 12 }}>Try a different date or remove filters</p>
        </div>
      ) : (
        <div>
          {Object.entries(grouped).sort(([a],[b]) => a.localeCompare(b)).map(([sport, picks]) => (
            <div key={sport} style={{ marginBottom: 32 }}>
              <h2 style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 12, paddingBottom: 8, borderBottom: '1px solid var(--border)' }}>
                {sportLabel(sport)} <span style={{ fontWeight: 400 }}>({picks.length})</span>
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 10 }}>
                {picks.map(p => <PickCard key={p._id} pick={p} />)}
              </div>
            </div>
          ))}
          {/* Load more */}
          {visibleCount < filtered.length && (
            <div style={{ textAlign: 'center', paddingTop: 16 }}>
              <button onClick={() => setVisibleCount(v => v + PAGE_SIZE)} style={{
                background: 'var(--bg-raised)', border: '1px solid var(--border-hi)',
                color: 'var(--text-secondary)', borderRadius: 8, padding: '10px 24px',
                fontSize: 13, fontWeight: 600, cursor: 'pointer',
              }}>
                Load {Math.min(PAGE_SIZE, filtered.length - visibleCount)} more
                <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}> ({filtered.length - visibleCount} remaining)</span>
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
