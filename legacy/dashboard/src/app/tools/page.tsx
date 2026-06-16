'use client'
import { useState, useMemo } from 'react'
import { Plus, Trash2 } from 'lucide-react'

function toDecimal(american: number): number {
  if (american > 0) return american / 100 + 1
  return 100 / Math.abs(american) + 1
}

function toAmerican(decimal: number): string {
  const implied = 1 / decimal
  if (implied >= 0.5) return `-${Math.round((implied / (1-implied)) * 100)}`
  return `+${Math.round(((1-implied)/implied) * 100)}`
}

function impliedProb(american: number): number {
  if (american > 0) return 100 / (american + 100)
  return Math.abs(american) / (Math.abs(american) + 100)
}

function Input({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.05em', display: 'block', marginBottom: 5 }}>{label}</label>
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--border-hi)', color: 'var(--text-bright)', borderRadius: 8, padding: '8px 12px', fontSize: 14, outline: 'none', fontVariantNumeric: 'tabular-nums' }} />
    </div>
  )
}

function ResultRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
      <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 700, color: color || 'var(--text-bright)', fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}

function EvCalc() {
  const [odds, setOdds] = useState('-110')
  const [prob, setProb] = useState('55')

  const results = useMemo(() => {
    const o = parseInt(odds)
    const p = parseFloat(prob) / 100
    if (isNaN(o) || isNaN(p) || p <= 0 || p >= 1) return null
    const implied = impliedProb(o)
    const edge = (p - implied) * 100
    const dec = toDecimal(o)
    const ev = (p * (dec - 1) - (1 - p)) * 100
    const kelly = edge > 0 ? edge / ((dec - 1) * 100) * 100 : 0
    return { implied: (implied * 100).toFixed(1), edge: edge.toFixed(2), ev: ev.toFixed(2), kelly: kelly.toFixed(1) }
  }, [odds, prob])

  return (
    <div className="stat-card">
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)', marginBottom: 16 }}>EV Calculator</div>
      <Input label="AMERICAN ODDS" value={odds} onChange={setOdds} placeholder="-110" />
      <Input label="MODEL PROBABILITY %" value={prob} onChange={setProb} placeholder="55" />
      {results && (
        <div style={{ marginTop: 16 }}>
          <ResultRow label="Implied Prob" value={`${results.implied}%`} />
          <ResultRow label="Edge" value={`${Number(results.edge) >= 0 ? '+' : ''}${results.edge}%`} color={Number(results.edge) >= 0 ? 'var(--green)' : 'var(--red)'} />
          <ResultRow label="EV per $100" value={`$${Number(results.ev) >= 0 ? '+' : ''}${results.ev}`} color={Number(results.ev) >= 0 ? 'var(--green)' : 'var(--red)'} />
          <ResultRow label="Kelly Fraction" value={`${results.kelly}%`} color='var(--cyan)' />
        </div>
      )}
    </div>
  )
}

