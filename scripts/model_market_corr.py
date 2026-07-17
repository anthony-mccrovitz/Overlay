#!/usr/bin/env python3
"""
scripts/model_market_corr.py — how correlated is our model with the market?

Hubáček, Šourek & Železný (2019, Int'l J. Forecasting) found that a model which
is DECORRELATED from the bookmaker's line earns more than a more-accurate model
that merely tracks it — a model that only reproduces the market never finds a
bet. This is a sizing diagnostic, NOT a training change: it reports, per
sport×market, the correlation between our stored model_prob and the market's
implied probability, plus how far apart they sit on average. High correlation
(r → 1) with tiny mean gap means we're mostly echoing the line and a
decorrelation penalty could be worth building; a lower r means we already carry
independent signal.

Reads data/pnl/picks.json (excludes shadow strategy picks — those ARE the
market by construction). Read-only. Does not touch calibration.py /
calibration_gate.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategies.consensus import implied  # noqa: E402

PICKS_FILE = Path("data/pnl/picks.json")
MIN_N = 50


def _load_picks() -> list[dict]:
    try:
        raw = json.loads(PICKS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    picks = raw.get("picks", []) if isinstance(raw, dict) else raw
    return [p for p in picks if isinstance(p, dict)]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def compute(min_n: int = MIN_N) -> list[dict]:
    """Per sport×market: n, Pearson r(model_prob, implied), mean|model−implied|."""
    groups: dict[tuple, list[tuple[float, float]]] = {}
    for p in _load_picks():
        if p.get("strategy"):
            continue  # shadow strategies are the market — excluding by design
        mp = p.get("model_prob")
        odds = p.get("odds")
        if mp is None or odds is None:
            continue
        imp = implied(odds)
        try:
            mp = float(mp)
        except (TypeError, ValueError):
            continue
        if imp is None or not (0.0 < mp < 1.0):
            continue
        key = (str(p.get("sport") or "?"), str(p.get("market") or "?"))
        groups.setdefault(key, []).append((mp, imp))

    rows: list[dict] = []
    for (sport, market), pts in groups.items():
        if len(pts) < min_n:
            continue
        model = [m for m, _ in pts]
        mkt = [i for _, i in pts]
        r = _pearson(model, mkt)
        gap = sum(abs(m - i) for m, i in pts) / len(pts)
        rows.append({"sport": sport, "market": market, "n": len(pts),
                     "pearson_r": r, "mean_abs_gap": gap})
    rows.sort(key=lambda x: (x["pearson_r"] if x["pearson_r"] is not None else -2))
    return rows


def main() -> int:
    rows = compute()
    print("\n  MODEL ↔ MARKET CORRELATION  (Hubáček decorrelation sizing)")
    print(f"  per sport×market, n≥{MIN_N} · lower r / bigger gap = more independent signal")
    if not rows:
        print("    (no eligible picks)")
        return 0
    print(f"    {'sport':<26}{'market':<22}{'n':>6}{'r(model,mkt)':>15}{'mean|gap|':>12}")
    for e in rows:
        r = f"{e['pearson_r']:+.3f}" if e["pearson_r"] is not None else "—"
        print(f"    {e['sport']:<26}{e['market']:<22}{e['n']:>6}{r:>15}{e['mean_abs_gap']:>11.3f}")
    print("    → r≳0.95 with a tiny gap ⇒ we're echoing the line there; a "
          "decorrelation penalty (Hubáček) could add bet-worthy divergence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
