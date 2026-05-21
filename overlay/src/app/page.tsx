import Link from "next/link";
import { readFeed } from "@/lib/feed";
import { ActivePickCard } from "@/components/ActivePickCard";
import { EquityCurve } from "@/components/EquityCurve";
import { RecentPicksTable } from "@/components/RecentPicksTable";

export const dynamic = "force-dynamic";

const PAYMENT_LINK = process.env.NEXT_PUBLIC_STRIPE_PAYMENT_LINK || "#pricing";

export default async function HomePage() {
  const feed = await readFeed();
  const r = feed?.record;
  const seatsLeft = feed ? feed.seats.total - feed.seats.taken : 22;
  const seatsTotal = feed?.seats.total ?? 25;

  return (
    <div className="landing-wrap" style={{ maxWidth: 1280, margin: "0 auto", padding: "32px 24px 0", display: "flex", flexDirection: "column", gap: 64 }}>
      {/* HERO */}
      <section className="hero-grid">
        <div>
          <div
            className="mono"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "5px 10px",
              borderRadius: 3,
              background: "var(--accent-dim)",
              border: "1px solid rgba(45,127,255,0.35)",
              color: "var(--accent-hi)",
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.14em",
              marginBottom: 24,
            }}
          >
            <span style={{ width: 6, height: 6, borderRadius: 999, background: "var(--accent-hi)" }} />
            FOUNDING ACCESS · {seatsLeft} OF {seatsTotal} SEATS LEFT
          </div>
          <h1
            style={{
              fontSize: 56,
              fontWeight: 800,
              lineHeight: 1.04,
              letterSpacing: "-0.025em",
              color: "var(--text-bright)",
              margin: 0,
              marginBottom: 20,
              maxWidth: 560,
            }}
          >
            Quant-backed picks for the{" "}
            <span style={{ color: "var(--accent)" }}>1%</span> of bettors.
          </h1>
          <p style={{ fontSize: 15, color: "var(--text-secondary)", maxWidth: 480, lineHeight: 1.6, marginBottom: 32 }}>
            Daily NBA &amp; MLB picks from a three-model ensemble (XGBoost · LightGBM · CatBoost).
            Every result tracked in public. No touts, no parlays, no hype.
          </p>

          {r && (
            <div style={{ display: "flex", gap: 36, marginBottom: 32 }}>
              <HeroStat
                label="Units P/L"
                value={`${r.units >= 0 ? "+" : ""}${r.units.toFixed(1)}U`}
                color={r.units >= 0 ? "var(--green-hi)" : "var(--red-hi)"}
              />
              <HeroStat
                label="ROI / stake"
                value={`${r.roi_pct >= 0 ? "+" : ""}${r.roi_pct.toFixed(1)}%`}
                color={r.roi_pct >= 0 ? "var(--green-hi)" : "var(--red-hi)"}
              />
              <HeroStat
                label="Win rate"
                value={`${r.win_rate_pct.toFixed(1)}%`}
                color="var(--text-bright)"
              />
            </div>
          )}
          <div style={{ display: "flex", gap: 10 }}>
            <a href={PAYMENT_LINK} className="btn-primary" target="_blank" rel="noopener noreferrer">Get today&apos;s picks — $29/mo</a>
            <Link href="/record" className="btn-ghost">See the full ledger</Link>
          </div>
        </div>
        {feed?.featured?.pick ? (
          <ActivePickCard pick={feed.featured.pick} sport={feed.featured.sport ?? "NBA"} />
        ) : (
          <div className="panel" style={{ padding: 32, textAlign: "center", color: "var(--text-muted)" }}>
            Today&apos;s slate locks shortly.
          </div>
        )}
      </section>

      {/* EQUITY CURVE */}
      <section>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 16 }}>
          <div>
            <div className="eyebrow">Cumulative equity</div>
            <h2 style={{ fontSize: 30, fontWeight: 800, color: "var(--text-bright)", margin: "6px 0 0", letterSpacing: "-0.015em" }}>
              {r ? `${r.total_card} picks. Tracked in public.` : "Tracked in public."}
            </h2>
          </div>
          {r && (
            <div style={{ textAlign: "right" }}>
              <div className="label-muted">YTD</div>
              <div className={`mono ${r.units >= 0 ? "pos" : "neg"}`} style={{ fontSize: 28, fontWeight: 800, marginTop: 4 }}>
                {r.units >= 0 ? "+" : ""}{r.units.toFixed(1)}U
              </div>
            </div>
          )}
        </div>
        <div className="panel" style={{ padding: 8 }}>
          <EquityCurve data={feed?.equity_curve || []} />
        </div>
        {r && (
          <div className="grid-4" style={{ marginTop: 12 }}>
            <KpiCard label="Picks" value={String(r.total_card)} />
            <KpiCard label="Win rate" value={`${r.win_rate_pct.toFixed(1)}%`} />
            <KpiCard label="Avg odds" value={r.avg_odds || "—"} />
            <KpiCard
              label="Streak"
              value={r.streak > 0 ? `W${r.streak}` : r.streak < 0 ? `L${Math.abs(r.streak)}` : "—"}
              color={r.streak > 0 ? "var(--green-hi)" : r.streak < 0 ? "var(--red-hi)" : "var(--text-bright)"}
            />
          </div>
        )}
      </section>

      {/* ENSEMBLE */}
      <section>
        <div className="eyebrow">The Ensemble</div>
        <h2 style={{ fontSize: 30, fontWeight: 800, color: "var(--text-bright)", margin: "6px 0 28px", letterSpacing: "-0.015em", lineHeight: 1.15 }}>
          Three models. Consensus required.<br />
          No single algorithm gets to make a call.
        </h2>
        <div className="grid-3">
          <ModelCard idx="01" name="XGBoost" tagline="The Regularizer" body="Handles sparse box-score data and complex feature interactions. Prevents overfitting on outlier player performances." />
          <ModelCard idx="02" name="LightGBM" tagline="The Speedster" body="Processes lineup changes, weather, and line movement in real-time to capture pre-game value before books adjust." />
          <ModelCard idx="03" name="CatBoost" tagline="The Categorical King" body="Specializes in categorical signals — umpires, referees, park factors, travel splits, rest differentials." />
        </div>
      </section>

      {/* LEDGER */}
      <section>
        <RecentPicksTable rows={feed?.recent_picks || []} />
      </section>

      {/* FINAL CTA */}
      <section id="pricing" style={{ textAlign: "center", padding: "56px 24px", borderTop: "1px solid var(--border)" }}>
        <div
          className="mono"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 12px",
            borderRadius: 3,
            background: "var(--accent-dim)",
            border: "1px solid rgba(45,127,255,0.35)",
            color: "var(--accent-hi)",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.14em",
            marginBottom: 18,
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: 999, background: "var(--accent-hi)" }} />
          {seatsLeft} OF {seatsTotal} FOUNDING SEATS LEFT
        </div>
        <h2
          style={{
            fontSize: 48,
            fontWeight: 800,
            color: "var(--text-bright)",
            margin: "0 0 12px",
            letterSpacing: "-0.025em",
          }}
        >
          Lock in <span style={{ color: "var(--accent)" }}>$29/mo</span> for life.
        </h2>
        <p style={{ color: "var(--text-secondary)", maxWidth: 480, margin: "0 auto 28px" }}>
          Founding price ends when the seat counter hits zero. After that it&apos;s $59/mo.
        </p>
        <a href={PAYMENT_LINK} className="btn-primary" style={{ fontSize: 14, padding: "16px 32px" }} target="_blank" rel="noopener noreferrer">
          SUBSCRIBE — $29/MO
        </a>
        <div className="mono" style={{ marginTop: 14, color: "var(--text-muted)", fontSize: 11, letterSpacing: "0.12em" }}>
          CANCEL ANYTIME · DELIVERED DAILY VIA WEB &amp; EMAIL
        </div>
      </section>
    </div>
  );
}

function HeroStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div className="mono" style={{ fontSize: 24, fontWeight: 800, color, lineHeight: 1.1 }}>{value}</div>
      <div className="label-muted" style={{ marginTop: 6 }}>{label}</div>
    </div>
  );
}

function KpiCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="panel" style={{ padding: "14px 18px" }}>
      <div className="label-muted">{label}</div>
      <div className="mono" style={{ fontSize: 20, fontWeight: 700, color: color || "var(--text-bright)", marginTop: 4 }}>
        {value}
      </div>
    </div>
  );
}

function ModelCard({ idx, name, tagline, body }: { idx: string; name: string; tagline: string; body: string }) {
  return (
    <div className="panel" style={{ padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
        <span className="mono" style={{ fontSize: 11, fontWeight: 700, color: "var(--accent)", letterSpacing: "0.1em" }}>
          [{idx}]
        </span>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", letterSpacing: "0.08em" }}>
          v4.2
        </span>
      </div>
      <div style={{ fontSize: 20, fontWeight: 800, color: "var(--text-bright)", letterSpacing: "-0.01em" }}>{name}</div>
      <div className="label-muted" style={{ marginTop: 4, marginBottom: 12 }}>{tagline}</div>
      <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6, margin: 0 }}>{body}</p>
    </div>
  );
}
