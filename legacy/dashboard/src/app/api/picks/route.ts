import { NextRequest, NextResponse } from 'next/server'
import { readdir, readFile } from 'fs/promises'
import path from 'path'

export const revalidate = 300

const ROOT = path.join(process.cwd(), '..')

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams
  const today = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const defaultDate = `${today.getFullYear()}${pad(today.getMonth()+1)}${pad(today.getDate())}`
  const date = sp.get('date') || defaultDate

  const picksDir = path.join(ROOT, 'output', 'picks')
  const result: Record<string, Record<string, unknown[]>> = {}

  try {
    const sports = await readdir(picksDir)
    for (const sport of sports) {
      const sportDateDir = path.join(picksDir, sport, date)
      try {
        const files = await readdir(sportDateDir)
        result[sport] = {}
        for (const file of files) {
          if (!file.endsWith('.json')) continue
          const key = file.replace('.json', '')
          try {
            const raw = await readFile(path.join(sportDateDir, file), 'utf-8')
            const parsed = JSON.parse(raw)
            // Normalize: unwrap { picks: [...] } or { date, sport, picks: [...] } wrappers
            if (Array.isArray(parsed)) {
              result[sport][key] = parsed
            } else if (parsed && Array.isArray(parsed.picks)) {
              result[sport][key] = parsed.picks
            } else if (parsed && typeof parsed === 'object') {
              // dict of objects (e.g. sim_summary) — skip, not iterable picks
              result[sport][key] = []
            } else {
              result[sport][key] = []
            }
          } catch { result[sport][key] = [] }
        }
      } catch { /* no picks for this sport/date */ }
    }
  } catch { /* no picks dir */ }

  return NextResponse.json({ date, sports: result })
}