function ClvCalc() {
  const [open, setOpen] = useState('+120')
  const [close, setClose] = useState('+100')

  const results = useMemo(() => {
    const o = parseInt(open)
    const c = parseInt(close)
    if (isNaN(o) || isNaN(c)) return null
    const openImpl = impliedProb(o)
    const closeImpl = impliedProb(c)
    const clv = (closeImpl - openImpl) * 100
    return { openImpl: (openImpl*100).toFixed(1), closeImpl: (closeImpl*100).toFixed(1), clv: clv.toFixed(2) }
  }, [open, close])

  return (
    <div className="stat-card">
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)', marginBottom: 16 }}>CLV Calculator</div>
      <Input label="OPENING ODDS (American)" value={open} onChange={setOpen} placeholder="+120" />
      <Input label="CLOSING ODDS (American)" value={close} onChange={setClose} placeholder="+100" />
      {results && (
        <div style={{ marginTop: 16 }}>
          <ResultRow label="Opening Implied" value={`${results.openImpl}%`} />
          <ResultRow label="Closing Implied" value={`${results.closeImpl}%`} />
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 12px', borderRadius: 8, marginTop: 8, background: Number(results.clv) >= 0 ? 'var(--red-dim)' : 'var(--green-dim)', border: `1px solid ${Number(results.clv) >= 0 ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)'}` }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>CLV%</span>
            <span style={{ fontSize: 15, fontWeight: 800, color: Number(results.clv) >= 0 ? 'var(--red)' : 'var(--green)' }}>
              {Number(results.clv) >= 0 ? '+' : ''}{results.clv}%
              {Number(results.clv) >= 0 ? ' (missed close)' : ' (beat close)'}
            </span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
            Negative CLV = market moved in your favor after you bet = you beat the close
          </div>
        </div>
      )}
    </div>
  )
}

interface Leg { id: number; desc: string; odds: string }

function ParlayBuilder() {
  const [legs, setLegs] = useState<Leg[]>([{ id: 1, desc: '', odds: '' }])

  const addLeg = () => {
    if (legs.length >= 10) return
    setLegs(l => [...l, { id: Date.now(), desc: '', odds: '' }])
  }

  const removeLeg = (id: number) => setLegs(l => l.filter(x => x.id !== id))
  const updateLeg = (id: number, field: 'desc' | 'odds', v: string) =>
    setLegs(l => l.map(x => x.id === id ? { ...x, [field]: v } : x))

  const results = useMemo(() => {
    const validLegs = legs.filter(l => l.odds.trim() !== '')
    if (validLegs.length < 2) return null
    const decimals = validLegs.map(l => toDecimal(parseInt(l.odds))).filter(d => !isNaN(d) && d > 1)
    if (decimals.length < 2) return null
    const combinedDec = decimals.reduce((a, b) => a * b, 1)
    const combinedAmerican = toAmerican(combinedDec)
    const payout = (combinedDec - 1) * 100
    return { combined: combinedAmerican, payout: payout.toFixed(0), legs: decimals.length }
  }, [legs])

  return (
    <div className="stat-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>Parlay Builder</div>
        <button onClick={addLeg} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: 'pointer', background: 'var(--indigo-dim)', border: '1px solid rgba(99,102,241,0.3)', color: 'var(--indigo)' }}>
          <Plus size={12} /> Add Leg
        </button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {legs.map((leg, i) => (
          <div key={leg.id} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', width: 16, flexShrink: 0 }}>#{i+1}</span>
            <input value={leg.desc} onChange={e => updateLeg(leg.id, 'desc', e.target.value)} placeholder="Pick description"
              style={{ flex: 1, background: 'var(--bg)', border: '1px solid var(--border-hi)', color: 'var(--text)', borderRadius: 6, padding: '6px 10px', fontSize: 12 }} />
            <input value={leg.odds} onChange={e => updateLeg(leg.id, 'odds', e.target.value)} placeholder="Odds"
              style={{ width: 72, background: 'var(--bg)', border: '1px solid var(--border-hi)', color: 'var(--text)', borderRadius: 6, padding: '6px 10px', fontSize: 12, textAlign: 'center' }} />
            {legs.length > 1 && (
              <button onClick={() => removeLeg(leg.id)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 4 }}>
                <Trash2 size={13} />
              </button>
            )}
          </div>
        ))}
      </div>
      {results && (
        <div style={{ marginTop: 16, padding: '12px', background: 'var(--bg)', borderRadius: 8, border: '1px solid var(--border-hi)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Combined odds ({results.legs} legs)</span>
            <span style={{ fontSize: 16, fontWeight: 800, color: 'var(--green)' }}>{results.combined}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>$100 payout</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)' }}>${results.payout}</span>
          </div>
        </div>
      )}
    </div>
  )
}

function OddsConverter() {
  const [input, setInput] = useState('-110')
  const [mode, setMode] = useState<'american' | 'decimal' | 'fraction' | 'implied'>('american')

  const results = useMemo(() => {
    const v = input.trim()
    if (!v) return null

    let americanVal: number | null = null
    let decimalVal: number | null = null

    if (mode === 'american') {
      const n = parseInt(v)
      if (isNaN(n) || n === 0 || n === -100 || n === 100) return null
      americanVal = n
      decimalVal = n > 0 ? n / 100 + 1 : 100 / Math.abs(n) + 1
    } else if (mode === 'decimal') {
      const n = parseFloat(v)
      if (isNaN(n) || n <= 1) return null
      decimalVal = n
      const prob = 1 / n
      americanVal = prob >= 0.5 ? -Math.round((prob / (1-prob)) * 100) : Math.round(((1-prob)/prob) * 100)
    } else if (mode === 'fraction') {
      const parts = v.split(/[\/\-]/)
      if (parts.length !== 2) return null
      const [num, den] = parts.map(Number)
      if (isNaN(num) || isNaN(den) || den === 0) return null
      decimalVal = num / den + 1
      const prob = 1 / decimalVal
      americanVal = prob >= 0.5 ? -Math.round((prob / (1-prob)) * 100) : Math.round(((1-prob)/prob) * 100)
    } else {
      const n = parseFloat(v)
      if (isNaN(n) || n <= 0 || n >= 100) return null
      const prob = n / 100
      americanVal = prob >= 0.5 ? -Math.round((prob / (1-prob)) * 100) : Math.round(((1-prob)/prob) * 100)
      decimalVal = 1 / prob
    }

    if (!decimalVal || !americanVal) return null
    const prob = 1 / decimalVal
    const num = Math.round((decimalVal - 1) * 10)
    const den = 10
    const gcd = (a: number, b: number): number => b === 0 ? a : gcd(b, a % b)
    const g = gcd(num, den)

    return {
      american: americanVal > 0 ? `+${americanVal}` : `${americanVal}`,
      decimal: decimalVal.toFixed(3),
      fraction: `${num/g}/${den/g}`,
      implied: (prob * 100).toFixed(2) + '%',
      vig_free: ((prob / (prob + (1 - prob))) * 100).toFixed(2) + '%',
    }
  }, [input, mode])

  const MODES = [
    { key: 'american', label: 'American' },
    { key: 'decimal', label: 'Decimal' },
    { key: 'fraction', label: 'Fraction' },
    { key: 'implied', label: 'Implied %' },
  ] as const

  return (
    <div className="stat-card">
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-bright)', marginBottom: 14 }}>Odds Converter</div>

      {/* Input format toggle */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 12, background: 'var(--bg)', border: '1px solid var(--border-hi)', borderRadius: 8, padding: 3 }}>
        {MODES.map(m => (
          <button key={m.key} onClick={() => { setMode(m.key); setInput('') }} style={{
            flex: 1, padding: '4px 0', borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: 'pointer', border: 'none',
            background: mode === m.key ? 'var(--indigo)' : 'transparent',
            color: mode === m.key ? '#fff' : 'var(--text-secondary)',
          }}>{m.label}</button>
        ))}
      </div>

      <Input
        label={`ENTER ${mode.toUpperCase()} ODDS`}
        value={input}
        onChange={setInput}
        placeholder={mode === 'american' ? '-110' : mode === 'decimal' ? '1.909' : mode === 'fraction' ? '10/11' : '52.38'}
      />

      {results ? (
        <div style={{ marginTop: 12 }}>
          {mode !== 'american' && <ResultRow label="American" value={results.american} color="var(--cyan)" />}
          {mode !== 'decimal' && <ResultRow label="Decimal" value={results.decimal} />}
          {mode !== 'fraction' && <ResultRow label="Fraction" value={results.fraction} />}
          {mode !== 'implied' && <ResultRow label="Implied Prob" value={results.implied} />}
          <div style={{ marginTop: 8, padding: '8px 10px', background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 600, letterSpacing: '0.05em' }}>QUICK REFERENCE</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, fontSize: 11 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Break-even win%</span>
              <span style={{ color: 'var(--text-bright)', fontWeight: 600, textAlign: 'right' }}>{results.implied}</span>
              <span style={{ color: 'var(--text-secondary)' }}>$100 to win</span>
              <span style={{ color: 'var(--green)', fontWeight: 600, textAlign: 'right' }}>
                ${results.american.startsWith('+') ? results.american.slice(1) : (100 / Math.abs(parseInt(results.american)) * 100).toFixed(0)}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
          {mode === 'american' && 'Enter American odds e.g. -110 or +150'}
          {mode === 'decimal' && 'Enter decimal odds e.g. 1.909 (must be > 1)'}
          {mode === 'fraction' && 'Enter fraction e.g. 10/11 or 3/1'}
          {mode === 'implied' && 'Enter implied probability e.g. 52.38 (no %)'}
        </div>
      )}
    </div>
  )
}

export default function ToolsPage() {
  return (
    <div style={{ maxWidth: 960 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-bright)', margin: '0 0 4px' }}>Tools</h1>
        <p style={{ color: 'var(--text-muted)', margin: 0, fontSize: 12 }}>EV calc · CLV calc · Odds converter · Parlay builder</p>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
        <EvCalc />
        <ClvCalc />
        <OddsConverter />
        <ParlayBuilder />
      </div>
    </div>
  )
}
