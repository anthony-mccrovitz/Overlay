"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { WCFixture, WCScorer, pct, odds, code, clock } from "@/lib/wc";
import { Flag } from "@/components/wc/Flag";
import { IconHost, IconAltitude, IconPenalty, IconLock } from "@/components/wc/Icons";

const FREE_SCORERS = 2;  // teaser: show this many, gate the rest behind the Pass

/* 3-way probability bar (H / D / A) */
function ProbBar({ p }: { p: { home_win: number; draw: number; away_win: number } }) {
  const seg = [
    { v: p.home_win, c: "var(--accent)" },
    { v: p.draw,     c: "var(--text-muted)" },
    { v: p.away_win, c: "#0EA98F" },
  ];
  return (
    <div style={{ display: "flex", height: 22, borderRadius: 5, overflow: "hidden", background: "var(--bg-overlay)" }}>
      {seg.map((s, i) => (
        <div key={i} style={{ width: `${s.v * 100}%`, background: s.c, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, color: "#fff" }}>
          {s.v > 0.12 ? pct(s.v) : ""}
        </div>
      ))}
    </div>
  );
}

function Chip({ children, tone }: { children: React.ReactNode; tone: "alt" | "host" }) {
  const c = tone === "alt"
    ? { bg: "rgba(245,158,11,0.12)", bd: "rgba(245,158,11,0.35)", fg: "var(--amber)" }
    : { bg: "var(--green-dim)", bd: "rgba(34,197,94,0.3)", fg: "var(--green-hi)" };
  return (
    <span style={{ fontSize: 10, fontWeight: 700, background: c.bg, border: `1px solid ${c.bd}`, color: c.fg, borderRadius: 6, padding: "3px 8px", whiteSpace: "nowrap" }}>{children}</span>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.1em", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 8 }}>{children}</div>;
}

function Row3({ label, p, prices, accent }: { label: string; p: { home_win: number; draw: number; away_win: number }; prices?: { home: number; away: number; draw: number }; accent?: boolean }) {
  const cell = (v: number, o?: number) => (
    <td style={{ textAlign: "center", padding: "5px 4px", fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 700, color: accent ? "var(--accent-hi)" : "var(--text-bright)" }}>
      {pct(v)}{o != null && <span style={{ display: "block", fontSize: 9, color: "var(--text-muted)", fontWeight: 500 }}>{odds(o)}</span>}
    </td>
  );
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <tbody><tr>
        <td style={{ fontSize: 11, color: "var(--text-secondary)", width: 56 }}>{label}</td>
        {cell(p.home_win, prices?.home)}{cell(p.draw, prices?.draw)}{cell(p.away_win, prices?.away)}
      </tr></tbody>
    </table>
  );
}

function Stat({ label, val, sub }: { label: string; val: string; sub?: string }) {
  return (
    <div style={{ background: "var(--bg-raised)", border: "1px solid var(--border)", borderRadius: 8, padding: 10, textAlign: "center" }}>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-muted)", textTransform: "uppercase" }}>{label}</div>
      <div className="mono" style={{ fontWeight: 800, fontSize: 16, marginTop: 4, color: "var(--text-bright)" }}>{val}</div>
      {sub && <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function Scorers({ team, rows }: { team: string; rows: WCScorer[] }) {
  return (
    <div>
      <Label>{team} — anytime scorer</Label>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {rows.slice(0, FREE_SCORERS).map(s => (
          <div key={s.player} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: "var(--text-bright)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {s.player}{s.pen_rate >= 0.25 ? <IconPenalty size={11} color="var(--amber)" style={{ marginLeft: 4, verticalAlign: "middle" }} /> : null}
            </span>
            <span className="mono" style={{ fontSize: 12, fontWeight: 800, color: "var(--green-hi)" }}>{pct(s.anytime_prob)}</span>
          </div>
        ))}
        {rows.length > FREE_SCORERS && (
          <Link href="/world-cup/pass" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 6, marginTop: 3, padding: "5px 8px", borderRadius: 6, background: "var(--accent-dim)", border: "1px dashed rgba(18,197,138,0.4)" }}>
            <IconLock size={11} color="var(--accent-hi)" />
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--accent-hi)" }}>+{rows.length - FREE_SCORERS} more · unlock with the $9 Pass</span>
          </Link>
        )}
        {rows.length === 0 && <span style={{ fontSize: 11, color: "var(--text-muted)" }}>No recent scorer data</span>}
      </div>
    </div>
  );
}

