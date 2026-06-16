"use client";

import { useEffect, useState, useCallback } from "react";
import { SubscribeButton } from "@/components/SubscribeButton";

// ── Types ──────────────────────────────────────────────────────────────────
interface SlateRow {
  id: string;
  sport: string;
  market: string;
  matchup: string;
  away_team: string;
  home_team: string;
  direction: string;
  line: number | null;
  model_prob: number | null;
  implied_prob: number | null;
  edge_pct: number;
  odds: number | null;
  odds_fmt: string;
  book: string;
  commence_time: string | null;
  away_sp: string | null;
  home_sp: string | null;
  why: string | null;
  is_card_pick: boolean;
}

interface SlateResponse {
  dates: Record<string, string>;
  total: number;
  positive_ev: number;
  avg_edge: number;
  top_edge: number;
  card_picks: number;
  rows: SlateRow[];
}

// ── Helpers ────────────────────────────────────────────────────────────────
const SPORT_LABELS: Record<string, string> = {
  mlb: "MLB",
  nba: "NBA",
  nhl: "NHL",
};

const MARKET_LABELS: Record<string, string> = {
  moneyline: "Moneyline",
  spread: "Spread",
  total: "Total",
  nrfi: "NRFI",
  f5_total: "F5 Total",
};

function fmtPct(v: number | null): string {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}

function fmtEdge(v: number): string {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

function edgeColor(v: number): string {
  if (v >= 10) return "#22c55e";
  if (v >= 5) return "#86efac";
  if (v > 0) return "#bbf7d0";
  if (v < -5) return "#ef4444";
  return "#fca5a5";
}

function sportDot(sport: string): string {
  const dots: Record<string, string> = { mlb: "#3b82f6", nba: "#f97316", nhl: "#8b5cf6" };
  return dots[sport] ?? "#6b7280";
}

function formatGameTime(ts: string | null): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return ts;
  }
}

// ── Pill filter button ─────────────────────────────────────────────────────
function Pill({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "5px 12px",
        borderRadius: 20,
        fontSize: 12,
        fontWeight: 600,
        cursor: "pointer",
        border: "1px solid",
        borderColor: active ? "var(--accent)" : "var(--border)",
        background: active ? "var(--accent)" : "transparent",
        color: active ? "#fff" : "var(--text-secondary)",
        transition: "all 0.15s",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </button>
  );
}

