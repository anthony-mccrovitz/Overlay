import { NextRequest, NextResponse } from 'next/server'
import { readFile } from 'fs/promises'
import path from 'path'

export const revalidate = 300

const ROOT = path.join(process.cwd(), '..')

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams
  const sport = sp.get('sport') || 'all'
  const days = parseInt(sp.get('days') || '90')

  let snapshots: Record<string, unknown>[] = []
  try {
    const raw = await readFile(path.join(ROOT, 'data', 'clv', 'snapshots.json'), 'utf-8')
    snapshots = JSON.parse(raw)
  } catch { snapshots = [] }

  const cutoff = new Date()
  cutoff.setDate(cutoff.getDate() - days)

  const filtered = snapshots.filter((s: Record<string, unknown>) => {
    if (s.clv_pct === null || s.clv_pct === undefined) return false
    if (sport !== 'all' && s.sport !== sport) return false
    if (s.date) {
      const d = new Date(s.date as string)
      if (!isNaN(d.getTime()) && days < 9999 && d < cutoff) return false
    }
    return true
  })

  const bySport: Record<string, { total_clv: number; n: number; beats: number }> = {}
  for (const s of filtered) {
    const sp = (s.sport as string) || 'unknown'
    if (!bySport[sp]) bySport[sp] = { total_clv: 0, n: 0, beats: 0 }
    bySport[sp].total_clv += (s.clv_pct as number) || 0
    bySport[sp].n++
    if ((s.clv_pct as number) > 0) bySport[sp].beats++
  }

  const totalClv = filtered.reduce((acc, s) => acc + ((s.clv_pct as number) || 0), 0)
  const beats = filtered.filter(s => (s.clv_pct as number) > 0).length

  return NextResponse.json({
    snapshots: filtered,
    summary: {
      avg_clv_pct: filtered.length > 0 ? Math.round((totalClv / filtered.length) * 1000) / 1000 : 0,
      beat_close_rate: filtered.length > 0 ? Math.round((beats / filtered.length) * 1000) / 1000 : 0,
      n: filtered.length,
      by_sport: Object.fromEntries(Object.entries(bySport).map(([k, v]) => [k, {
        avg_clv: v.n > 0 ? Math.round((v.total_clv / v.n) * 1000) / 1000 : 0,
        beat_rate: v.n > 0 ? Math.round((v.beats / v.n) * 1000) / 1000 : 0,
        n: v.n,
      }]))
    }
  })
}