function FixtureCard({ f }: { f: WCFixture }) {
  const [open, setOpen] = useState(false);
  const display = f.blend ?? f.model;
  const maxScore = Math.max(...f.top_scores.map(s => s.prob), 0.001);
  return (
    <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 14, overflow: "hidden" }}>
      <button onClick={() => setOpen(o => !o)} style={{ width: "100%", textAlign: "left", background: "transparent", border: "none", cursor: "pointer", padding: "14px 16px", color: "var(--text-bright)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)" }}>{clock(f.time)}</span>
          <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.08em", background: "var(--accent-dim)", color: "var(--accent-hi)", borderRadius: 4, padding: "2px 6px" }}>GRP {f.group}</span>
          <span style={{ flex: 1 }} />
          {f.edge && f.edge.pp >= 3 && (
            <span style={{ fontSize: 10, fontWeight: 800, background: "var(--green-dim)", border: "1px solid rgba(34,197,94,0.3)", color: "var(--green-hi)", borderRadius: 5, padding: "2px 7px" }}>
              EDGE {f.edge.side.toUpperCase()} +{f.edge.pp}pp
            </span>
          )}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 12, alignItems: "center" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
              <Flag team={f.home} size={16} />
              <span style={{ fontWeight: 700, fontSize: 15 }}>{f.home}</span>
              <span className="mono" style={{ fontSize: 10, color: "var(--text-muted)" }}>{f.elo.home}</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Flag team={f.away} size={16} />
              <span style={{ fontWeight: 700, fontSize: 15 }}>{f.away}</span>
              <span className="mono" style={{ fontSize: 10, color: "var(--text-muted)" }}>{f.elo.away}</span>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 3 }}>proj. score</div>
            <div className="mono" style={{ fontWeight: 800, fontSize: 17 }}>{f.model.exp_home.toFixed(1)}–{f.model.exp_away.toFixed(1)}</div>
          </div>
        </div>
        <div style={{ marginTop: 10 }}><ProbBar p={display} /></div>
        {(f.context.altitude || f.context.host_side) && (
          <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
            {f.context.host_side && <Chip tone="host"><IconHost size={11} style={{ marginRight: 4, verticalAlign: "-1px" }} />{f.context.host_country} home</Chip>}
            {f.context.altitude && <Chip tone="alt"><IconAltitude size={11} style={{ marginRight: 4, verticalAlign: "-1px" }} />{f.context.city} {f.context.altitude.meters.toLocaleString()}m{f.context.altitude.favored ? ` · ${code(f.context.altitude.favored)} edge` : ""}</Chip>}
          </div>
        )}
      </button>

      {open && (
        <div style={{ borderTop: "1px solid var(--border)", padding: "14px 16px", background: "var(--bg-raised)" }}>
          {f.market && (
            <div style={{ marginBottom: 16 }}>
              <Label>Model vs Vegas</Label>
              <Row3 label="Model" p={f.model} />
              <Row3 label="Vegas" p={f.market} prices={f.market.prices} />
              {f.blend && <Row3 label="Blend" p={f.blend} accent />}
            </div>
          )}
          <Label>Most likely scorelines</Label>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 16 }}>
            {f.top_scores.map(s => (
              <div key={s.score} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="mono" style={{ width: 34, fontSize: 13, fontWeight: 700 }}>{s.score}</span>
                <div style={{ flex: 1, height: 14, background: "var(--bg-overlay)", borderRadius: 4, overflow: "hidden" }}>
                  <div style={{ width: `${(s.prob / maxScore) * 100}%`, height: "100%", background: "var(--accent)" }} />
                </div>
                <span className="mono" style={{ width: 42, textAlign: "right", fontSize: 12, color: "var(--text-secondary)" }}>{pct(s.prob, 1)}</span>
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8, marginBottom: 16 }}>
            <Stat label="Over 2.5" val={pct(f.model.over_2_5)} sub={f.market_total ? `mkt ${pct(f.market_total.over)}` : undefined} />
            <Stat label="BTTS" val={pct(f.model.btts)} />
            <Stat label="Exp total" val={f.model.exp_total.toFixed(2)} />
          </div>
          {(f.scorers?.home?.length || f.scorers?.away?.length) ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              <Scorers team={f.home} rows={f.scorers.home} />
              <Scorers team={f.away} rows={f.scorers.away} />
            </div>
          ) : null}
          {f.context.notes.length > 0 && (
            <div style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.18)", borderRadius: 8, padding: "10px 12px" }}>
              <Label>Why this line moves</Label>
              {f.context.notes.map((n, i) => (
                <div key={i} style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5 }}>• {n}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Board({ fixtures }: { fixtures: WCFixture[] }) {
  const [sort, setSort] = useState<"date" | "edge">("date");

  const sorted = useMemo(() => {
    const f = [...fixtures];
    if (sort === "edge") f.sort((a, b) => (b.edge?.pp ?? -99) - (a.edge?.pp ?? -99));
    else f.sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));
    return f;
  }, [fixtures, sort]);

  const byDate = useMemo(() => {
    const m: Record<string, WCFixture[]> = {};
    for (const f of sorted) (m[f.date] ??= []).push(f);
    return m;
  }, [sorted]);

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <span style={{ fontWeight: 800, fontSize: 18, color: "var(--text-bright)" }}>Match projections</span>
        <div style={{ display: "flex", gap: 4, background: "var(--bg-panel)", borderRadius: 8, padding: 3 }}>
          {(["date", "edge"] as const).map(s => (
            <button key={s} onClick={() => setSort(s)} style={{
              fontSize: 11, fontWeight: 700, padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
              background: sort === s ? "var(--accent-dim)" : "transparent",
              color: sort === s ? "var(--accent-hi)" : "var(--text-secondary)",
            }}>{s === "date" ? "By date" : "By edge"}</button>
          ))}
        </div>
      </div>

      {sort === "edge" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {sorted.map(f => <FixtureCard key={f.id} f={f} />)}
        </div>
      )}

      {sort === "date" && Object.entries(byDate).map(([date, fs]) => (
        <div key={date} style={{ marginBottom: 22 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", color: "var(--text-secondary)", textTransform: "uppercase", marginBottom: 10 }}>
            {new Date(date + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" })}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {fs.map(f => <FixtureCard key={f.id} f={f} />)}
          </div>
        </div>
      ))}
    </>
  );
}
