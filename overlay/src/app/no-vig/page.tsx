"use client";

import { useState, useCallback } from "react";

// ── Math ───────────────────────────────────────────────────────────────────

function parseOdds(raw: string): number | null {
  const s = raw.trim().replace(/\s/g, "");
  if (!s) return null;
  const n = parseFloat(s);
  if (isNaN(n) || n === 0) return null;
  // Validate plausible American odds range
  if (n > 0 && n < 100) return null; // not valid (e.g. "50" isn't a real line)
  return n;
}

function americanToImplied(odds: number): number {
  if (odds < 0) return (-odds) / (-odds + 100);
  return 100 / (odds + 100);
}

function impliedToAmerican(p: number): number {
  if (p <= 0 || p >= 1) return NaN;
  if (p >= 0.5) return Math.round(-p / (1 - p) * 100);
  return Math.round((1 - p) / p * 100);
}

function fmtAmerican(n: number): string {
  if (isNaN(n)) return "—";
  return n > 0 ? `+${n}` : `${n}`;
}

function fmtPct(n: number, decimals = 1): string {
  return `${(n * 100).toFixed(decimals)}%`;
}

interface OddsLine {
  raw: string;
  odds: number | null;
  implied: number | null;
}

interface Result {
  lines: OddsLine[];
  totalImplied: number;
  vigPct: number;         // vig as a % of 100 (e.g. 4.5)
  holdPct: number;        // hold = totalImplied - 1 as %
  noVigProbs: number[];
  noVigOdds: number[];
  breakEven: number[];
}

function calculate(lines: OddsLine[]): Result | null {
  const valid = lines.filter((l) => l.odds != null && l.implied != null);
  if (valid.length < 2) return null;

  const totalImplied = valid.reduce((s, l) => s + (l.implied ?? 0), 0);
  const holdPct = (totalImplied - 1) * 100;
  const vigPct = ((totalImplied - 1) / totalImplied) * 100;

  const noVigProbs = valid.map((l) => (l.implied ?? 0) / totalImplied);
  const noVigOdds = noVigProbs.map(impliedToAmerican);

  // Break-even = implied prob of the no-vig odds (to cover vig you need to hit this %)
  const breakEven = noVigProbs.map((p) => p); // same as no-vig prob in fair market

  return {
    lines: valid,
    totalImplied,
    vigPct,
    holdPct,
    noVigProbs,
    noVigOdds,
    breakEven,
  };
}

// ── UI ─────────────────────────────────────────────────────────────────────

function OddsInput({
  value,
  onChange,
  placeholder,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  label: string;
}) {
  return (
    <div style={{ flex: 1, minWidth: 140 }}>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-secondary)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 6,
        }}
      >
        {label}
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
          fontSize: 18,
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

const PRESETS = [
  { label: "Pick'em", odds: ["-110", "-110"] },
  { label: "Heavy fav", odds: ["-200", "+170"] },
  { label: "MLB total", odds: ["-115", "-105"] },
  { label: "3-way", odds: ["+120", "+240", "+200"] },
];

