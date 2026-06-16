"use client";

import { useState, useCallback } from "react";

// ── Math ───────────────────────────────────────────────────────────────────

function parseOdds(raw: string): number | null {
  const s = raw.trim().replace(/\s/g, "");
  if (!s) return null;
  const n = parseFloat(s);
  if (isNaN(n) || n === 0) return null;
  if (Math.abs(n) < 100) return null; // not valid American odds
  return n;
}

/** Convert American odds to no-vig implied probability.
 *  For a two-sided market where both sides are at the same odds (pick'em),
 *  the no-vig is just the implied. For a single side we need context.
 *  Here we return the raw implied (with vig) — user inputs one side at a time.
 */
function americanToImplied(odds: number): number {
  if (odds < 0) return (-odds) / (-odds + 100);
  return 100 / (odds + 100);
}

/** No-vig probability for one side, given BOTH sides of the market */
function noVigProb(sideImplied: number, totalImplied: number): number {
  return sideImplied / totalImplied;
}

function fmtAmerican(n: number): string {
  if (!isFinite(n)) return "—";
  return n > 0 ? `+${Math.round(n)}` : `${Math.round(n)}`;
}

function fmtPct(n: number, d = 2): string {
  return `${(n * 100).toFixed(d)}%`;
}

/** CLV = no-vig closing prob for your side minus no-vig opening prob for your side.
 *  Positive = you got better of close (beat the book). Negative = you got worse.
 */
function calcCLV(
  betOdds: number,
  closingYour: number,
  closingOpp: number,
): {
  betImplied: number;
  closingImplied: number;
  closingOppImplied: number;
  totalClosing: number;
  noVigBet: number;    // no-vig prob AT TIME OF BET (we only have one side, assume juice is 4.76%)
  noVigClose: number;  // no-vig prob at closing
  clvPct: number;      // CLV in probability points (e.g. 0.045 = 4.5pp)
  clvOdds: number;     // CLV in American odds equivalent
} {
  const betImplied = americanToImplied(betOdds);
  const closingImplied = americanToImplied(closingYour);
  const closingOppImplied = americanToImplied(closingOpp);
  const totalClosing = closingImplied + closingOppImplied;

  // For the bet side at open: we only know one side, so assume standard -110/-110 vig
  // This means no-vig open ≈ betImplied / (betImplied + 1 - betImplied) * (1/1.0476)
  // Simplification: standard hold = 4.76% for -110/-110 market
  // Instead of guessing the other side, we normalize with 2-sided assumption:
  // If user provides both sides at open, we'd be exact. For now, use close vig as proxy.
  const noVigBet = betImplied / (betImplied + (1 - betImplied) * (totalClosing / 1)); // rough
  // Simpler: assume vig is same at open as close, normalize similarly
  const oppBetImplied = 1 - betImplied + (totalClosing - 1) * betImplied; // rough
  const nvBet = betImplied / (betImplied + oppBetImplied);

  const noVigClose = closingImplied / totalClosing;
  // CLV = probability YOU got minus probability at close (your side)
  // Positive = you beat the close (got a better line than where it closed)
  const clvPct = noVigClose - noVigBet;

  // Convert CLV back to American odds delta
  const impliedClose = noVigClose;
  const impliedYours = noVigBet;
  const oddsClose = impliedClose >= 0.5
    ? -(impliedClose / (1 - impliedClose)) * 100
    : (1 - impliedClose) / impliedClose * 100;
  const oddsYours = impliedYours >= 0.5
    ? -(impliedYours / (1 - impliedYours)) * 100
    : (1 - impliedYours) / impliedYours * 100;
  const clvOdds = oddsYours - oddsClose; // positive = you had better odds than close

  return {
    betImplied,
    closingImplied,
    closingOppImplied,
    totalClosing,
    noVigBet: noVigBet,
    noVigClose,
    clvPct,
    clvOdds,
  };
}

// ── Streak tracker entry ───────────────────────────────────────────────────

