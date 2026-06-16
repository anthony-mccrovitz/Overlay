const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export async function fetchPicks(sport: string = "mlb", bankroll: number = 0) {
  const params = new URLSearchParams({ bankroll: bankroll.toString() });
  const res = await fetch(`${API_BASE}/picks/${sport}?${params}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to fetch picks");
  return res.json();
}

export async function fetchOdds(sport: string = "mlb") {
  const res = await fetch(`${API_BASE}/odds/${sport}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch odds");
  return res.json();
}

export async function fetchRecord() {
  const res = await fetch(`${API_BASE}/record`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch record");
  return res.json();
}

export async function fetchBacktest(sport: string = "mlb") {
  const res = await fetch(`${API_BASE}/backtest/${sport}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to fetch backtest");
  return res.json();
}

export async function fetchPaperTrade() {
  const res = await fetch(`${API_BASE}/paper-trade/summary`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to fetch paper trade data");
  return res.json();
}

export async function fetchPaperTradeToday() {
  const res = await fetch(`${API_BASE}/paper-trade/today`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to fetch today's picks");
  return res.json();
}

export async function calculateSizing(
  modelProb: number,
  americanOdds: number,
  bankroll: number,
  kellyFraction: number = 0.5,
) {
  const res = await fetch(`${API_BASE}/sizing`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model_prob: modelProb,
      american_odds: americanOdds,
      bankroll,
      kelly_fraction: kellyFraction,
    }),
  });
  if (!res.ok) throw new Error("Failed to calculate sizing");
  return res.json();
}