export default function NoVigPage() {
  const [inputs, setInputs] = useState(["", ""]);
  const [result, setResult] = useState<Result | null>(null);
  const [calculated, setCalculated] = useState(false);

  const updateInput = useCallback((i: number, v: string) => {
    setInputs((prev) => {
      const next = [...prev];
      next[i] = v;
      return next;
    });
    setCalculated(false);
    setResult(null);
  }, []);

  const addLeg = () => {
    if (inputs.length < 4) setInputs((p) => [...p, ""]);
  };

  const removeLeg = (i: number) => {
    if (inputs.length > 2) setInputs((p) => p.filter((_, idx) => idx !== i));
    setResult(null);
    setCalculated(false);
  };

  const loadPreset = (odds: string[]) => {
    setInputs(odds);
    setResult(null);
    setCalculated(false);
  };

  const run = () => {
    const lines: OddsLine[] = inputs.map((raw) => {
      const odds = parseOdds(raw);
      return { raw, odds, implied: odds != null ? americanToImplied(odds) : null };
    });
    setResult(calculate(lines));
    setCalculated(true);
  };

  const vigColor = result
    ? result.holdPct > 8 ? "#ef4444"
    : result.holdPct > 5 ? "#f97316"
    : "#22c55e"
    : "var(--text-bright)";

  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "28px 16px 80px" }}>

      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Free Tool</div>
        <h1
          style={{
            fontSize: 28,
            fontWeight: 800,
            color: "var(--text-bright)",
            margin: 0,
            letterSpacing: "-0.015em",
          }}
        >
          No-Vig Fair Odds Calculator
        </h1>
        <p style={{ fontSize: 14, color: "var(--text-secondary)", margin: "10px 0 0", lineHeight: 1.6 }}>
          Paste any two-sided (or three-way) market to strip the book's margin.
          Reveals the true fair odds and the exact vig percentage you're paying.
        </p>
      </div>

      {/* Presets */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Quick load
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {PRESETS.map((p) => (
            <button
              key={p.label}
              onClick={() => loadPreset(p.odds)}
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
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Inputs */}
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 12,
          padding: "20px",
          marginBottom: 16,
        }}
      >
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
          {inputs.map((val, i) => (
            <div key={i} style={{ flex: 1, minWidth: 120, position: "relative" }}>
              <OddsInput
                value={val}
                onChange={(v) => updateInput(i, v)}
                placeholder={i === 0 ? "-110" : i === 1 ? "-110" : "+200"}
                label={
                  inputs.length === 2
                    ? i === 0 ? "Side A" : "Side B"
                    : `Outcome ${i + 1}`
                }
              />
              {inputs.length > 2 && (
                <button
                  onClick={() => removeLeg(i)}
                  style={{
                    position: "absolute",
                    top: 0,
                    right: 0,
                    background: "none",
                    border: "none",
                    color: "var(--text-secondary)",
                    cursor: "pointer",
                    fontSize: 14,
                    padding: "0 4px",
                  }}
                >
                  ×
                </button>
              )}
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={run}
            className="btn-primary"
            style={{ flex: 1, padding: "11px 0", fontSize: 14, fontWeight: 700, borderRadius: 8 }}
          >
            Calculate
          </button>
          {inputs.length < 4 && (
            <button
              onClick={addLeg}
              style={{
                padding: "11px 20px",
                fontSize: 13,
                fontWeight: 600,
                borderRadius: 8,
                border: "1px solid var(--border)",
                background: "transparent",
                color: "var(--text-secondary)",
                cursor: "pointer",
              }}
            >
              + Outcome
            </button>
          )}
        </div>
      </div>

      {/* Results */}
      {calculated && !result && (
        <div
          style={{
            padding: "16px 20px",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 12,
            color: "var(--text-secondary)",
            fontSize: 14,
          }}
        >
          Enter valid American odds (e.g. -110, +150) in at least two fields.
        </div>
      )}

      {result && (
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 12,
            overflow: "hidden",
          }}
        >
          {/* Vig summary bar */}
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
                label: "Book Hold",
                val: `${result.holdPct.toFixed(2)}%`,
                sub: "% of $100 wagered the book keeps",
                color: vigColor,
              },
              {
                label: "Total Implied",
                val: fmtPct(result.totalImplied),
                sub: "raw sum of implied probs",
                color: "var(--text-bright)",
              },
              {
                label: "Vig (juice)",
                val: `${result.vigPct.toFixed(2)}%`,
                sub: "% of wagers that is overround",
                color: "var(--text-bright)",
              },
            ].map((s) => (
              <div
                key={s.label}
                style={{ background: "var(--surface)", padding: "16px 14px", textAlign: "center" }}
              >
                <div
                  style={{
                    fontSize: 22,
                    fontWeight: 800,
                    color: s.color,
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {s.val}
                </div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-secondary)", marginTop: 4 }}>
                  {s.label}
                </div>
                <div style={{ fontSize: 10, color: "var(--text-secondary)", marginTop: 2, lineHeight: 1.4 }}>
                  {s.sub}
                </div>
              </div>
            ))}
          </div>

          {/* Per-outcome breakdown */}
          <div style={{ padding: "20px" }}>
            <div
              style={{
                fontSize: 11,
                color: "var(--text-secondary)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                marginBottom: 12,
              }}
            >
              Per-outcome breakdown
            </div>

            {/* Table header */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 1fr 1fr",
                gap: 8,
                padding: "6px 12px",
                fontSize: 10,
                color: "var(--text-secondary)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              <div>Outcome</div>
              <div style={{ textAlign: "right" }}>Your Odds</div>
              <div style={{ textAlign: "right" }}>Implied</div>
              <div style={{ textAlign: "right" }}>Fair Odds</div>
            </div>

            {result.lines.map((line, i) => (
              <div
                key={i}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr 1fr 1fr",
                  gap: 8,
                  padding: "10px 12px",
                  background: i % 2 === 0 ? "var(--bg)" : "transparent",
                  borderRadius: 6,
                  alignItems: "center",
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)" }}>
                  {inputs.length === 2 ? (i === 0 ? "Side A" : "Side B") : `Outcome ${i + 1}`}
                </div>
                <div
                  style={{
                    fontSize: 15,
                    fontWeight: 700,
                    color: "var(--text-bright)",
                    textAlign: "right",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {fmtAmerican(line.odds ?? 0)}
                </div>
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    color: "var(--text-secondary)",
                    textAlign: "right",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {fmtPct(line.implied ?? 0)}
                </div>
                <div
                  style={{
                    fontSize: 15,
                    fontWeight: 800,
                    color: "#22c55e",
                    textAlign: "right",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {fmtAmerican(result.noVigOdds[i])}
                  <div
                    style={{
                      fontSize: 10,
                      fontWeight: 500,
                      color: "var(--text-secondary)",
                      marginTop: 2,
                    }}
                  >
                    {fmtPct(result.noVigProbs[i])} true prob
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Interpretation */}
          <div
            style={{
              borderTop: "1px solid var(--border)",
              padding: "16px 20px",
              fontSize: 13,
              color: "var(--text-secondary)",
              lineHeight: 1.7,
            }}
          >
            {result.holdPct > 8 ? (
              <>
                <span style={{ color: "#ef4444", fontWeight: 700 }}>High hold ({result.holdPct.toFixed(1)}%)</span>
                {" "}— this is a high-juice market. You need to win at a higher rate just to break even.
                Shop for better lines or skip this market.
              </>
            ) : result.holdPct > 5 ? (
              <>
                <span style={{ color: "#f97316", fontWeight: 700 }}>Moderate hold ({result.holdPct.toFixed(1)}%)</span>
                {" "}— typical for a retail book. Compare with Pinnacle for sharper lines.
              </>
            ) : (
              <>
                <span style={{ color: "#22c55e", fontWeight: 700 }}>Low hold ({result.holdPct.toFixed(1)}%)</span>
                {" "}— sharp-money pricing. The book is not protecting much margin here.
              </>
            )}
          </div>
        </div>
      )}

      {/* Explainer */}
      <div
        style={{
          marginTop: 40,
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 12,
          padding: "20px 24px",
        }}
      >
        <h2
          style={{
            fontSize: 16,
            fontWeight: 700,
            color: "var(--text-bright)",
            margin: "0 0 12px",
          }}
        >
          How no-vig odds work
        </h2>
        <div
          style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.8, display: "flex", flexDirection: "column", gap: 12 }}
        >
          <p style={{ margin: 0 }}>
            Every two-sided betting market has a built-in margin (the "vig" or "juice").
            A standard -110 / -110 line has a{" "}
            <strong style={{ color: "var(--text-bright)" }}>4.5% hold</strong> — meaning if
            you bet both sides at equal amounts, the book keeps 4.5% of the total money wagered.
          </p>
          <p style={{ margin: 0 }}>
            No-vig odds strip that margin. The formula: convert each side to implied
            probability, sum them (the sum will be greater than 100%), then normalize
            each back to a 100% total. Those normalized probabilities reflect what
            the book <em>actually</em> thinks the odds are, without the markup.
          </p>
          <p style={{ margin: 0 }}>
            This tool is what sharp bettors use to determine whether a line is actually
            good value. When your model says 63% and the no-vig implied is 55%, that's
            an 8-point edge — positive EV regardless of which book you're on.
          </p>
        </div>
      </div>

      {/* Link to slate */}
      <div
        style={{
          marginTop: 24,
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
            See today's full model slate
          </div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 3 }}>
            MLB + NBA · edge % · model prob vs market implied · card picks
          </div>
        </div>
        <a href="/slate" className="btn-primary" style={{ padding: "8px 18px", fontSize: 13, flexShrink: 0 }}>
          View Slate →
        </a>
      </div>
    </div>
  );
}