// ── Row Card ───────────────────────────────────────────────────────────────
function RowCard({ row, isPro }: { row: SlateRow; isPro: boolean }) {
  const isPositive = row.edge_pct > 0;

  return (
    <div
      style={{
        background: "var(--surface)",
        border: `1px solid ${row.is_card_pick ? "var(--accent)" : "var(--border)"}`,
        borderRadius: 10,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        position: "relative",
      }}
    >
      {row.is_card_pick && (
        <div
          style={{
            position: "absolute",
            top: 10,
            right: 12,
            background: "var(--accent)",
            color: "#04130C",
            fontSize: 10,
            fontWeight: 700,
            padding: "2px 8px",
            borderRadius: 20,
            letterSpacing: "0.05em",
          }}
        >
          CARD PICK
        </div>
      )}

      {/* Matchup header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: sportDot(row.sport),
            marginTop: 5,
            flexShrink: 0,
          }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-bright)", lineHeight: 1.3 }}>
            {row.matchup}
          </div>
          {(row.away_sp || row.home_sp) && (
            <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 2 }}>
              {row.away_sp && `${row.away_team}: ${row.away_sp}`}
              {row.away_sp && row.home_sp && " · "}
              {row.home_sp && `${row.home_team}: ${row.home_sp}`}
            </div>
          )}
          {row.commence_time && (
            <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 2 }}>
              {formatGameTime(row.commence_time)}
            </div>
          )}
        </div>
      </div>

      {/* Pick details grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "6px 12px",
          background: "var(--bg)",
          borderRadius: 8,
          padding: "10px 12px",
        }}
      >
        {/* Pick */}
        <div>
          <div
            style={{
              fontSize: 10,
              color: "var(--text-secondary)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            Pick
          </div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-bright)", marginTop: 2 }}>
            {MARKET_LABELS[row.market] ?? row.market} {row.direction}
            {row.line != null
              ? ` ${row.line > 0 ? "+" : ""}${row.line}`
              : ""}
          </div>
        </div>

        {/* Odds / Book */}
        <div>
          <div
            style={{
              fontSize: 10,
              color: "var(--text-secondary)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            Odds / Book
          </div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-bright)", marginTop: 2 }}>
            {row.odds_fmt}{" "}
            <span style={{ fontWeight: 400, color: "var(--text-secondary)", fontSize: 11 }}>
              {row.book}
            </span>
          </div>
        </div>

        {/* Edge */}
        <div>
          <div
            style={{
              fontSize: 10,
              color: "var(--text-secondary)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            Edge
          </div>
          <div
            style={{
              fontSize: 15,
              fontWeight: 800,
              color: edgeColor(row.edge_pct),
              marginTop: 2,
              fontFamily: "var(--font-mono)",
            }}
          >
            {fmtEdge(row.edge_pct)}
          </div>
        </div>

        {/* Model vs Market */}
        <div>
          <div
            style={{
              fontSize: 10,
              color: "var(--text-secondary)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            Model vs Market
          </div>
          {isPro ? (
            <div
              style={{ fontSize: 12, fontWeight: 600, color: "var(--text-bright)", marginTop: 2 }}
            >
              <span style={{ color: isPositive ? "#22c55e" : "#ef4444" }}>
                {fmtPct(row.model_prob)}
              </span>
              <span style={{ color: "var(--text-secondary)" }}> vs </span>
              {fmtPct(row.implied_prob)}
            </div>
          ) : (
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: "var(--text-secondary)",
                marginTop: 2,
                filter: "blur(5px)",
                userSelect: "none",
              }}
            >
              63% vs 55%
            </div>
          )}
        </div>
      </div>

      {/* Why / reasoning */}
      {row.why && (
        <div
          style={{
            fontSize: 12,
            color: isPro ? "var(--text-secondary)" : "transparent",
            borderLeft: `2px solid ${isPro ? "var(--accent)" : "var(--border)"}`,
            paddingLeft: 10,
            lineHeight: 1.6,
            ...(isPro
              ? {}
              : {
                  background: "var(--border)",
                  borderRadius: "0 6px 6px 0",
                  paddingTop: 6,
                  paddingBottom: 6,
                  userSelect: "none",
                }),
          }}
        >
          {isPro ? row.why : "Model reasoning unlocked with Pro"}
        </div>
      )}
    </div>
  );
}

// ── Main Client Component ──────────────────────────────────────────────────
export function SlateClient({ isPro }: { isPro: boolean }) {
  const [data, setData] = useState<SlateResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [sport, setSport] = useState("all");
  const [market, setMarket] = useState("all");
  const [minEdge, setMinEdge] = useState(0);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (sport !== "all") params.set("sport", sport);
      if (market !== "all") params.set("market", market);
      if (minEdge > 0) params.set("min_edge", String(minEdge));
      const res = await fetch(`/api/slate?${params}`, { cache: "no-store" });
      if (!res.ok) throw new Error("fetch failed");
      setData(await res.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [sport, market, minEdge]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Derive available markets from data
  const markets = data ? [...new Set(data.rows.map((r) => r.market))] : [];
  const sportOptions: string[] = ["all", "mlb", "nba", "nhl"];

  return (
    <div style={{ maxWidth: 940, margin: "0 auto", padding: "28px 16px 60px" }}>

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Full Slate</div>
        <h1
          style={{
            fontSize: 26,
            fontWeight: 800,
            color: "var(--text-bright)",
            margin: 0,
            letterSpacing: "-0.015em",
          }}
        >
          Every game the model evaluated today
        </h1>
        <p style={{ fontSize: 14, color: "var(--text-secondary)", margin: "8px 0 0", maxWidth: 600 }}>
          Positive EV = model probability exceeds market implied probability.{" "}
          <span style={{ color: "var(--accent)", fontWeight: 600 }}>Card picks</span>{" "}
          are officially posted plays. Edge % and direction free.
          Model probabilities + reasoning unlock with Pro.
        </p>
      </div>

      {/* Stats bar */}
      {data && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 1,
            background: "var(--border)",
            borderRadius: 10,
            overflow: "hidden",
            marginBottom: 20,
          }}
        >
          {[
            { label: "Evaluated", val: String(data.total) },
            { label: "Positive EV", val: String(data.positive_ev) },
            { label: "Card Picks", val: String(data.card_picks) },
            { label: "Top Edge", val: fmtEdge(data.top_edge) },
          ].map((s) => (
            <div
              key={s.label}
              style={{
                background: "var(--surface)",
                padding: "12px 16px",
                textAlign: "center",
              }}
            >
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 800,
                  color: "var(--text-bright)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {s.val}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 2 }}>
                {s.label}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          marginBottom: 16,
          alignItems: "center",
        }}
      >
        {/* Sport pills */}
        <div style={{ display: "flex", gap: 4 }}>
          {sportOptions.map((s) => (
            <Pill
              key={s}
              label={s === "all" ? "All Sports" : (SPORT_LABELS[s] ?? s.toUpperCase())}
              active={sport === s}
              onClick={() => setSport(s)}
            />
          ))}
        </div>

        <div style={{ width: 1, height: 20, background: "var(--border)" }} />

        {/* Market pills — generated from data */}
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          <Pill label="All Markets" active={market === "all"} onClick={() => setMarket("all")} />
          {markets.map((m) => (
            <Pill
              key={m}
              label={MARKET_LABELS[m] ?? m}
              active={market === m}
              onClick={() => setMarket(m)}
            />
          ))}
        </div>

        <div style={{ width: 1, height: 20, background: "var(--border)" }} />

        {/* Min edge pills */}
        <div style={{ display: "flex", gap: 4 }}>
          {[0, 5, 10].map((e) => (
            <Pill
              key={e}
              label={e === 0 ? "All" : `${e}%+ Edge`}
              active={minEdge === e}
              onClick={() => setMinEdge(e)}
            />
          ))}
        </div>
      </div>

      {/* Pro upgrade CTA */}
      {!isPro && (
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 10,
            padding: "14px 18px",
            marginBottom: 20,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-bright)" }}>
              Model probabilities + reasoning locked
            </div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 3 }}>
              See the exact ensemble calculation behind every pick. $19/mo — cancel anytime.
            </div>
          </div>
          <SubscribeButton />
        </div>
      )}

      {/* Rows */}
      {loading ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "var(--text-secondary)" }}>
          Loading slate…
        </div>
      ) : !data || data.rows.length === 0 ? (
        <div
          style={{
            textAlign: "center",
            padding: "60px 0",
            color: "var(--text-secondary)",
            lineHeight: 1.7,
          }}
        >
          No games found.
          <br />
          <span style={{ fontSize: 12 }}>
            Model runs at 9am ET. Check back after picks are generated.
          </span>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
            gap: 12,
          }}
        >
          {data.rows.map((row) => (
            <RowCard key={row.id} row={row} isPro={isPro} />
          ))}
        </div>
      )}

      {/* Footer */}
      <div
        style={{
          marginTop: 40,
          fontSize: 11,
          color: "var(--text-secondary)",
          textAlign: "center",
          lineHeight: 1.8,
        }}
      >
        Data refreshes every 2 minutes. Model runs at 9am ET daily.
        <br />
        Edge = model probability minus market implied probability (best available line).
        <br />
        All picks logged before first pitch with SHA-256 timestamp. Public ledger at{" "}
        <a href="/record" style={{ color: "var(--accent)" }}>
          /record
        </a>
        .
      </div>
    </div>
  );
}
