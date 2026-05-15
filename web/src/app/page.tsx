"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

interface MarketStats { wins: number; losses: number; win_rate: number; units_profit: number; roi: number; }
interface RecentPick  { date: string|null; sport: string|null; market: string|null; team: string|null; odds: number|null; result: string|null; profit: number|null; }
interface StatsData {
  summary: { wins: number; losses: number; win_rate: number; units_profit: number; roi: number; settled: number; };
  by_market: Record<string, MarketStats>;
  recent_picks: RecentPick[];
}

function fmtOdds(o: number|null) { if (!o) return "—"; return o > 0 ? `+${o}` : `${o}`; }
function fmtRoi(v: number)       { return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`; }
function fmtPL(v: number)        { return `${v >= 0 ? "+" : ""}${v.toFixed(2)}u`; }

/* ── Sport label badge (brand colors, no emoji) ── */
function SportBadge({ sport }: { sport: string }) {
  const cfg: Record<string, { bg: string }> = {
    mlb: { bg: "#002D72" },
    nba: { bg: "#C9082A" },
    nhl: { bg: "#000" },
    pga: { bg: "#1E4620" },
  };
  const c = cfg[sport.toLowerCase()] ?? { bg: "#334155" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      background: c.bg, color: "#fff",
      fontSize: 9, fontWeight: 900, letterSpacing: "0.08em",
      padding: "3px 7px", borderRadius: 5, flexShrink: 0,
    }}>{sport.toUpperCase()}</span>
  );
}

/* ── SVG check / cross ── */
function Check() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0, marginTop: 1 }}>
      <circle cx="7" cy="7" r="7" fill="rgba(74,222,128,0.15)"/>
      <path d="M4 7l2 2 4-4" stroke="#4ADE80" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}
function Cross() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0, marginTop: 1 }}>
      <circle cx="7" cy="7" r="7" fill="rgba(255,255,255,0.05)"/>
      <path d="M5 5l4 4M9 5l-4 4" stroke="rgba(255,255,255,0.2)" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}

/* ── Email capture ── */
function EmailSignup({ source = "home", cta = "Get Free Pick" }: { source?: string; cta?: string }) {
  const [email, setEmail] = useState("");
  const [st, setSt]       = useState<"idle" | "loading" | "done" | "error">("idle");
  const [msg, setMsg]     = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSt("loading");
    try {
      const r = await fetch("/api/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), tier: "free", source }),
      });
      const d = await r.json();
      if (d.ok) { setSt("done"); setMsg(d.message ?? "You are on the list."); }
      else       { setSt("error"); setMsg(d.error ?? "Something went wrong."); }
    } catch { setSt("error"); setMsg("Connection failed. Try again."); }
  }

  if (st === "done") return (
    <div style={{
      background: "rgba(74,222,128,0.08)", border: "1px solid rgba(74,222,128,0.25)",
      borderRadius: 10, padding: "12px 16px", textAlign: "center",
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, color: "#4ADE80", marginBottom: 3 }}>You are on the list</div>
      <div style={{ fontSize: 12, color: "rgba(255,255,255,0.4)" }}>First pick arrives before tomorrow&apos;s games.</div>
    </div>
  );

  return (
    <form onSubmit={submit}>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          type="email" required value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="your@email.com"
          style={{
            flex: 1, background: "rgba(255,255,255,0.05)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 9, padding: "10px 14px",
            fontSize: 13, color: "#fff", outline: "none",
          }}
        />
        <button type="submit" disabled={st === "loading"} style={{
          background: "rgba(255,255,255,0.08)",
          border: "1px solid rgba(255,255,255,0.15)",
          color: "#fff", fontWeight: 700, fontSize: 12,
          padding: "10px 16px", borderRadius: 9, cursor: "pointer",
          whiteSpace: "nowrap", letterSpacing: "0.03em",
          opacity: st === "loading" ? 0.5 : 1,
        }}>
          {st === "loading" ? "..." : cta}
        </button>
      </div>
      {st === "error" && <p style={{ fontSize: 11, color: "#f87171", marginTop: 6 }}>{msg}</p>}
    </form>
  );
}

const FREE_FEATURES  = ["1 best pick daily, delivered to your email", "Model edge score and brief reasoning", "Full public track record access"];
const FREE_NO        = ["Full daily slate (all games and markets)", "NRFI and player prop picks", "Same-game parlay builder", "Kelly bet sizing"];
const PRO_FEATURES   = ["Full slate at market open, every day", "All markets: moneyline, totals, props, NRFI", "Edge score and model reasoning on every pick", "Kelly bet sizing per pick", "Same-game parlay builder", "MLB, NBA, and PGA major coverage", "Timestamped public record"];

export default function Home() {
  const [stats, setStats] = useState<StatsData | null>(null);

  useEffect(() => {
    fetch("/api/record").then(r => r.json()).then(setStats).catch(() => {});
  }, []);

  const s      = stats?.summary;
  const bm     = stats?.by_market ?? {};
  const recent = stats?.recent_picks?.filter(p => p.result === "win" || p.result === "loss").slice(0, 8) ?? [];

  return (
    <div style={{ background: "#06080f", minHeight: "100vh", color: "#fff" }}>
      <div style={{ maxWidth: 880, margin: "0 auto", padding: "48px 20px 100px" }}>

        {/* ── Hero ── */}
        <div style={{ textAlign: "center", marginBottom: 52 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, marginBottom: 18 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#22c55e", display: "inline-block" }} className="live-dot" />
            <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.14em", color: "#22c55e" }}>LIVE · 2025–26 SEASON</span>
          </div>

          <h1 style={{ fontSize: "clamp(34px, 6vw, 56px)", fontWeight: 900, lineHeight: 1.06, letterSpacing: "-0.03em", marginBottom: 16 }}>
            Find the overlay<br />
            <span style={{ background: "linear-gradient(90deg, #6366f1, #8b5cf6, #06b6d4)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
              every single day.
            </span>
          </h1>

          <p style={{ fontSize: 16, color: "rgba(255,255,255,0.45)", lineHeight: 1.65, maxWidth: 480, margin: "0 auto 0" }}>
            AI edge detection across MLB, NBA, and golf. Verified track record. No cherry-picking.
          </p>
        </div>

        {/* ── Stats bar ── */}
        {s && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 36 }}>
            {[
              { label: "Season Record",  val: `${s.wins}–${s.losses}`,            sub: `${s.settled} settled`,    green: s.win_rate >= 0.524 },
              { label: "Win Rate",       val: `${(s.win_rate*100).toFixed(1)}%`,  sub: "52.4% breakeven",         green: s.win_rate >= 0.524 },
              { label: "Units Profit",   val: fmtPL(s.units_profit),              sub: "flat 1u stakes",          green: s.units_profit >= 0 },
              { label: "ROI",            val: fmtRoi(s.roi),                      sub: "on settled bets",         green: s.roi >= 0 },
            ].map(({ label, val, sub, green }) => (
              <div key={label} style={{
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.07)",
                borderRadius: 12, padding: "16px 14px", textAlign: "center",
              }}>
                <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.1em", color: "rgba(255,255,255,0.3)", textTransform: "uppercase", marginBottom: 8 }}>{label}</div>
                <div style={{ fontWeight: 900, fontSize: 20, letterSpacing: "-0.02em", color: green ? "#4ADE80" : "#f87171" }}>{val}</div>
                <div style={{ fontSize: 10, color: "rgba(255,255,255,0.2)", marginTop: 4 }}>{sub}</div>
              </div>
            ))}
          </div>
        )}

        {/* ── Plans ── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 40 }}>

          {/* Free */}
          <div style={{
            background: "rgba(255,255,255,0.025)",
            border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 16, overflow: "hidden",
          }}>
            <div style={{ padding: "24px 24px 20px" }}>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "rgba(255,255,255,0.35)", textTransform: "uppercase", marginBottom: 8 }}>Free</div>
              <div style={{ fontSize: 26, fontWeight: 900, letterSpacing: "-0.02em", marginBottom: 4 }}>$0 / month</div>
              <div style={{ fontSize: 12, color: "rgba(255,255,255,0.35)", marginBottom: 24 }}>Pick of the Day to your inbox</div>
              <EmailSignup source="plan-free" cta="Get Free Pick" />
            </div>
            <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", padding: "18px 24px" }}>
              <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", color: "rgba(255,255,255,0.25)", marginBottom: 12, textTransform: "uppercase" }}>Included</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {FREE_FEATURES.map(f => (
                  <div key={f} style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
                    <Check /><span style={{ fontSize: 12, color: "rgba(255,255,255,0.6)", lineHeight: 1.5 }}>{f}</span>
                  </div>
                ))}
                {FREE_NO.map(f => (
                  <div key={f} style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
                    <Cross /><span style={{ fontSize: 12, color: "rgba(255,255,255,0.2)", lineHeight: 1.5 }}>{f}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Pro */}
          <div style={{
            background: "rgba(99,102,241,0.06)",
            border: "1px solid rgba(99,102,241,0.3)",
            borderRadius: 16, overflow: "hidden", position: "relative",
          }}>
            <div style={{ height: 3, background: "linear-gradient(90deg, #6366f1, #8b5cf6, #06b6d4)" }} />
            <div style={{ padding: "21px 24px 20px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", color: "#818cf8", textTransform: "uppercase" }}>Pro</span>
                <span style={{
                  fontSize: 9, fontWeight: 800, letterSpacing: "0.08em",
                  background: "rgba(99,102,241,0.2)", color: "#a5b4fc",
                  border: "1px solid rgba(99,102,241,0.4)",
                  borderRadius: 4, padding: "2px 7px",
                }}>EARLY ACCESS</span>
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 4 }}>
                <span style={{ fontSize: 26, fontWeight: 900, letterSpacing: "-0.02em" }}>$29</span>
                <span style={{ fontSize: 13, color: "rgba(255,255,255,0.35)" }}>/ month</span>
              </div>
              <div style={{ fontSize: 12, color: "rgba(255,255,255,0.35)", marginBottom: 24 }}>
                Locks at $29 — price increases at public launch
              </div>
              <Link href="/early-access" style={{
                display: "block", textAlign: "center",
                background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
                color: "#fff", fontWeight: 800, fontSize: 13,
                padding: "12px 20px", borderRadius: 9, textDecoration: "none",
                boxShadow: "0 4px 24px rgba(99,102,241,0.3)",
                letterSpacing: "0.02em",
              }}>
                Get Early Access
              </Link>
            </div>
            <div style={{ borderTop: "1px solid rgba(99,102,241,0.15)", padding: "18px 24px" }}>
              <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", color: "rgba(255,255,255,0.25)", marginBottom: 12, textTransform: "uppercase" }}>Everything in Free, plus</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {PRO_FEATURES.map(f => (
                  <div key={f} style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
                    <Check /><span style={{ fontSize: 12, color: "rgba(255,255,255,0.65)", lineHeight: 1.5 }}>{f}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* ── Recent results ── */}
        {recent.length > 0 && (
          <div style={{
            background: "rgba(255,255,255,0.02)",
            border: "1px solid rgba(255,255,255,0.07)",
            borderRadius: 16, overflow: "hidden", marginBottom: 32,
          }}>
            <div style={{
              padding: "13px 20px", borderBottom: "1px solid rgba(255,255,255,0.07)",
              display: "flex", alignItems: "center", justifyContent: "space-between",
            }}>
              <span style={{ fontWeight: 700, fontSize: 13 }}>Recent Results</span>
              <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.1em", color: "rgba(255,255,255,0.25)", textTransform: "uppercase" }}>All picks logged pre-game</span>
            </div>
            {recent.map((p, i) => (
              <div key={i} style={{
                padding: "11px 20px",
                borderBottom: i < recent.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none",
                display: "flex", alignItems: "center", gap: 12,
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: 7, flexShrink: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 10, fontWeight: 900,
                  background: p.result === "win" ? "rgba(74,222,128,0.12)" : "rgba(248,113,113,0.12)",
                  border: `1px solid ${p.result === "win" ? "rgba(74,222,128,0.3)" : "rgba(248,113,113,0.3)"}`,
                  color: p.result === "win" ? "#4ADE80" : "#f87171",
                }}>
                  {p.result === "win" ? "W" : "L"}
                </div>
                {p.sport && <SportBadge sport={p.sport} />}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.team ?? "—"}</div>
                  <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 2 }}>{p.market} · {fmtOdds(p.odds)}</div>
                </div>
                {p.profit != null && (
                  <div style={{ fontSize: 13, fontWeight: 900, fontFamily: "monospace", flexShrink: 0, color: p.profit >= 0 ? "#4ADE80" : "#f87171" }}>
                    {fmtPL(p.profit)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* ── How it works ── */}
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 0,
          background: "rgba(255,255,255,0.02)",
          border: "1px solid rgba(255,255,255,0.07)",
          borderRadius: 16, overflow: "hidden", marginBottom: 32,
        }}>
          {[
            {
              icon: (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
                </svg>
              ),
              n: "01", title: "Model scans every game",
              body: "XGBoost ensemble trained on 10 years of data. Pitching, rest, travel, weather, and line movement — all factored in before every pick.",
            },
            {
              icon: (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
                </svg>
              ),
              n: "02", title: "Edge detected, pick logged",
              body: "Only picks above a minimum edge threshold make the cut. Every pick is timestamped to a file before first pitch or tip-off.",
            },
            {
              icon: (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              ),
              n: "03", title: "Results graded publicly",
              body: "All outcomes auto-graded after games settle. Full record published — wins and losses both counted. No retroactive changes.",
            },
          ].map(({ icon, n, title, body }, i) => (
            <div key={n} style={{ padding: "22px 20px", borderRight: i < 2 ? "1px solid rgba(255,255,255,0.07)" : "none" }}>
              <div style={{ marginBottom: 12 }}>{icon}</div>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.14em", color: "rgba(99,102,241,0.7)", marginBottom: 6, textTransform: "uppercase" }}>{n}</div>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>{title}</div>
              <div style={{ fontSize: 12, color: "rgba(255,255,255,0.38)", lineHeight: 1.65 }}>{body}</div>
            </div>
          ))}
        </div>

        {/* ── Track record by market ── */}
        {Object.keys(bm).length > 0 && (
          <div style={{
            background: "rgba(255,255,255,0.02)",
            border: "1px solid rgba(255,255,255,0.07)",
            borderRadius: 16, overflow: "hidden", marginBottom: 32,
          }}>
            <div style={{
              padding: "13px 20px", borderBottom: "1px solid rgba(255,255,255,0.07)",
              display: "flex", alignItems: "center", justifyContent: "space-between",
            }}>
              <span style={{ fontWeight: 700, fontSize: 13 }}>Track Record by Market</span>
              <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.1em", color: "rgba(255,255,255,0.25)", textTransform: "uppercase" }}>card_pick only · no retroactive changes</span>
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                  {["Market","W–L","Win%","ROI","Units"].map(h => (
                    <th key={h} style={{
                      padding: "8px 20px", textAlign: h === "Market" ? "left" : "right",
                      fontSize: 9, fontWeight: 700, letterSpacing: "0.1em",
                      color: "rgba(255,255,255,0.25)", textTransform: "uppercase",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(bm).map(([key, m]) => {
                  if (m.wins + m.losses === 0) return null;
                  const label: Record<string,string> = { total:"Totals", nrfi:"NRFI", moneyline:"Moneyline", spread:"Spread", prop:"Props" };
                  return (
                    <tr key={key} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                      <td style={{ padding: "11px 20px", fontSize: 13, color: "rgba(255,255,255,0.6)", fontWeight: 500 }}>{label[key] ?? key}</td>
                      <td style={{ padding: "11px 20px", textAlign: "right", fontFamily: "monospace", fontSize: 12 }}>{m.wins}–{m.losses}</td>
                      <td style={{ padding: "11px 20px", textAlign: "right", fontFamily: "monospace", fontSize: 12, fontWeight: 700, color: m.win_rate >= 0.524 ? "#4ADE80" : "rgba(255,255,255,0.4)" }}>
                        {(m.win_rate * 100).toFixed(1)}%
                      </td>
                      <td style={{ padding: "11px 20px", textAlign: "right", fontFamily: "monospace", fontSize: 12, fontWeight: 700, color: m.roi >= 0 ? "#4ADE80" : "#f87171" }}>
                        {fmtRoi(m.roi)}
                      </td>
                      <td style={{ padding: "11px 20px", textAlign: "right", fontFamily: "monospace", fontSize: 12, color: m.units_profit >= 0 ? "#4ADE80" : "#f87171" }}>
                        {fmtPL(m.units_profit)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Bottom CTAs ── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div style={{
            background: "rgba(255,255,255,0.02)",
            border: "1px solid rgba(255,255,255,0.07)",
            borderRadius: 14, padding: "24px",
          }}>
            <div style={{ fontWeight: 800, fontSize: 15, letterSpacing: "-0.01em", marginBottom: 6 }}>Start free</div>
            <p style={{ fontSize: 12, color: "rgba(255,255,255,0.38)", lineHeight: 1.6, marginBottom: 20 }}>
              One best pick per day, delivered before first pitch. Free forever.
            </p>
            <EmailSignup source="bottom-free" cta="Get Pick of Day" />
          </div>

          <div style={{
            background: "rgba(99,102,241,0.06)",
            border: "1px solid rgba(99,102,241,0.28)",
            borderRadius: 14, padding: "24px",
          }}>
            <div style={{ fontWeight: 800, fontSize: 15, letterSpacing: "-0.01em", marginBottom: 6 }}>Full access</div>
            <p style={{ fontSize: 12, color: "rgba(255,255,255,0.38)", lineHeight: 1.6, marginBottom: 20 }}>
              Every pick, every market, every day. Full model output with edge scores.
            </p>
            <Link href="/early-access" style={{
              display: "block", textAlign: "center",
              background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
              color: "#fff", fontWeight: 800, fontSize: 13,
              padding: "11px 20px", borderRadius: 9, textDecoration: "none",
            }}>
              Get Early Access — $29/mo
            </Link>
            <div style={{ fontSize: 10, color: "rgba(255,255,255,0.2)", textAlign: "center", marginTop: 8 }}>
              Cancel anytime · Powered by Stripe
            </div>
          </div>
        </div>

        <p style={{ textAlign: "center", fontSize: 10, color: "rgba(255,255,255,0.12)", marginTop: 36, letterSpacing: "0.08em" }}>
          NOT FINANCIAL ADVICE · BET RESPONSIBLY · 21+ · RESULTS IN UNITS (1u = 1 UNIT STAKED FLAT)
        </p>
      </div>
    </div>
  );
}
