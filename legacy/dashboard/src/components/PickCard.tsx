'use client'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import type { NormalizedPick } from '@/app/picks/page'

function fmtOdds(o: number) {
  if (o == null || isNaN(o)) return '—'
  return o > 0 ? `+${o}` : `${o}`
}

function impliedProb(odds: number): number {
  if (odds > 0) return 100 / (odds + 100)
  return Math.abs(odds) / (Math.abs(odds) + 100)
}

function edgeTier(edge: number | null | undefined): string {
  if (edge == null) return 'low'
  if (edge >= 10) return 'hot'
  if (edge >= 6) return 'high'
  if (edge >= 3) return 'med'
  return 'low'
}

function mktClass(market: string): string {
  if (market === 'moneyline') return 'ml'
  if (market === 'spread' || market === 'runline') return 'rl'
  if (market === 'total') return 'ou'
  if (market === 'nrfi' || market === 'yrfi') return 'nrfi'
  return 'prop'
}

function mktLabel(market: string, line?: number | null): string {
  const map: Record<string, string> = {
    moneyline: 'ML', spread: 'RL', runline: 'RL', total: 'O/U',
    nrfi: 'NRFI', yrfi: 'YRFI', win: 'WIN',
    pitcher_strikeouts: 'K Props', batter_hits: 'H Props',
    batter_total_bases: 'TB Props', batter_home_runs: 'HR Props',
    player_points: 'Pts', player_rebounds: 'Reb', player_assists: 'Ast',
    player_threes: '3PT', player_steals: 'STL', player_blocks: 'BLK',
    player_points_rebounds_assists: 'PRA',
    f5_total: 'F5 O/U', f5_moneyline: 'F5 ML',
  }
  const l = map[market] || market.replace(/_/g,' ').replace(/\b\w/g, c => c.toUpperCase())
  return line != null ? `${l} ${line}` : l
}

export default function PickCard({ pick }: { pick: NormalizedPick }) {
  const [expanded, setExpanded] = useState(false)

  const implied = pick.implied_prob ?? impliedProb(pick.odds)
  const modelP = pick.model_prob ?? null
  const tier = edgeTier(pick.edge_pct)
  const mc = mktClass(pick.market)

  const resultColor = pick.result === 'win' ? 'var(--green)'
    : pick.result === 'loss' ? 'var(--red)'
    : pick.result === 'push' ? 'var(--amber)' : undefined

  const primaryLabel = pick.label || pick.direction || pick.team
  // Don't show secondary if it's just OVER/UNDER (already in label) or same as primary
  const isRedundantDirection = ['OVER','UNDER','WIN','LOSE'].includes((pick.direction || '').toUpperCase())
  const secondaryLabel = (!isRedundantDirection && pick.label && pick.direction && pick.label !== pick.direction)
    ? pick.direction
    : (!isRedundantDirection && pick.team && pick.team !== primaryLabel ? pick.team : null)

  return (
    <div className="pick-card" style={{ padding: '14px 16px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {pick.matchup && pick.matchup !== primaryLabel && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {pick.matchup}
            </div>
          )}
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-bright)', lineHeight: 1.2 }}>
            {primaryLabel}
          </div>
          {secondaryLabel && (
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>{secondaryLabel}</div>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, marginLeft: 12, flexShrink: 0 }}>
          <div style={{
            fontSize: 20, fontWeight: 800, fontVariantNumeric: 'tabular-nums',
            color: pick.odds > 0 ? 'var(--green)' : 'var(--text-bright)',
          }}>
            {fmtOdds(pick.odds)}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{pick.sportsbook}</div>
        </div>
      </div>

      {/* Badges */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: modelP ? 10 : 8 }}>
        <span className={`mkt-badge ${mc}`}>{mktLabel(pick.market, pick.line)}</span>
        {pick.edge_pct != null && (
          <span className={`edge-badge ${tier}`}>
            {pick.edge_pct > 0 ? '+' : ''}{pick.edge_pct.toFixed(1)}% edge
          </span>
        )}
        {pick.result && (
          <span style={{ padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 700, color: resultColor, background: resultColor ? `${resultColor}22` : 'transparent', border: `1px solid ${resultColor || 'transparent'}` }}>
            {pick.result.toUpperCase()}{pick.profit != null ? ` ${pick.profit > 0 ? '+' : ''}${pick.profit.toFixed(2)}u` : ''}
          </span>
        )}
      </div>

      {/* Probability bar */}
      {modelP != null && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
            <span>Model {(modelP * 100).toFixed(1)}%</span>
            <span>Implied {(implied * 100).toFixed(1)}%</span>
          </div>
          <div className="prob-track" style={{ position: 'relative' }}>
            <div className="prob-fill" style={{ width: `${Math.min(modelP * 100, 100)}%` }} />
          </div>
          <div style={{ position: 'relative', height: 0 }}>
            <div style={{ position: 'absolute', left: `${Math.min(implied * 100, 100)}%`, top: -9, width: 2, height: 12, background: 'var(--text-muted)', borderRadius: 1, transform: 'translateX(-50%)' }} />
          </div>
        </div>
      )}

      {/* Why / notes expandable */}
      {pick.why && (
        <div>
          <button onClick={() => setExpanded(e => !e)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, marginTop: modelP ? 6 : 0 }}>
            {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            {expanded ? 'Hide' : 'Why this pick'}
          </button>
          {expanded && (
            <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 6, padding: '8px 10px', background: 'var(--bg)', borderRadius: 6, lineHeight: 1.5 }}>
              {pick.why}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