interface StreakEntry {
  id: string;
  label: string;
  betOdds: number;
  closingYour: number;
  closingOpp: number;
  clvPct: number;
  clvOdds: number;
  positive: boolean;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function clvLabel(clvPct: number): { text: string; color: string; detail: string } {
  const pp = clvPct * 100;
  if (pp >= 5) return { text: "Strong beat", color: "#22c55e", detail: "Top ~5% of all sharp bets. Clear positive EV." };
  if (pp >= 2) return { text: "Beat the close", color: "#86efac", detail: "Meaningful CLV. Good line shopping paid off." };
  if (pp >= 0) return { text: "Slight beat", color: "#bbf7d0", detail: "Small positive CLV. Acceptable — keep hunting for better." };
  if (pp >= -2) return { text: "Slight miss", color: "#fca5a5", detail: "Moved slightly against you. May have acted too late." };
  if (pp >= -5) return { text: "Missed close", color: "#f97316", detail: "Significant CLV loss. The market moved away — reconsider timing." };
  return { text: "Bad timing", color: "#ef4444", detail: "You paid more vig than the closing price. Evaluate the source." };
}

// ── UI ─────────────────────────────────────────────────────────────────────

function InputGroup({
  label,
  sub,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  sub?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <div>
      <div style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-bright)" }}>{label}</div>
        {sub && <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>{sub}</div>}
      </div>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%",
          background: "var(--bg)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: "10px 14px",
          fontSize: 20,
          fontWeight: 700,
          color: "var(--text-bright)",
          fontFamily: "var(--font-mono)",
          outline: "none",
          boxSizing: "border-box",
        }}
      />
    </div>
  );
}

const EXAMPLES = [
  { label: "Good timing", bet: "-108", closeYour: "-115", closeOpp: "-105", note: "You got -108, closed -115 — beat the close by ~3pp" },
  { label: "Bad timing", bet: "-115", closeYour: "-108", closeOpp: "-112", note: "Line moved against you after you bet" },
  { label: "Sharp move", bet: "+105", closeYour: "-105", closeOpp: "-115", note: "Reverse line move — you were on the sharp side" },
];

