import Link from "next/link";
import { getFixtures, getFutures, getMeta } from "@/lib/wcData";
import { pct, code, daysToKickoff } from "@/lib/wc";
import { Flag } from "@/components/wc/Flag";
import { IconAltitude } from "@/components/wc/Icons";

/**
 * World Cup 2026 campaign takeover for the Overlay homepage. Renders nothing
 * if the WC data hasn't been generated, so the homepage degrades gracefully.
 * Same brand, same record — the World Cup is the spearhead, not a separate site.
 */
export async function WorldCupHero() {
  const [futures, fixtures, meta] = await Promise.all([getFutures(), getFixtures(), getMeta()]);
  if (!futures || !fixtures || fixtures.length === 0) return null;

  const days = daysToKickoff();
  // Showcase fixture: the altitude/host opener (Mexico City) if present, else first.
  const showcase =
    fixtures.find(f => f.context?.altitude && f.context?.host_side) ?? fixtures[0];
  const top = futures.teams.slice(0, 6);

  return (
    <section
      className="wc-hero"
      style={{
        position: "relative",
        borderRadius: 16,
        overflow: "hidden",
        border: "1px solid rgba(18,197,138,0.28)",
        background:
          "radial-gradient(1200px 400px at 15% -20%, rgba(18,197,138,0.16), transparent 60%), linear-gradient(180deg, var(--bg-panel), var(--bg-raised))",
        padding: "32px 28px",
      }}
    >
      {/* gradient top edge */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 3, background: "linear-gradient(90deg, var(--accent), #0EA98F, var(--green-hi))" }} />

      {/* badge */}
      <div
        className="mono"
        style={{
          display: "inline-flex", alignItems: "center", gap: 8, padding: "5px 11px",
          borderRadius: 3, background: "var(--green-dim)", border: "1px solid rgba(34,197,94,0.3)",
          color: "var(--green-hi)", fontSize: 10, fontWeight: 700, letterSpacing: "0.14em", marginBottom: 18,
        }}
      >
        <span style={{ width: 6, height: 6, borderRadius: 999, background: "var(--green-hi)" }} />
        {days > 0 ? `WORLD CUP 2026 · ${days} DAYS TO KICKOFF` : "WORLD CUP 2026 · LIVE NOW"}
      </div>

      <div className="wc-hero-grid" style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 32, alignItems: "center" }}>
        {/* left: pitch */}
        <div>
          <h1 style={{ fontSize: 46, fontWeight: 800, lineHeight: 1.05, letterSpacing: "-0.025em", color: "var(--text-bright)", margin: "0 0 16px", maxWidth: 520 }}>
            The World Cup, <span style={{ color: "var(--accent)" }}>modeled.</span>
          </h1>
          <p style={{ fontSize: 15, color: "var(--text-secondary)", maxWidth: 480, lineHeight: 1.6, marginBottom: 22 }}>
            Calibrated projections on all 72 group games — altitude, host edge, and anytime scorers
            baked in, shown honestly next to the market. The same model discipline behind our public
            record, pointed at the biggest event on earth.
          </p>

          {/* stat row */}
          <div style={{ display: "flex", gap: 28, marginBottom: 26, flexWrap: "wrap" }}>
            <Stat value={String(days)} label="days to kickoff" />
            <Stat value={`${meta?.n_priced ?? 72}/72`} label="matches priced" />
            <Stat value={meta ? `${Math.round(meta.n_sims / 1000)}k` : "20k"} label="sims per forecast" />
          </div>

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Link href="/world-cup" className="btn-primary">Explore the World Cup model →</Link>
            <Link href="/world-cup/pass" className="btn-ghost">Get the Pass — $9</Link>
          </div>
        </div>

        {/* right: favorites + showcase */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="panel" style={{ padding: "16px 18px", background: "var(--bg-overlay)" }}>
            <div className="label-muted" style={{ marginBottom: 12 }}>Title favorites</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
              {top.map(t => (
                <div key={t.team} style={{ textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                  <Flag team={t.team} size={18} />
                  <div className="mono" style={{ fontSize: 10, fontWeight: 700, color: "var(--accent-hi)", letterSpacing: "0.06em" }}>{code(t.team)}</div>
                  <div className="mono" style={{ fontWeight: 800, fontSize: 17, color: "var(--text-bright)" }}>{pct(t.blend)}</div>
                </div>
              ))}
            </div>
          </div>

          {showcase && (
            <Link href="/world-cup" style={{ textDecoration: "none" }}>
              <div className="panel" style={{ padding: "14px 16px", background: "var(--bg-overlay)" }}>
                <div className="label-muted" style={{ marginBottom: 8 }}>Opening match</div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: "var(--text-bright)", display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <Flag team={showcase.home} size={15} /> {showcase.home}
                    <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>v</span>
                    <Flag team={showcase.away} size={15} /> {showcase.away}
                  </span>
                  {showcase.edge && showcase.edge.pp >= 3 && (
                    <span className="mono" style={{ fontSize: 10, fontWeight: 800, background: "var(--green-dim)", border: "1px solid rgba(34,197,94,0.3)", color: "var(--green-hi)", borderRadius: 5, padding: "2px 7px" }}>
                      EDGE +{showcase.edge.pp}pp
                    </span>
                  )}
                </div>
                {showcase.context?.notes?.[0] && (
                  <div style={{ fontSize: 11, color: "var(--amber)", display: "flex", alignItems: "center", gap: 5 }}><IconAltitude size={12} /> {showcase.context.notes[0]}</div>
                )}
              </div>
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="mono" style={{ fontSize: 24, fontWeight: 800, color: "var(--text-bright)", lineHeight: 1.1 }}>{value}</div>
      <div className="label-muted" style={{ marginTop: 6 }}>{label}</div>
    </div>
  );
}
