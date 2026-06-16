'use client'
import { useEffect, useState, useMemo } from 'react'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, BarChart, Bar, CartesianGrid, ReferenceLine } from 'recharts'
import { Loader2 } from 'lucide-react'
import { useAutoRefresh } from '@/components/AutoRefresh'

const TIMELINES = [
  { label: '1D', days: 1 },
  { label: '7D', days: 7 },
  { label: '30D', days: 30 },
  { label: '90D', days: 90 },
  { label: 'All', days: 9999 },
]

interface HistoryData {
  picks: Record<string, unknown>[]
  by_date: { date: string; cumulative_profit: number; daily_profit: number; n: number; wins: number }[]
  summary: { wins: number; losses: number; pushes: number; profit: number; roi: number; total: number }
}

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="stat-card">
      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 800, color: color || 'var(--text-bright)', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

export default function PerformancePage() {
  useAutoRefresh(5 * 60 * 1000)
  const [days, setDays] = useState(90)
  const [sport, setSport] = useState('all')
  const [market, setMarket] = useState('all')
  const [cardOnly, setCardOnly] = useState(false)
  const [data, setData] = useState<HistoryData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams({ sport, market, card_only: cardOnly ? 'true' : 'false', days: String(days) })
    fetch(`/api/history?${params}`).then(r => r.json()).then(d => { setData(d); setLoading(false) })
  }, [days, sport, market, cardOnly])

  const endProfit = data?.by_date?.at(-1)?.cumulative_profit ?? 0
  const lineColor = endProfit >= 0 ? '#22C55E' : '#EF4444'

  const byDateWithColor = useMemo(() => (data?.by_date || []).map(d => ({
    ...d,
    date: d.date.slice(5), // MM-DD
    color: d.cumulative_profit >= 0 ? '#22C55E' : '#EF4444'
  })), [data])

  // Normalize sport key: "mlb" and "baseball_mlb" → "MLB" etc.
  const normSport = (s: string) => s
    .replace(/^baseball_/, '').replace(/^basketball_/, '')
    .replace(/^icehockey_/, '').replace(/^auto_racing_/, '')
    .replace(/^golf_/, '').replace(/^soccer_/, '').replace(/^tennis_/, '')
    .replace(/^mma_/, '').replace(/_/g, ' ')
    .toUpperCase()
    .replace('MIXED MARTIAL ARTS', 'UFC')
    .replace('PGA CHAMPIONSHIP', 'PGA')
    .replace('FIFA WORLD CUP', 'Soccer')
    .replace('ATP FRENCH OPEN', 'Tennis')
    .replace('FORMULA ONE', 'F1')
    .replace('INDYCAR SERIES', 'IndyCar')
    .replace('NASCAR CUP SERIES', 'NASCAR')

  // ROI by sport — merge equivalent sport keys (mlb + baseball_mlb → MLB)
  const bySport = useMemo(() => {
    if (!data?.picks) return []
    const map: Record<string, { profit: number; n: number }> = {}
    for (const p of data.picks) {
      const key = normSport((p.sport as string) || 'unknown')
      if (!map[key]) map[key] = { profit: 0, n: 0 }
      if (p.result === 'win' || p.result === 'loss') {
        map[key].profit += (p.profit as number) || 0
        map[key].n++
      }
    }
    return Object.entries(map).map(([sport, v]) => ({
      sport,
      roi: v.n > 0 ? Math.round((v.profit / v.n) * 1000) / 10 : 0,
      n: v.n,
      profit: Math.round(v.profit * 100) / 100,
    })).sort((a, b) => b.n - a.n)
  }, [data])

  const s = data?.summary
  const winPct = s && (s.wins + s.losses) > 0 ? (s.wins / (s.wins + s.losses) * 100).toFixed(1) : '—'

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-bright)', margin: '0 0 4px' }}>Performance</h1>
        <p style={{ color: 'var(--text-muted)', margin: 0, fontSize: 12 }}>P&L, ROI breakdown, win rates</p>
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 24, alignItems: 'center' }}>
        {/* Timeline pills */}
        <div style={{ display: 'flex', gap: 4, background: 'var(--bg-raised)', border: '1px solid var(--border-hi)', borderRadius: 8, padding: 3 }}>
          {TIMELINES.map(t => (
            <button key={t.label} onClick={() => setDays(t.days)} style={{
              padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: 'none',
              background: days === t.days ? 'var(--indigo)' : 'transparent',
              color: days === t.days ? '#fff' : 'var(--text-secondary)',
            }}>{t.label}</button>
          ))}
        </div>
        <select value={sport} onChange={e => setSport(e.target.value)}
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-hi)', color: 'var(--text)', borderRadius: 8, padding: '6px 10px', fontSize: 12 }}>
          <option value="all">All sports</option>
          <option value="baseball_mlb">MLB</option>
          <option value="basketball_nba">NBA</option>
          <option value="basketball_wnba">WNBA</option>
          <option value="auto_racing_indycar_series">IndyCar</option>
          <option value="golf_pga_championship">PGA</option>
        </select>
        <select value={market} onChange={e => setMarket(e.target.value)}
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-hi)', color: 'var(--text)', borderRadius: 8, padding: '6px 10px', fontSize: 12 }}>
          <option value="all">All markets</option>
          <option value="moneyline">Moneyline</option>
          <option value="spread">Spread</option>
          <option value="total">Total</option>
          <option value="nrfi">NRFI</option>
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)', cursor: 'pointer' }}>
          <input type="checkbox" checked={cardOnly} onChange={e => setCardOnly(e.target.checked)} />
          Card picks only
        </label>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
          <Loader2 size={24} style={{ color: 'var(--indigo)', animation: 'spin 1s linear infinite' }} />
          <style>{`@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }`}</style>
        </div>
      ) : (
        <>
          {/* Summary stats */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 28 }}>
            <StatCard label="Record" value={s ? `${s.wins}-${s.losses}` : '—'} sub={s?.pushes ? `${s.pushes} push` : undefined} />
            <StatCard label="Win %" value={`${winPct}%`} color={parseFloat(winPct) >= 52.4 ? 'var(--green)' : 'var(--text-bright)'} />
            <StatCard label="Profit" value={s ? `${s.profit >= 0 ? '+' : ''}${s.profit.toFixed(1)}u` : '—'} color={s && s.profit >= 0 ? 'var(--green)' : 'var(--red)'} />
            <StatCard label="ROI" value={s ? `${(s.roi * 100).toFixed(1)}%` : '—'} color={s && s.roi >= 0 ? 'var(--green)' : 'var(--red)'} />
            <StatCard label="Picks" value={s ? String(s.total) : '—'} />
          </div>

          {/* P&L Chart */}
          <div className="stat-card" style={{ marginBottom: 20, padding: '20px 16px' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 16, letterSpacing: '0.05em' }}>CUMULATIVE P&L (units)</div>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={byDateWithColor} margin={{ top: 4, right: 16, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} tickLine={false} />
                <ReferenceLine y={0} stroke="var(--border-hi)" strokeDasharray="4 4" />
                <Tooltip contentStyle={{ background: 'var(--bg-overlay)', border: '1px solid var(--border-hi)', borderRadius: 8, fontSize: 12 }} labelStyle={{ color: 'var(--text-secondary)' }} formatter={(v: number) => [`${v >= 0 ? '+' : ''}${v.toFixed(2)}u`, 'Cumulative P&L']} />
                <Line type="monotone" dataKey="cumulative_profit" stroke={lineColor} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* ROI by sport */}
          {bySport.length > 0 && (
            <div className="stat-card" style={{ padding: '20px 16px' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 16, letterSpacing: '0.05em' }}>ROI BY SPORT (%)</div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={bySport} margin={{ top: 4, right: 16, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="sport" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} tickLine={false} />
                  <ReferenceLine y={0} stroke="var(--border-hi)" />
                  <Tooltip contentStyle={{ background: 'var(--bg-overlay)', border: '1px solid var(--border-hi)', borderRadius: 8, fontSize: 12 }} formatter={(v: number) => [`${v.toFixed(1)}%`, 'ROI']} />
                  <Bar dataKey="roi" radius={[4,4,0,0]} fill="var(--indigo)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  )
}
