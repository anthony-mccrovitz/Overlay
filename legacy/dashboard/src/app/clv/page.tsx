'use client'
import { useEffect, useState, useMemo } from 'react'
import { ResponsiveContainer, ScatterChart, Scatter, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from 'recharts'
import { Loader2 } from 'lucide-react'

const SPORT_COLORS: Record<string, string> = {
  mlb: '#22D3EE', baseball_mlb: '#22D3EE',
  basketball_nba: '#F59E0B', nba: '#F59E0B',
  icehockey_nhl: '#60A5FA', nhl: '#60A5FA',
  basketball_wnba: '#A78BFA',
  default: '#6366F1',
}

interface ClvData {
  snapshots: Record<string, unknown>[]
  summary: {
    avg_clv_pct: number
    beat_close_rate: number
    n: number
    by_sport: Record<string, { avg_clv: number; beat_rate: number; n: number }>
  }
}

export default function ClvPage() {
  const [days, setDays] = useState(90)
  const [sport, setSport] = useState('all')
  const [data, setData] = useState<ClvData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/clv?sport=${sport}&days=${days}`).then(r => r.json()).then(d => { setData(d); setLoading(false) })
  }, [sport, days])

  const s = data?.summary

  const scatterData = useMemo(() => (data?.snapshots || []).map(sn => ({
    x: Math.round(((sn.opening_implied_prob as number) || 0.5) * 1000) / 10,
    y: Math.round(((sn.clv_pct as number) || 0) * 100) / 100,
    sport: (sn.sport as string) || 'unknown',
    fill: SPORT_COLORS[(sn.sport as string) || ''] || SPORT_COLORS.default,
  })).filter(d => !isNaN(d.x) && !isNaN(d.y)), [data])

  const beatRate = s?.beat_close_rate ?? 0
  const beatPct = Math.round(beatRate * 100)

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-bright)', margin: '0 0 4px' }}>CLV Analysis</h1>
        <p style={{ color: 'var(--text-muted)', margin: 0, fontSize: 12 }}>Closing line value — did you beat the market?</p>
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 24, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 4, background: 'var(--bg-raised)', border: '1px solid var(--border-hi)', borderRadius: 8, padding: 3 }}>
          {[{l:'7D',d:7},{l:'30D',d:30},{l:'90D',d:90},{l:'All',d:9999}].map(t => (
            <button key={t.l} onClick={() => setDays(t.d)} style={{
              padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: 'none',
              background: days === t.d ? 'var(--indigo)' : 'transparent',
              color: days === t.d ? '#fff' : 'var(--text-secondary)',
            }}>{t.l}</button>
          ))}
        </div>
        <select value={sport} onChange={e => setSport(e.target.value)}
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-hi)', color: 'var(--text)', borderRadius: 8, padding: '6px 10px', fontSize: 12 }}>
          <option value="all">All sports</option>
          <option value="mlb">MLB</option>
          <option value="basketball_nba">NBA</option>
          <option value="icehockey_nhl">NHL</option>
        </select>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
          <Loader2 size={24} style={{ color: 'var(--indigo)', animation: 'spin 1s linear infinite' }} />
          <style>{`@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }`}</style>
        </div>
      ) : (
        <>
          {/* Key metrics */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 28 }}>
            <div className="stat-card" style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', marginBottom: 8 }}>BEAT CLOSE %</div>
              <div style={{ fontSize: 42, fontWeight: 900, color: beatPct >= 50 ? 'var(--green)' : 'var(--red)', lineHeight: 1 }}>{beatPct}%</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
                {beatPct >= 50 ? '✓ Beating market' : '✗ Market moving against you'}
              </div>
            </div>
            <div className="stat-card" style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', marginBottom: 8 }}>AVG CLV</div>
              <div style={{ fontSize: 42, fontWeight: 900, color: (s?.avg_clv_pct ?? 0) >= 0 ? 'var(--green)' : 'var(--red)', lineHeight: 1 }}>
                {s ? `${s.avg_clv_pct >= 0 ? '+' : ''}${s.avg_clv_pct.toFixed(2)}%` : '—'}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>{s?.n || 0} picks with CLV data</div>
            </div>
          </div>

          {/* Scatter */}
          {scatterData.length > 0 && (
            <div className="stat-card" style={{ marginBottom: 20, padding: '20px 16px' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 4, letterSpacing: '0.05em' }}>CLV SCATTER — Opening Implied Prob vs CLV%</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 12 }}>Each dot = one pick. Above 0 = you beat the close.</div>
              <ResponsiveContainer width="100%" height={240}>
                <ScatterChart margin={{ top: 4, right: 16, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="x" type="number" name="Opening Implied %" unit="%" domain={[30, 80]} tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} />
                  <YAxis dataKey="y" type="number" name="CLV%" unit="%" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} />
                  <ReferenceLine y={0} stroke="var(--border-hi)" strokeDasharray="4 4" />
                  <Tooltip cursor={{ stroke: 'var(--border-hi)' }} contentStyle={{ background: 'var(--bg-overlay)', border: '1px solid var(--border-hi)', borderRadius: 8, fontSize: 11 }} formatter={(v: number, name: string) => [`${v.toFixed(2)}%`, name]} />
                  <Scatter data={scatterData} fill="var(--indigo)" opacity={0.7} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* By sport table */}
          {s?.by_sport && Object.keys(s.by_sport).length > 0 && (
            <div className="stat-card">
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 12, letterSpacing: '0.05em' }}>CLV BY SPORT</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ color: 'var(--text-muted)', fontSize: 11, fontWeight: 600 }}>
                    <th style={{ textAlign: 'left', padding: '0 0 8px' }}>Sport</th>
                    <th style={{ textAlign: 'right', padding: '0 0 8px' }}>Avg CLV</th>
                    <th style={{ textAlign: 'right', padding: '0 0 8px' }}>Beat %</th>
                    <th style={{ textAlign: 'right', padding: '0 0 8px' }}>n</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(
                    // Merge duplicate sport keys (mlb + baseball_mlb → MLB)
                    Object.entries(s.by_sport).reduce((acc, [sp, sv]) => {
                      const key = sp.replace(/^baseball_/,'').replace(/^basketball_/,'').replace(/^icehockey_/,'').replace(/^auto_racing_/,'').toUpperCase().replace('MIXED_MARTIAL_ARTS','UFC').replace('PGA_CHAMPIONSHIP','PGA')
                      if (!acc[key]) acc[key] = { avg_clv: 0, beat_rate: 0, n: 0, _total_clv: 0, _beats: 0 }
                      acc[key]._total_clv += sv.avg_clv * sv.n
                      acc[key]._beats += sv.beat_rate * sv.n
                      acc[key].n += sv.n
                      acc[key].avg_clv = acc[key]._total_clv / acc[key].n
                      acc[key].beat_rate = acc[key]._beats / acc[key].n
                      return acc
                    }, {} as Record<string, { avg_clv: number; beat_rate: number; n: number; _total_clv: number; _beats: number }>)
                  ).sort((a,b) => b[1].n - a[1].n).map(([sp, sv]) => (
                    <tr key={sp} style={{ borderTop: '1px solid var(--border)' }}>
                      <td style={{ padding: '8px 0', color: 'var(--text)' }}>{sp}</td>
                      <td style={{ padding: '8px 0', textAlign: 'right', color: sv.avg_clv >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                        {sv.avg_clv >= 0 ? '+' : ''}{sv.avg_clv.toFixed(2)}%
                      </td>
                      <td style={{ padding: '8px 0', textAlign: 'right', color: sv.beat_rate >= 0.5 ? 'var(--green)' : 'var(--red)' }}>
                        {Math.round(sv.beat_rate * 100)}%
                      </td>
                      <td style={{ padding: '8px 0', textAlign: 'right', color: 'var(--text-muted)' }}>{sv.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
