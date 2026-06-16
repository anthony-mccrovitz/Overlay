import Link from "next/link";
import { getSession, isAllowlisted } from "@/lib/session";
import { SubscribeButton } from "@/components/SubscribeButton";
import { ToolsClient } from "@/components/tools/ToolsClient";

export const dynamic = "force-dynamic";

const card: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  padding: "20px 22px",
  textDecoration: "none",
  display: "block",
  height: "100%",
};

export default function ToolsPage() {
  let isPro = false;
  try {
    const session = getSession();
    isPro = !!(session?.email && isAllowlisted(session.email));
  } catch {
    isPro = false;
  }

  const tools = [
    {
      href: "/no-vig",
      icon: "📊",
      title: "No-Vig Fair Odds Calculator",
      desc: "Paste any two-sided or three-way market. Strips the book's margin and shows you the true fair odds + vig percentage.",
      cta: "Open calculator →",
    },
    {
      href: "/clv-calculator",
      icon: "📈",
      title: "CLV Calculator",
      desc: "Closing Line Value is a better predictor of long-run profitability than W/L. Paste your odds + the closing line — see your CLV% and session streak.",
      cta: "Calculate CLV →",
    },
    {
      href: "/slate",
      icon: "🔍",
      title: "Full Model Slate",
      desc: "Every game the model evaluated today — MLB, NBA, NHL. Edge %, direction, odds, and book. Positive EV highlighted.",
      cta: "View today's slate →",
    },
  ];

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "32px 24px 80px", display: "flex", flexDirection: "column", gap: 40 }}>

      {/* ── Free public tools ── */}
      <div>
        <div className="eyebrow" style={{ marginBottom: 8 }}>Free Tools</div>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--text-bright)", margin: "0 0 8px", letterSpacing: "-0.015em" }}>
          Tools the model uses
        </h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 14, margin: 0, maxWidth: 540 }}>
          Free forever. No login required. OddsJam charges $80/mo for access to tools like these.
        </p>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 16,
            marginTop: 24,
          }}
        >
          {tools.map((t) => (
            <Link key={t.href} href={t.href} style={{ textDecoration: "none" }}>
              <div style={card}>
                <div style={{ fontSize: 24, marginBottom: 10 }}>{t.icon}</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-bright)", marginBottom: 6 }}>
                  {t.title}
                </div>
                <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6 }}>
                  {t.desc}
                </div>
                <div style={{ marginTop: 14, fontSize: 12, color: "var(--accent)", fontWeight: 600 }}>
                  {t.cta}
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* ── Subscriber workbench ── */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <div className="eyebrow">Pro Workbench</div>
          {!isPro && (
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                background: "var(--accent)",
                color: "#04130C",
                padding: "2px 8px",
                borderRadius: 10,
              }}
            >
              SUBSCRIBERS ONLY
            </span>
          )}
        </div>
        <h2 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-bright)", margin: "0 0 6px", letterSpacing: "-0.01em" }}>
          EV · CLV · Odds conversion · Parlay math
        </h2>
        <p style={{ color: "var(--text-secondary)", fontSize: 13, margin: 0, maxWidth: 540 }}>
          Everything wired to American, decimal, fraction, and implied. Same primitives the ensemble runs on.
        </p>

        {isPro ? (
          <div style={{ marginTop: 24 }}>
            <ToolsClient />
          </div>
        ) : (
          <div
            style={{
              marginTop: 24,
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 12,
              padding: "28px 24px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 20,
              flexWrap: "wrap",
            }}
          >
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: "var(--text-bright)", marginBottom: 6 }}>
                EV calculator, Kelly sizing, CLV tracker, parlay builder
              </div>
              <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6, maxWidth: 400 }}>
                Subscribe to unlock the full workbench. $19/mo — cancel anytime.
                Founding price locked for life.
              </div>
            </div>
            <SubscribeButton />
          </div>
        )}
      </div>

    </div>
  );
}