export default function CLVCalculatorPage() {
  const [betOdds, setBetOdds] = useState("");
  const [closeYour, setCloseYour] = useState("");
  const [closeOpp, setCloseOpp] = useState("");
  const [label, setLabel] = useState("");
  const [result, setResult] = useState<ReturnType<typeof calcCLV> | null>(null);
  const [error, setError] = useState("");
  const [streak, setStreak] = useState<StreakEntry[]>([]);

  const calculate = useCallback(() => {
    const bet = parseOdds(betOdds);
    const cy = parseOdds(closeYour);
    const co = parseOdds(closeOpp);
    if (!bet || !cy || !co) {
      setError("Enter valid American odds in all three fields (e.g. -110, +105).");
      setResult(null);
      return;
    }
    setError("");
    const r = calcCLV(bet, cy, co);
    setResult(r);
  }, [betOdds, closeYour, closeOpp]);

  const addToStreak = useCallback(() => {
    if (!result) return;
    const bet = parseOdds(betOdds)!;
    const cy = parseOdds(closeYour)!;
    const co = parseOdds(closeOpp)!;
    setStreak((prev) => [
      ...prev,
      {
        id: Date.now().toString(),
        label: label.trim() || `Bet ${prev.length + 1}`,
        betOdds: bet,
        closingYour: cy,
        closingOpp: co,
        clvPct: result.clvPct,
        clvOdds: result.clvOdds,
        positive: result.clvPct > 0,
      },
    ]);
    // Clear form for next
    setBetOdds("");
    setCloseYour("");
    setCloseOpp("");
    setLabel("");
    setResult(null);
  }, [result, betOdds, closeYour, closeOpp, label]);

  const clearStreak = () => setStreak([]);

  const streakAvgCLV = streak.length
    ? streak.reduce((s, e) => s + e.clvPct, 0) / streak.length
    : null;
  const streakPositive = streak.filter((e) => e.positive).length;

  const res = result;
  const badge = res ? clvLabel(res.clvPct) : null;

  return (
    <div style={{ maxWidth: 680, margin: "0 auto", padding: "28px 16px 80px" }}>

      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Free Tool</div>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--text-bright)", margin: 0, letterSpacing: "-0.015em" }}>
          Closing Line Value Calculator
        </h1>
        <p style={{ fontSize: 14, color: "var(--text-secondary)", margin: "10px 0 0", lineHeight: 1.7, maxWidth: 560 }}>
          CLV is the single best predictor of long-run betting profitability — better than W/L.
          If you consistently beat the closing line, you're winning against sharp money. If you don't,
          you're going to lose regardless of recent results.
        </p>
      </div>

      {/* Examples */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Load an example
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              onClick={() => {
                setBetOdds(ex.bet);
                setCloseYour(ex.closeYour);
                setCloseOpp(ex.closeOpp);
                setResult(null);
                setError("");
              }}
              title={ex.note}
              style={{
                padding: "5px 14px",
                borderRadius: 20,
                fontSize: 12,
                fontWeight: 600,
                border: "1px solid var(--border)",
                background: "transparent",
                color: "var(--text-secondary)",
                cursor: "pointer",
              }}
            >
              {ex.label}
            </button>
          ))}
        </div>
      </div>

      {/* Input form */}
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 12,
          padding: "20px",
          marginBottom: 16,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <InputGroup
          label="Odds you got (American)"
          sub="The line when you placed your bet"
          value={betOdds}
          onChange={setBetOdds}
          placeholder="-108"
        />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <InputGroup
            label="Closing — your side"
            sub="Final line for the side you bet"
            value={closeYour}
            onChange={setCloseYour}
            placeholder="-115"
          />
          <InputGroup
            label="Closing — other side"
            sub="Final line for the opposite side"
            value={closeOpp}
            onChange={setCloseOpp}
            placeholder="+105"
          />
        </div>

        <InputGroup
          label="Label (optional)"
          sub="For your streak tracker below"
          value={label}
          onChange={setLabel}
          placeholder="LAD ML vs CHC"
        />

        <button
          onClick={calculate}
          className="btn-primary"
          style={{ padding: "12px 0", fontSize: 14, fontWeight: 700, borderRadius: 8 }}
        >
          Calculate CLV
        </button>

        {error && (
          <div style={{ fontSize: 13, color: "#ef4444", marginTop: -8 }}>{error}</div>
        )}
      </div>

      {/* Result */}
      {res && badge && (
        <div
          style={{
            background: "var(--surface)",
            border: `1px solid ${badge.color}`,
            borderRadius: 12,
            overflow: "hidden",
            marginBottom: 16,
          }}
        >
          {/* CLV headline */}
          <div
            style={{
              padding: "20px 24px",
              background: "var(--bg)",
              display: "flex",
              alignItems: "center",
              gap: 20,
              flexWrap: "wrap",
            }}
          >
            <div>
              <div style={{ fontSize: 11, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Closing Line Value
              </div>
              <div
                style={{
                  fontSize: 40,
                  fontWeight: 800,
                  color: badge.color,
                  fontFamily: "var(--font-mono)",
                  lineHeight: 1.1,
                  marginTop: 4,
                }}
              >
                {res.clvPct >= 0 ? "+" : ""}{(res.clvPct * 100).toFixed(2)}pp
              </div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
                {res.clvOdds >= 0 ? "+" : ""}{res.clvOdds.toFixed(1)} American odds vs close
              </div>
            </div>
            <div
              style={{
                padding: "10px 16px",
                background: "var(--surface)",
                borderRadius: 8,
                border: `1px solid ${badge.color}`,
              }}
            >
              <div style={{ fontSize: 14, fontWeight: 800, color: badge.color }}>{badge.text}</div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4, maxWidth: 220, lineHeight: 1.5 }}>
                {badge.detail}
              </div>
            </div>
          </div>

          {/* Breakdown grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 1,
              background: "var(--border)",
            }}
          >
            {[
              {
                label: "Your implied prob",
                val: fmtPct(res.betImplied),
                sub: "raw (with vig)",
              },
              {
                label: "No-vig open",
                val: fmtPct(res.noVigBet),
                sub: "your side, vig stripped",
              },
              {
                label: "No-vig close",
                val: fmtPct(res.noVigClose),
                sub: "sharp money settled here",
              },
            ].map((s) => (
              <div
                key={s.label}
                style={{
                  background: "var(--surface)",
                  padding: "14px 12px",
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: 18, fontWeight: 800, color: "var(--text-bright)", fontFamily: "var(--font-mono)" }}>
                  {s.val}
                </div>
                <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-secondary)", marginTop: 4 }}>
                  {s.label}
                </div>
                <div style={{ fontSize: 10, color: "var(--text-secondary)", marginTop: 2 }}>
                  {s.sub}
                </div>
              </div>
            ))}
          </div>

          {/* Closing market breakdown */}
          <div style={{ padding: "14px 20px", borderTop: "1px solid var(--border)" }}>
            <div style={{ fontSize: 11, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>
              Closing market
            </div>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
              {[
                { side: "Your side", odds: closeYour, implied: res.closingImplied, novig: res.noVigClose },
                { side: "Other side", odds: closeOpp, implied: res.closingOppImplied, novig: 1 - res.noVigClose },
              ].map((s) => (
                <div
                  key={s.side}
                  style={{
                    flex: 1,
                    minWidth: 140,
                    background: "var(--bg)",
                    borderRadius: 8,
                    padding: "10px 14px",
                  }}
                >
                  <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 4 }}>{s.side}</div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: "var(--text-bright)", fontFamily: "var(--font-mono)" }}>
                    {s.odds}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
                    {fmtPct(s.implied)} implied → <strong style={{ color: "var(--text-bright)" }}>{fmtPct(s.novig)}</strong> no-vig
                  </div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 10 }}>
              Hold: {((res.totalClosing - 1) * 100).toFixed(2)}% · Total implied: {fmtPct(res.totalClosing)}
            </div>
          </div>

          {/* Add to streak button */}
          <div style={{ padding: "14px 20px", borderTop: "1px solid var(--border)", background: "var(--bg)" }}>
            <button
              onClick={addToStreak}
              style={{
                padding: "10px 20px",
                borderRadius: 8,
                border: "1px solid var(--border)",
                background: "var(--surface)",
                color: "var(--text-bright)",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              + Add to CLV Tracker
            </button>
          </div>
        </div>
      )}

      {/* CLV Streak Tracker */}
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 12,
          overflow: "hidden",
          marginBottom: 40,
        }}
      >
        <div
          style={{
            padding: "14px 20px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-bright)" }}>
              CLV Tracker
            </div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
              Track your closing line value across multiple bets this session
            </div>
          </div>
          {streak.length > 0 && (
            <button
              onClick={clearStreak}
              style={{
                fontSize: 12,
                color: "var(--text-secondary)",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "4px 8px",
              }}
            >
              Clear
            </button>
          )}
        </div>

        {streak.length === 0 ? (
          <div
            style={{
              padding: "32px 20px",
              textAlign: "center",
              color: "var(--text-secondary)",
              fontSize: 13,
            }}
          >
            Calculate a CLV above and click "Add to CLV Tracker" to build your streak.
            <br />
            <span style={{ fontSize: 11, marginTop: 6, display: "block" }}>
              Data stays in this browser session only — nothing is stored.
            </span>
          </div>
        ) : (
          <>
            {/* Summary bar */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 1fr",
                gap: 1,
                background: "var(--border)",
              }}
            >
              {[
                {
                  label: "Avg CLV",
                  val: streakAvgCLV != null
                    ? `${streakAvgCLV >= 0 ? "+" : ""}${(streakAvgCLV * 100).toFixed(2)}pp`
                    : "—",
                  color: (streakAvgCLV ?? 0) > 0 ? "#22c55e" : "#ef4444",
                },
                {
                  label: "Beat the close",
                  val: `${streakPositive}/${streak.length}`,
                  color: "var(--text-bright)",
                },
                {
                  label: "CLV Verdict",
                  val: (streakAvgCLV ?? 0) > 0.02
                    ? "Sharp"
                    : (streakAvgCLV ?? 0) > 0
                    ? "Slight edge"
                    : "No edge",
                  color: (streakAvgCLV ?? 0) > 0.02 ? "#22c55e" : (streakAvgCLV ?? 0) > 0 ? "#86efac" : "#ef4444",
                },
              ].map((s) => (
                <div
                  key={s.label}
                  style={{
                    background: "var(--surface)",
                    padding: "12px 16px",
                    textAlign: "center",
                  }}
                >
                  <div style={{ fontSize: 18, fontWeight: 800, color: s.color, fontFamily: "var(--font-mono)" }}>
                    {s.val}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 3 }}>{s.label}</div>
                </div>
              ))}
            </div>

            {/* Bet list */}
            <div>
              {streak.map((entry, i) => (
                <div
                  key={entry.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 16px",
                    borderBottom: i < streak.length - 1 ? "1px solid var(--border)" : "none",
                    background: i % 2 === 0 ? "transparent" : "var(--bg)",
                  }}
                >
                  <div
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: entry.positive ? "#22c55e" : "#ef4444",
                      flexShrink: 0,
                    }}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-bright)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {entry.label}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                      Bet {fmtAmerican(entry.betOdds)} · Close {fmtAmerican(entry.closingYour)} / {fmtAmerican(entry.closingOpp)}
                    </div>
                  </div>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 800,
                      color: entry.positive ? "#22c55e" : "#ef4444",
                      fontFamily: "var(--font-mono)",
                      flexShrink: 0,
                    }}
                  >
                    {entry.clvPct >= 0 ? "+" : ""}{(entry.clvPct * 100).toFixed(2)}pp
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Educational section */}
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 12,
          padding: "20px 24px",
          marginBottom: 20,
        }}
      >
        <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--text-bright)", margin: "0 0 16px" }}>
          Why CLV matters more than W/L
        </h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7 }}>
          <p style={{ margin: 0 }}>
            <strong style={{ color: "var(--text-bright)" }}>The sportsbook line is a crowd-sourced probability estimate.</strong>{" "}
            As bets flow in, the line moves to reflect where the money (especially sharp money) lands.
            The closing line is the most accurate reflection of true probability — it incorporates
            everything the market knows.
          </p>
          <p style={{ margin: 0 }}>
            <strong style={{ color: "var(--text-bright)" }}>If you consistently get better odds than the close,</strong>{" "}
            you're getting better prices than the sharpest bettors in the world think is fair.
            That's positive CLV — and academic research shows it's the strongest predictor of
            long-run profitability in sports betting.
          </p>
          <p style={{ margin: 0 }}>
            <strong style={{ color: "var(--text-bright)" }}>W/L is noise over small samples.</strong>{" "}
            A bettor with +55% win rate on 50 bets could be running hot. A bettor with
            consistent +3pp CLV over 50 bets is almost certainly skilled. The Pinnacle model
            (sharpest book in the world) uses this to spot winners and limit accounts.
          </p>
          <div
            style={{
              background: "var(--bg)",
              borderRadius: 8,
              padding: "12px 16px",
              fontSize: 12,
            }}
          >
            <strong style={{ color: "var(--text-bright)" }}>Rule of thumb:</strong>
            <ul style={{ margin: "8px 0 0", paddingLeft: 20, lineHeight: 2 }}>
              <li><strong style={{ color: "#22c55e" }}>+3pp avg CLV or better</strong> — sharp bettor, real edge</li>
              <li><strong style={{ color: "#86efac" }}>+1–3pp avg CLV</strong> — beating the market, sustainable with discipline</li>
              <li><strong style={{ color: "var(--text-secondary)" }}>-1pp to +1pp</strong> — roughly break-even, within noise</li>
              <li><strong style={{ color: "#ef4444" }}>Below -2pp avg CLV</strong> — paying more than fair value consistently</li>
            </ul>
          </div>
        </div>
      </div>

      {/* CTA */}
      <div
        style={{
          padding: "14px 20px",
          background: "var(--surface)",
          border: "1px solid var(--accent)",
          borderRadius: 10,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
        }}
      >
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-bright)" }}>
            See the model's CLV track record
          </div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 3 }}>
            Every pick SHA-256 timestamped before first pitch. Full CLV ledger on the record page.
          </div>
        </div>
        <a href="/record" className="btn-primary" style={{ padding: "8px 18px", fontSize: 13, flexShrink: 0 }}>
          View Record →
        </a>
      </div>
    </div>
  );
}
