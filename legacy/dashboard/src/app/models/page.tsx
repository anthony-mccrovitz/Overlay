'use client'
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'

interface ModelRow {
  key: string
  status: 'live' | 'incubating' | 'retired'
  label: string
  sport: string
  market: string
  wins: number
  losses: number
  pushes: number
  pending: number
  profit: number
  win_rate: number | null
  roi: number | null
  card_wins: number
  card_losses: number
  card_profit: number
  card_settled: number
  settled: number
}

interface Summary {
  live_count: number
  incubating_count: number
  card_wins: number
  card_losses: number
  card_profit: number
}

interface ApiResponse {
  models: ModelRow[]
  summary: Summary
}

function WinRate({ rate }: { rate: number | null }) {
  if (rate === null) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  const good = rate >= 52.4
  return <span style={{ color: good ? 'var(--green)' : 'var(--text-secondary)', fontWeight: 600 }}>{rate.toFixed(1)}%</span>
}

function Roi({ roi }: { roi: number | null }) {
  if (roi === null) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  return <span style={{ color: roi >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>{roi >= 0 ? '+' : ''}{roi.toFixed(1)}%</span>
}

function StatusBadge({ status }: { status: 'live' | 'incubating' }) {
  if (status === 'live') return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 999, fontSize: 10, fontWeight: 700,
      background: 'rgba(34,197,94,0.12)', color: 'var(--green)',
      border: '1px solid rgba(34,197,94,0.3)', letterSpacing: '0.05em',
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--green)', display: 'inline-block' }} />
      LIVE
    </span>
  )
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 999, fontSize: 10, fontWeight: 700,
      background: 'rgba(99,102,241,0.10)', color: 'var(--indigo)',
      border: '1px solid rgba(99,102,241,0.25)', letterSpacing: '0.05em',
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--indigo)', display: 'inline-block' }} />
      SHADOW
    </span>
  )
}

const SPORT_ORDER = ['NBA', 'MLB', 'NHL', 'WNBA', 'PGA', 'Tennis']

