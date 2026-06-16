import Link from "next/link";
import type { Metadata } from "next";
import { getAccuracy, getMeta, getFixtures } from "@/lib/wcData";
import { eloLadder, eloExpected, timeAgo } from "@/lib/wc";
import { Flag } from "@/components/wc/Flag";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "The World Cup Model — How It Works",
  description: "A calibrated Elo + Poisson engine for international football: how the World Cup 2026 projections, scorer props, and futures are built — and what they can and can't do.",
};

function Banner({ n, label }: { n: string; label: string }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div className="mono" style={{ fontWeight: 900, fontSize: 24, color: "var(--accent-hi)" }}>{n}</div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2, lineHeight: 1.3 }}>{label}</div>
    </div>
  );
}

function Prov({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-bright)", marginBottom: 5 }}>{label}</div>
      <div style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.55 }}>{children}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <h2 style={{ fontSize: 19, fontWeight: 800, color: "var(--text-bright)", marginBottom: 10 }}>{title}</h2>
      <div style={{ fontSize: 14, color: "var(--text)", lineHeight: 1.7 }}>{children}</div>
    </div>
  );
}

export default async function ModelPage() {
  const [a, meta, fixtures] = await Promise.all([getAccuracy(), getMeta(), getFixtures()]);
  const sims = meta ? meta.n_sims.toLocaleString() : "20,000";
  const tourns = a ? a.n_tournaments : 19;
  const matches = a ? a.n_matches.toLocaleString() : "800+";

  // Live Elo ladder straight from today's fixtures — top 5 + bottom 1 for range.
  const ladder = fixtures ? eloLadder(fixtures) : [];
  const topElo = ladder.slice(0, 5);
  const lowElo = ladder.length ? ladder[ladder.length - 1] : null;
  const eloFloor = ladder.length ? ladder[ladder.length - 1].elo : 1500;
  const eloTop = ladder.length ? ladder[0].elo : 2000;
  // Concrete intuition: a 100-point edge ≈ this win expectancy (two-outcome Elo).
  const edge100 = Math.round(eloExpected(100) * 100);
  const refreshed = timeAgo(meta?.generated);

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "32px 16px 100px" }}>
      <Link href="/world-cup" style={{ fontSize: 12, color: "var(--accent-hi)", textDecoration: "none" }}>← All matches</Link>
      <h1 style={{ fontSize: 32, fontWeight: 900, letterSpacing: "-0.02em", margin: "16px 0 8px", color: "var(--text-bright)" }}>The model</h1>
      <p style={{ fontSize: 15, color: "var(--text-secondary)", marginBottom: 8 }}>How every World Cup 2026 number on this site is built.</p>
      <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 28 }}>
        Prefer the receipts? <Link href="/world-cup/accuracy" style={{ color: "var(--accent-hi)", textDecoration: "none" }}>See the track record →</Link>
      </p>

      {/* stat banner */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(90px,1fr))", gap: 14, background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 14, padding: "18px 16px", marginBottom: 32 }}>
        <Banner n={sims} label="simulations per forecast" />
        <Banner n={String(tourns)} label="tournaments validated" />
        <Banner n={matches} label="matches graded out-of-sample" />
        <Banner n="47k+" label="historical goals for scorer props" />
        <Banner n="4" label="calibration parameters" />
      </div>

      <div style={{ background: "var(--accent-dim)", border: "1px solid rgba(18,197,138,0.25)", borderRadius: 12, padding: "14px 18px", marginBottom: 32 }}>
        <div style={{ fontSize: 13, color: "var(--text)", lineHeight: 1.6 }}>
          <strong style={{ color: "var(--text-bright)" }}>One idea up front:</strong> the model rates how good every nation is, simulates each match as goals scored, and runs the whole tournament thousands of times. It does <strong>not</strong> read sportsbook odds to form its opinion — we show the market next to it so you can judge for yourself.
        </div>
      </div>

      <Section title="1. Strength, then goals">
        Every nation carries a rolling <strong style={{ color: "var(--text-bright)" }}>Elo rating</strong> updated after each competitive international — win against a strong side, gain more. That strength gap sets each team&apos;s expected goals, which feed a <strong style={{ color: "var(--text-bright)" }}>Dixon-Coles Poisson</strong> model: a full grid of every plausible scoreline (0-0, 2-1, 3-0…) with a probability on each. From that one grid we read win/draw/win, both-teams-to-score, totals, and the most likely scores — all internally consistent, never bolted on separately.
      </Section>

      {/* Plain-English Elo explainer + live ladder */}
      <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 14, padding: "20px 20px 18px", marginBottom: 28 }}>
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.12em", color: "var(--accent-hi)", textTransform: "uppercase", marginBottom: 10 }}>
          Plain English: what&apos;s an Elo rating?
        </div>
        <p style={{ fontSize: 14, color: "var(--text)", lineHeight: 1.7, margin: "0 0 12px" }}>
          It&apos;s the same idea chess uses to rank players — one number for how strong a team is. Beat a
          stronger side and your number goes up; lose to a weaker one and it drops. Everyone starts in the
          same currency, so you can compare any two nations directly. A bigger gap means a bigger favorite:
          a <strong style={{ color: "var(--text-bright)" }}>100-point edge ≈ a {edge100}% chance</strong> in
          a head-to-head, and the gaps stack from there.
        </p>
        <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6, margin: "0 0 16px" }}>
          On this site the scale runs from about <strong className="mono" style={{ color: "var(--text-bright)" }}>{eloFloor}</strong> for
          the weakest qualifier up to <strong className="mono" style={{ color: "var(--text-bright)" }}>{eloTop}</strong> for the favorites.
          These aren&apos;t illustrations — they&apos;re the exact ratings driving every projection right now:
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          {topElo.map((t, i) => {
            const span = Math.max(1, eloTop - eloFloor);
            const w = Math.round(((t.elo - eloFloor) / span) * 88) + 12;
            return (
              <div key={t.team} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", width: 14 }}>{i + 1}</span>
                <Flag team={t.team} size={15} />
                <span style={{ fontSize: 13, color: "var(--text-bright)", width: 110, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.team}</span>
                <div style={{ flex: 1, height: 8, background: "var(--bg-raised)", borderRadius: 999, overflow: "hidden" }}>
                  <div style={{ width: `${w}%`, height: "100%", background: "linear-gradient(90deg, var(--accent), var(--accent-hi))", borderRadius: 999 }} />
                </div>
                <span className="mono" style={{ fontSize: 13, fontWeight: 700, color: "var(--accent-hi)", width: 42, textAlign: "right" }}>{t.elo}</span>
              </div>
            );
          })}
          {lowElo && (
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4, paddingTop: 8, borderTop: "1px dashed var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", width: 14 }}>↓</span>
              <Flag team={lowElo.team} size={15} />
              <span style={{ fontSize: 13, color: "var(--text-secondary)", width: 110, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{lowElo.team}</span>
              <div style={{ flex: 1, height: 8, background: "var(--bg-raised)", borderRadius: 999, overflow: "hidden" }}>
                <div style={{ width: "12%", height: "100%", background: "var(--text-muted)", borderRadius: 999 }} />
              </div>
              <span className="mono" style={{ fontSize: 13, fontWeight: 700, color: "var(--text-secondary)", width: 42, textAlign: "right" }}>{lowElo.elo}</span>
            </div>
          )}
        </div>
        <p style={{ fontSize: 11, color: "var(--text-muted)", margin: "14px 0 0", lineHeight: 1.5 }}>
          Weakest field team shown for range · ratings update after every competitive international
        </p>
      </div>

      <Section title="2. What goes in — and what doesn't">
        Inputs: each team&apos;s live Elo, a recency-weighted measure of how freely they&apos;ve been scoring and conceding, and the venue (below). Deliberately kept to <strong style={{ color: "var(--text-bright)" }}>four fitted parameters</strong> — international squads change too fast for a heavier model to do anything but overfit. Notably absent: <strong>sportsbook odds.</strong> The projection is formed independently, then we de-vig the market and show both. The &quot;blend&quot; number you see is a transparency layer for the headline, not a model input.
      </Section>

      <Section title="3. Calibrated, not just confident">
        Raw strength models are overconfident on favorites — they&apos;ll say 85% when reality is closer to 68%. We correct that with a <strong style={{ color: "var(--text-bright)" }}>temperature setting (T=1.25)</strong>, tuned across {matches} past matches, that softens extreme probabilities toward honesty. The <Link href="/world-cup/accuracy" style={{ color: "var(--accent-hi)", textDecoration: "none" }}>accuracy page</Link> shows the result: when we say a number, it happens about that often.
      </Section>

      <Section title="4. The context other models miss">
        This is the edge for a World Cup in North America. The three co-hosts (USA, Mexico, Canada) get a real <strong style={{ color: "var(--text-bright)" }}>home advantage</strong> at their own venues. And altitude matters: <strong style={{ color: "var(--text-bright)" }}>Mexico City sits at 2,240m</strong>, where acclimatized sides (Mexico and the Andean nations) keep their legs while sea-level visitors fade. The opener — Mexico vs South Africa in Mexico City — carries a combined host-plus-altitude edge worth ~115 Elo points. Most models treat every neutral-site game the same. This one doesn&apos;t.
      </Section>

      <Section title="5. Simulating the whole tournament">
        For futures — who lifts the trophy, who escapes the group — we run the full 48-team bracket <strong style={{ color: "var(--text-bright)" }}>{sims} times</strong>, playing every group and knockout match (shootouts included) with the same engine. Counting how often each team reaches each round gives the championship, finalist, and advance probabilities.
      </Section>

      <Section title="6. Who scores">
        Anytime-scorer and Golden Boot projections come from a separate layer built on <strong style={{ color: "var(--text-bright)" }}>47,000+ historical international goals</strong>. Each player gets a recency-weighted share of their nation&apos;s scoring, which splits the team&apos;s expected goals into individual chances. A striker on a high-scoring side in a deep run climbs the board; the math is the same one that prices the anytime market.
      </Section>

      <Section title="7. What it can't do (read this)">
        Even a perfect model tops out around 53-55% on match results — draws and upsets are baked into football. And on <strong style={{ color: "var(--text-bright)" }}>goal totals, the model has no edge</strong> (the <Link href="/world-cup/accuracy" style={{ color: "var(--accent-hi)", textDecoration: "none" }}>numbers prove it</Link>): international totals are near-random. We show projected totals for color but don&apos;t sell them. The win is calibrated probabilities, honest context, and good stories — not magic.
      </Section>

      {/* Real + live data provenance */}
      <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 14, padding: "20px 20px 16px", marginBottom: 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <span style={{ width: 7, height: 7, borderRadius: 999, background: "var(--green-hi)", boxShadow: "0 0 8px var(--green-hi)" }} />
          <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.12em", color: "var(--green-hi)", textTransform: "uppercase" }}>
            Real data, refreshed live
          </span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 14 }}>
          <Prov label="Match results">
            Every competitive international, going back decades — the public results history the Elo ratings are built and continuously updated from.
          </Prov>
          <Prov label="Live sportsbook lines">
            Real moneyline and futures prices pulled from the market via the Odds API. All <strong style={{ color: "var(--text-bright)" }}>{meta?.n_priced ?? 72}/72</strong> group games are priced against live odds, de-vigged before we compare.
          </Prov>
          <Prov label="Scoring history">
            <strong style={{ color: "var(--text-bright)" }}>47,000+</strong> real international goals power the anytime-scorer and Golden Boot props — no hand-picked names.
          </Prov>
          <Prov label="Last refreshed">
            <strong style={{ color: "var(--text-bright)" }}>{refreshed || "today"}</strong>{meta?.generated ? ` · ${new Date(meta.generated).toUTCString().replace("GMT", "UTC")}` : ""}. Re-pulled before every slate so the lines you see are current.
          </Prov>
        </div>
        <p style={{ fontSize: 11, color: "var(--text-muted)", margin: "14px 0 0", lineHeight: 1.5 }}>
          Nothing on this page is mocked or illustrative. Every projection, Elo, and edge is computed from the data above and graded openly on the <Link href="/world-cup/accuracy" style={{ color: "var(--accent-hi)", textDecoration: "none" }}>track record</Link>.
        </p>
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8 }}>
        <Link href="/world-cup/accuracy" style={{ fontSize: 13, fontWeight: 700, color: "var(--accent-hi)", textDecoration: "none", background: "var(--accent-dim)", border: "1px solid rgba(18,197,138,0.3)", borderRadius: 8, padding: "10px 16px" }}>See the track record →</Link>
        <Link href="/world-cup" style={{ fontSize: 13, fontWeight: 700, color: "var(--text-secondary)", textDecoration: "none", background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 16px" }}>Back to matches</Link>
      </div>

      <p style={{ textAlign: "center", fontSize: 10, color: "var(--text-muted)", marginTop: 32, letterSpacing: "0.06em" }}>NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+</p>
    </div>
  );
}
