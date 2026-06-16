import Link from "next/link";
import { readFeed } from "@/lib/feed";
import { ActivePickCard } from "@/components/ActivePickCard";
import { EquityCurve } from "@/components/EquityCurve";
import { RecentPicksTable } from "@/components/RecentPicksTable";
import { WorldCupHero } from "@/components/wc/HomeHero";
import { LeadCapture } from "@/components/LeadCapture";

export const dynamic = "force-dynamic";

const PAYMENT_LINK = process.env.NEXT_PUBLIC_STRIPE_PAYMENT_LINK || "#pricing";

export default async function HomePage() {
  const feed = await readFeed();
  const r = feed?.record;
  const seatsLeft = feed ? feed.seats.total - feed.seats.taken : 22;
  const seatsTotal = feed?.seats.total ?? 25;

  return (
    <div className="landing-wrap" style={{ maxWidth: 1280, margin: "0 auto", padding: "32px 24px 0", display: "flex", flexDirection: "column", gap: 64 }}>
      {/* WORLD CUP CAMPAIGN TAKEOVER */}
      <WorldCupHero />

      {/* framing divider */}
      <div style={{ textAlign: "center", marginTop: -32 }}>
        <div className="eyebrow">The engine behind it</div>
        <p style={{ fontSize: 14, color: "var(--text-secondary)", maxWidth: 540, margin: "8px auto 0", lineHeight: 1.6 }}>
          The same quantitative discipline that prices the World Cup runs our daily NBA &amp; MLB card — every pick timestamped before game time, tracked in public.
        </p>
      </div>

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
              border: "1px solid rgba(18,197,138,0.35)",
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
            <a href={PAYMENT_LINK} className="btn-primary" target="_blank" rel="noopener noreferrer">Get today&apos;s picks — $19/mo</a>
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

      {/* HOW IT WORKS */}
      <section>
        <div className="eyebrow">How it works</div>
        <h2 style={{ fontSize: 30, fontWeight: 800, color: "var(--text-bright)", margin: "6px 0 28px", letterSpacing: "-0.015em", lineHeight: 1.15 }}>
          From slate to inbox in three steps.
        </h2>
        <div className="grid-3">
          <Step
            idx="01"
            title="The models price the slate"
            body="Three independent models project every game overnight. A pick only posts when all three agree and the number beats the book — most games produce nothing, and that's the point."
          />
          <Step
            idx="02"
            title="You get it before the line moves"
            body="Picks land on your dashboard and in your inbox each morning — timestamped before tip-off so you can verify every call was made early, not after the fact."
          />
          <Step
            idx="03"
            title="Everything is graded in public"
            body="Win or lose, every card pick hits the public ledger. No deleting losers, no cherry-picked screenshots. The record above is the whole record."
          />
        </div>
      </section>

      {/* FAQ */}
      <section>
        <div className="eyebrow">Before you ask</div>
        <h2 style={{ fontSize: 30, fontWeight: 800, color: "var(--text-bright)", margin: "6px 0 24px", letterSpacing: "-0.015em" }}>
          The honest answers.
        </h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <Faq
            q="Do you guarantee winning picks?"
            a="No — and anyone who does is lying to you. Sports betting has real variance and losing weeks are part of every honest record. What we guarantee is process: positive-EV picks, sized with Kelly, every result posted in public so the edge shows over volume instead of in a highlight reel."
          />
          <Faq
            q="How do I actually get the picks?"
            a="They post to your subscriber dashboard every morning and go out by email the same time — before lines move. Each pick is SHA-256 timestamped so the call is provably early."
          />
          <Faq
            q="What's the edge, in plain terms?"
            a="Three models (XGBoost, LightGBM, CatBoost) each project the game. A pick only fires when they agree and the projection beats the sportsbook's number by a meaningful margin. We bet the book's mistake, not a hunch — no parlays, no chasing."
          />
          <Faq
            q="Which sports are covered?"
            a="NBA and MLB daily during their seasons, plus a calibrated World Cup 2026 model running now. NHL and others rotate in seasonally. Your subscription covers everything on the card."
          />
          <Faq
            q="Can I cancel?"
            a="Anytime, in one click — no email, no phone call, no retention maze. You keep access through the end of the period you already paid for."
          />
          <Faq
            q="Is this legal?"
            a="Overlay is research and analysis, not a sportsbook — we never hold your money. Bet only where it's legal in your jurisdiction, and only if you're 21+. Wager what you can afford to lose."
          />
        </div>
      </section>

      {/* FREE LIST CAPTURE — catch the not-ready-to-pay visitor before they bounce */}
      <section style={{ textAlign: "center", padding: "44px 24px", borderTop: "1px solid var(--border)" }}>
        <div className="eyebrow">Not ready to subscribe?</div>
        <h2 style={{ fontSize: 30, fontWeight: 800, color: "var(--text-bright)", margin: "8px 0 10px", letterSpacing: "-0.015em" }}>
          Get a free play before the next big slate.
        </h2>
        <p style={{ color: "var(--text-secondary)", maxWidth: 460, margin: "0 auto 22px", fontSize: 14, lineHeight: 1.6 }}>
          One sharp pick from the same engine, straight to your inbox. No card required. See the edge for yourself, then decide.
        </p>
        <LeadCapture source="landing-free-list" cta="Send me a free play" />
        <div className="mono" style={{ marginTop: 14, color: "var(--text-muted)", fontSize: 11, letterSpacing: "0.12em" }}>
          NO SPAM · UNSUBSCRIBE IN ONE CLICK
        </div>
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
            border: "1px solid rgba(18,197,138,0.35)",
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
          Lock in <span style={{ color: "var(--accent)" }}>$19/mo</span> for life.
        </h2>
        <p style={{ color: "var(--text-secondary)", maxWidth: 480, margin: "0 auto 12px" }}>
          Founding price ends when the seat counter hits zero. After that it's $29/mo.
        </p>
        <p style={{ color: "var(--text-muted)", maxWidth: 520, margin: "0 auto 28px", fontSize: 13, lineHeight: 1.6 }}>
          Every pick we&apos;ve ever posted — wins and losses — is on the public ledger before you pay a cent. Cancel in one click, anytime.
        </p>
        <a href={PAYMENT_LINK} className="btn-primary" style={{ fontSize: 14, padding: "16px 32px" }} target="_blank" rel="noopener noreferrer">
          SUBSCRIBE — $19/MO
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

function Step({ idx, title, body }: { idx: string; title: string; body: string }) {
  return (
    <div className="panel" style={{ padding: 24 }}>
      <span className="mono" style={{ fontSize: 11, fontWeight: 700, color: "var(--accent)", letterSpacing: "0.1em" }}>
        [{idx}]
      </span>
      <div style={{ fontSize: 18, fontWeight: 800, color: "var(--text-bright)", letterSpacing: "-0.01em", margin: "12px 0 10px" }}>{title}</div>
      <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6, margin: 0 }}>{body}</p>
    </div>
  );
}

function Faq({ q, a }: { q: string; a: string }) {
  return (
    <details className="panel" style={{ padding: "16px 20px" }}>
      <summary
        style={{
          cursor: "pointer",
          listStyle: "none",
          fontSize: 15,
          fontWeight: 700,
          color: "var(--text-bright)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 16,
        }}
      >
        {q}
        <span className="mono" style={{ color: "var(--accent)", fontSize: 18, fontWeight: 700, flexShrink: 0 }}>+</span>
      </summary>
      <p style={{ fontSize: 13.5, color: "var(--text-secondary)", lineHeight: 1.65, margin: "12px 0 0" }}>{a}</p>
    </details>
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
