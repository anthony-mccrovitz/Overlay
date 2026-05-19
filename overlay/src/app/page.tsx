import Link from "next/link";
import { readFeed } from "@/lib/feed";
import { SubscribeButton } from "@/components/SubscribeButton";

export default async function HomePage() {
  const feed = await readFeed();
  const r = feed?.record;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 56 }}>
      {/* Hero */}
      <section style={{ paddingTop: 32 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--indigo)", letterSpacing: "0.08em", marginBottom: 12 }}>
          MODEL-BACKED · TRACKED · TRANSPARENT
        </div>
        <h1
          style={{
            fontSize: 44,
            lineHeight: 1.1,
            fontWeight: 800,
            letterSpacing: "-0.02em",
            color: "var(--text-bright)",
            margin: 0,
            marginBottom: 16,
            maxWidth: 720,
          }}
        >
          Daily NBA & MLB picks from a quantitative model.{" "}
          <span style={{
            background: "linear-gradient(90deg, var(--indigo), var(--violet))",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
          }}>
            Tracked record. No hype.
          </span>
        </h1>
        <p style={{ fontSize: 16, color: "var(--text-secondary)", maxWidth: 600, marginBottom: 28 }}>
          One subscription. Every morning, you get the card picks from the same ensemble model
          (XGBoost + LightGBM + CatBoost) that tracks every result publicly. $29/month.
        </p>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <SubscribeButton />
          <Link href="/record" className="btn-secondary">
            See the record
          </Link>
        </div>
      </section>

      {/* Live record strip */}
      {r && (
        <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16 }}>
          <div className="stat-card">
            <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Record</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: "var(--text-bright)", marginTop: 4 }}>
              {r.wins}–{r.losses}
            </div>
          </div>
          <div className="stat-card">
            <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Units</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: r.units >= 0 ? "var(--green-hi)" : "var(--red)", marginTop: 4 }}>
              {r.units >= 0 ? "+" : ""}{r.units.toFixed(2)}u
            </div>
          </div>
          <div className="stat-card">
            <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>ROI</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: r.roi_pct >= 0 ? "var(--green-hi)" : "var(--red)", marginTop: 4 }}>
              {r.roi_pct >= 0 ? "+" : ""}{r.roi_pct.toFixed(1)}%
            </div>
          </div>
          <div className="stat-card">
            <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Streak</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: "var(--text-bright)", marginTop: 4 }}>
              {r.streak > 0 ? `W${r.streak}` : r.streak < 0 ? `L${Math.abs(r.streak)}` : "—"}
            </div>
          </div>
        </section>
      )}

      {/* What you get */}
      <section>
        <h2 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-bright)", marginBottom: 20 }}>What you get</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
          {[
            { t: "Daily card picks", d: "NBA + MLB. Posted every morning before lines move. Selection, odds, sportsbook, stake, and a model-backed read on why." },
            { t: "Tracked record", d: "Every pick goes into a public ledger — wins, losses, units, ROI, streaks. No cherry-picking, no hiding losers." },
            { t: "Plain-English reasoning", d: "Each pick comes with a short read on the matchup signal so you understand the bet, not just the line." },
            { t: "Founding member access", d: "First 25 subscribers locked at $29/mo. Price goes up when the seat cap moves." },
          ].map((card) => (
            <div key={card.t} className="stat-card">
              <div style={{ fontSize: 15, fontWeight: 700, color: "var(--text-bright)", marginBottom: 8 }}>{card.t}</div>
              <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.55 }}>{card.d}</div>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section style={{ textAlign: "center", padding: "32px 20px" }}>
        <h2 style={{ fontSize: 28, fontWeight: 700, color: "var(--text-bright)", marginBottom: 12 }}>
          Lock in founding member access
        </h2>
        <p style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 20 }}>
          $29/month. Cancel any time. First 25 seats only.
        </p>
        <SubscribeButton />
      </section>
    </div>
  );
}
