'use client'
import { Star } from 'lucide-react'
import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import type { NormalizedPick } from '@/app/picks/page'

function fmtOdds(o: number) {
  if (o == null || isNaN(o)) return '—'
  return o > 0 ? `+${o}` : `${o}`
}

function impliedProb(odds: number): number {
  if (odds > 0) return 100 / (odds + 100)
  return Math.abs(odds) / (Math.abs(odds) + 100)
}

const SPORT_LABELS: Record<string, string> = {
  baseball_mlb: 'MLB', basketball_nba: 'NBA', basketball_wnba: 'WNBA',
  icehockey_nhl: 'NHL', auto_racing_indycar_series: 'IndyCar',
  golf_pga: 'PGA', golf_pga_championship: 'PGA',
  mlb: 'MLB', nba: 'NBA',
}
function sportLabel(key: string) {
  if (SPORT_LABELS[key]) return SPORT_LABELS[key]
  if (key.startsWith('tennis_')) return 'Tennis'
  if (key.startsWith('soccer_')) return 'Soccer'
  return key.replace(/_/g, ' ').toUpperCase()
}

function mktLabel(market: string, line?: number | null): string {
  const map: Record<string, string> = {
    moneyline: 'ML', spread: 'RL', runline: 'RL', total: 'O/U',
    nrfi: 'NRFI', yrfi: 'YRFI', f5_total: 'F5 O/U',
    pitcher_strikeouts: 'K Props', batter_hits: 'H Props',
    batter_total_bases: 'TB Props', batter_home_runs: 'HR Props',
    player_points: 'Pts', player_rebounds: 'Reb', player_assists: 'Ast',
    player_threes: '3PT', player_steals: 'STL', player_blocks: 'BLK',
    player_points_rebounds_assists: 'PRA',
  }
  const l = map[market] || market.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  return line != null ? `${l} ${line}` : l
}

export default function PickOfTheDay({ pick }: { pick: NormalizedPick }) {
  const [expanded, setExpanded] = useState(false)

  const implied = pick.implied_prob ?? impliedProb(pick.odds)
  const modelP = pick.model_prob ?? null
  const edge = pick.edge_pct ?? 0
  const isLive = pick.card_pick

  const primaryLabel = pick.label || pick.direction || pick.team

  return (
    <div style={{
      marginBottom: 24,
      borderRadius: 12,
      border: '1px solid',
      borderColor: isLive ? 'rgba(34,197,94,0.35)' : 'rgba(99,102,241,0.35)',
      background: isLive
        ? 'linear-gradient(135deg, rgba(34,197,94,0.07) 0%, rgba(7,9,15,0) 60%)'
        : 'linear-gradient(135deg, rgba(99,102,241,0.08) 0%, rgba(7,9,15,0) 60%)',
      padding: '20px 24px',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Background glow */}
      <div style={{
        position: 'absolute', top: -40, right: -40, width: 160, height: 160,
        borderRadius: '50%',
        background: isLive ? 'rgba(34,197,94,0.07)' : 'rgba(99,102,241,0.07)',
        filter: 'blur(40px)',
        pointerEvents: 'none',
      }} />

      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <Star size={13} style={{ color: isLive ? 'var(--green)' : 'var(--indigo)', fill: isLive ? 'var(--green)' : 'var(--indigo)' }} />
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: isLive ? 'var(--green)' : 'var(--indigo)', textTransform: 'uppercase' }}>
          Pick of the Day
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>
          {sportLabel(pick.sport)} · {mktLabel(pick.market, pick.line)}
        </span>
        {isLive && (
          <span style={{
            marginLeft: 'auto', fontSize: 10, fontWeight: 700, letterSpacing: '0.05em',
            padding: '2px 8px', borderRadius: 999,
            background: 'rgba(34,197,94,0.12)', color: 'var(--green)',
            border: '1px solid rgba(34,197,94,0.3)',
          }}>LIVE MODEL</span>
        )}
        {!isLive && (
          <span style={{
            marginLeft: 'auto', fontSize: 10, fontWeight: 700, letterSpacing: '0.05em',
            padding: '2px 8px', borderRadius: 999,
            background: 'rgba(99,102,241,0.10)', color: 'var(--indigo)',
            border: '1px solid rgba(99,102,241,0.25)',
          }}>SHADOW</span>
        )}
      </div>

      {/* Main content */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {pick.matchup && pick.matchup !== primaryLabel && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>{pick.matchup}</div>
          )}
          <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--text-bright)', lineHeight: 1.15, marginBottom: 6 }}>
            {primaryLabel}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{
              fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
              color: pick.odds > 0 ? 'var(--green)' : 'var(--text-bright)',
            }}>
              {fmtOdds(pick.odds)}
            </span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{pick.sportsbook}</span>
            <span style={{
              padding: '2px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700,
              background: edge >= 10 ? 'rgba(251,191,36,0.15)' : edge >= 6 ? 'rgba(34,197,94,0.12)' : 'rgba(99,102,241,0.1)',
              color: edge >= 10 ? 'var(--amber)' : edge >= 6 ? 'var(--green)' : 'var(--indigo)',
              border: `1px solid ${edge >= 10 ? 'rgba(251,191,36,0.3)' : edge >= 6 ? 'rgba(34,197,94,0.3)' : 'rgba(99,102,241,0.25)'}`,
            }}>
              +{edge.toFixed(1)}% edge
            </span>
          </div>
        </div>

        {/* Edge dial */}
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontSize: 40, fontWeight: 900, lineHeight: 1, fontVariantNumeric: 'tabular-nums',
            color: edge >= 10 ? 'var(--amber)' : edge >= 6 ? 'var(--green)' : 'var(--indigo)' }}>
            +{edge.toFixed(1)}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2, letterSpacing: '0.05em' }}>% EDGE</div>
        </div>
      </div>

      {/* Probability bar */}
      {modelP != null && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 5 }}>
            <span>Model probability: <strong style={{ color: 'var(--text-secondary)' }}>{(modelP * 100).toFixed(1)}%</strong></span>
            <span>Market implied: <strong style={{ color: 'var(--text-secondary)' }}>{(implied * 100).toFixed(1)}%</strong></span>
          </div>
          <div style={{ height: 6, background: 'var(--bg-raised)', borderRadius: 999, overflow: 'hidden', position: 'relative' }}>
            <div style={{ position: 'absolute', inset: 0, width: `${Math.min(modelP * 100, 100)}%`,
              background: isLive ? 'var(--green)' : 'var(--indigo)', borderRadius: 999, opacity: 0.7 }} />
          </div>
          <div style={{ position: 'relative', height: 0 }}>
            <div style={{
              position: 'absolute', left: `${Math.min(implied * 100, 100)}%`, top: -7,
              width: 2, height: 10, background: 'var(--text-muted)', borderRadius: 1, transform: 'translateX(-50%)'
            }} />
          </div>
        </div>
      )}

      {/* Why expandable */}
      {pick.why && (
        <div style={{ marginTop: modelP != null ? 14 : 16 }}>
          <button onClick={() => setExpanded(e => !e)} style={{
            background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer',
            padding: 0, display: 'flex', alignItems: 'center', gap: 4, fontSize: 12,
          }}>
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? 'Hide reasoning' : 'Why this pick'}
          </button>
          {expanded && (
            <div style={{
              fontSize: 12, color: 'var(--text-secondary)', marginTop: 8,
              padding: '10px 14px', background: 'var(--bg)', borderRadius: 8, lineHeight: 1.6,
            }}>
              {pick.why}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