export default function ModelsPage() {
  const [data, setData] = useState<ApiResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'live' | 'incubating'>('all')

  useEffect(() => {
    fetch('/api/models').then(r => r.json()).then(d => { setData(d); setLoading(false) })
  }, [])

  const models = (data?.models || []).filter(m => filter === 'all' || m.status === filter)
  const s = data?.summary

  // Group by sport for section headers
  const grouped: Record<string, ModelRow[]> = {}
  for (const m of models) {
    if (!grouped[m.sport]) grouped[m.sport] = []
    grouped[m.sport].push(m)
  }
  const sportOrder = SPORT_ORDER.filter(s => grouped[s])
  const remaining = Object.keys(grouped).filter(s => !SPORT_ORDER.includes(s)).sort()

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-bright)', margin: '0 0 4px' }}>Models</h1>
        <p style={{ color: 'var(--text-muted)', margin: 0, fontSize: 12 }}>Live vs shadow model performance — all picks tracked, only live picks count publicly</p>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
          <Loader2 size={24} style={{ color: 'var(--indigo)', animation: 'spin 1s linear infinite' }} />
          <style>{`@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }`}</style>
        </div>
      ) : (
        <>
          {/* Summary cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 28 }}>
            <div className="stat-card" style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', marginBottom: 8 }}>OFFICIAL RECORD</div>
              <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text-bright)' }}>
                {s?.card_wins ?? 0}–{s?.card_losses ?? 0}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>card picks only</div>
            </div>
            <div className="stat-card" style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', marginBottom: 8 }}>OFFICIAL P&L</div>
              <div style={{ fontSize: 28, fontWeight: 800, color: (s?.card_profit ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>
                {(s?.card_profit ?? 0) >= 0 ? '+' : ''}{(s?.card_profit ?? 0).toFixed(1)}u
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>live models</div>
            </div>
            <div className="stat-card" style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', marginBottom: 8 }}>LIVE MODELS</div>
              <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--green)' }}>{s?.live_count ?? 0}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>posting publicly</div>
            </div>
            <div className="stat-card" style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', marginBottom: 8 }}>SHADOW MODELS</div>
              <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--indigo)' }}>{s?.incubating_count ?? 0}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>tracked silently</div>
            </div>
          </div>

          {/* Filter pills */}
          <div style={{ display: 'flex', gap: 4, background: 'var(--bg-raised)', border: '1px solid var(--border-hi)', borderRadius: 8, padding: 3, width: 'fit-content', marginBottom: 20 }}>
            {(['all', 'live', 'incubating'] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)} style={{
                padding: '4px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: 'none',
                background: filter === f ? 'var(--indigo)' : 'transparent',
                color: filter === f ? '#fff' : 'var(--text-secondary)',
              }}>
                {f === 'all' ? 'All' : f === 'live' ? 'Live' : 'Shadow'}
              </button>
            ))}
          </div>

          {/* Model tables by sport */}
          {[...sportOrder, ...remaining].map(sport => (
            <div key={sport} className="stat-card" style={{ marginBottom: 16, padding: 0, overflow: 'hidden' }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>{sport}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{grouped[sport].length} model{grouped[sport].length !== 1 ? 's' : ''}</span>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ color: 'var(--text-muted)', fontSize: 10, fontWeight: 600, letterSpacing: '0.05em' }}>
                    <th style={{ textAlign: 'left', padding: '8px 16px', borderBottom: '1px solid var(--border)' }}>MODEL</th>
                    <th style={{ textAlign: 'center', padding: '8px 12px', borderBottom: '1px solid var(--border)' }}>STATUS</th>
                    <th style={{ textAlign: 'right', padding: '8px 12px', borderBottom: '1px solid var(--border)' }}>RECORD</th>
                    <th style={{ textAlign: 'right', padding: '8px 12px', borderBottom: '1px solid var(--border)' }}>WIN%</th>
                    <th style={{ textAlign: 'right', padding: '8px 12px', borderBottom: '1px solid var(--border)' }}>ROI</th>
                    <th style={{ textAlign: 'right', padding: '8px 16px', borderBottom: '1px solid var(--border)' }}>PROFIT</th>
                    <th style={{ textAlign: 'right', padding: '8px 16px', borderBottom: '1px solid var(--border)' }}>PENDING</th>
                  </tr>
                </thead>
                <tbody>
                  {grouped[sport].map((m, i) => (
                    <tr key={m.key} style={{
                      background: m.status === 'live' ? 'rgba(34,197,94,0.04)' : 'transparent',
                      borderTop: i === 0 ? 'none' : '1px solid var(--border)',
                    }}>
                      <td style={{ padding: '10px 16px', color: m.status === 'live' ? 'var(--text-bright)' : 'var(--text-secondary)', fontWeight: m.status === 'live' ? 600 : 400 }}>
                        {m.label}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        {m.status !== 'retired' && <StatusBadge status={m.status as 'live' | 'incubating'} />}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--text)' }}>
                        {m.settled > 0 ? `${m.wins}–${m.losses}${m.pushes > 0 ? `–${m.pushes}` : ''}` : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                        <WinRate rate={m.win_rate} />
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                        <Roi roi={m.roi} />
                      </td>
                      <td style={{ padding: '10px 16px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: m.profit >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 500 }}>
                        {m.settled > 0 ? `${m.profit >= 0 ? '+' : ''}${m.profit.toFixed(1)}u` : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                      </td>
                      <td style={{ padding: '10px 16px', textAlign: 'right', color: 'var(--text-muted)', fontSize: 12 }}>
                        {m.pending > 0 ? m.pending : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}

          {/* Explanation */}
          <div style={{ padding: '14px 16px', background: 'var(--bg-raised)', borderRadius: 8, border: '1px solid var(--border)', fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
            <strong style={{ color: 'var(--text-secondary)' }}>How this works:</strong> Every pick generated goes into the record.{' '}
            <span style={{ color: 'var(--green)', fontWeight: 600 }}>Live</span> models post publicly and count toward the official W-L.{' '}
            <span style={{ color: 'var(--indigo)', fontWeight: 600 }}>Shadow</span> models are tracked silently — picks are generated and graded but not posted.{' '}
            A model graduates from shadow → live in <code style={{ background: 'var(--bg)', padding: '1px 4px', borderRadius: 3 }}>src/config/models.py</code> once it proves edge.
          </div>
        </>
      )}
    </div>
  )
}
