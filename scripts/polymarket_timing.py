#!/usr/bin/env python3
"""
When should the scanner actually look? Measured, not guessed.

The cron currently fires every 6h, which was a shrug rather than a finding.
This answers the question with data: for games that have already been played,
replay each market's price track and ask how much the price still moved AFTER
each lead time.

The metric is remaining movement. If the price 12h before kickoff is already
within a cent of its final pre-game price, nothing is discovered in those 12
hours and scanning then is as good as scanning at the buzzer. If most of the
movement lands in the final 2 hours, an early scan is looking at a stale
picture and a late scan is where the mispricings are.

Two readings come out of it:
  - MOVE REMAINING (mean |p(T-N) - p(close)|): how much opportunity is still
    on the table at lead N. Bigger = more room for Polymarket to disagree with
    the sharp price.
  - DRIFT: the signed version. A systematic direction means the market is
    predictably wrong early in one direction, which is tradeable on its own.

Polymarket's own final pre-kickoff price is the reference, not Pinnacle. We
have a full price track per token and only one Pinnacle snapshot per pick, so
this measures Polymarket's own price discovery — which is exactly what
decides whether an early entry gets a better number than a late one.

Usage:
  python3 scripts/polymarket_timing.py
  python3 scripts/polymarket_timing.py --since 2026-07-01 --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.polymarket import _get, fetch_price_history   # noqa: E402

GAMMA_BASE = "https://gamma-api.polymarket.com"
OUT_FILE = Path("data/clv/polymarket_timing.json")

# Lead times to score, in hours before kickoff.
LEADS = (48, 24, 12, 8, 6, 4, 3, 2, 1, 0.5)

TAGS = ("mlb", "wnba", "mls", "k-league", "brazil-serie-a", "nba", "nhl", "ufc")


def _epoch(ts) -> int | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00").replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


def fetch_played_markets(tag: str, since: str, limit: int = 200) -> list[dict]:
    """Closed moneyline markets whose game has already been played."""
    try:
        data = _get(f"{GAMMA_BASE}/events",
                    params={"tag_slug": tag, "closed": "true",
                            "end_date_min": f"{since}T00:00:00Z", "limit": limit})
    except Exception:
        return []
    out = []
    for e in data if isinstance(data, list) else []:
        for m in (e.get("markets") or []):
            if (m.get("sportsMarketType") or "") != "moneyline":
                continue
            gs = m.get("gameStartTime")
            if not gs or str(gs) < since:
                continue
            toks = m.get("clobTokenIds")
            if isinstance(toks, str):
                try:
                    toks = json.loads(toks)
                except ValueError:
                    toks = None
            if not toks:
                continue
            out.append({"question": m.get("question"), "game_start": gs,
                        "token": toks[0]})
    return out


def _price_at(hist: list[dict], t: int) -> float | None:
    """Last observed price at or before t (a resting order sees the last trade)."""
    best = None
    for h in hist:
        if h["t"] <= t:
            best = h["p"]
        else:
            break
    return best


def analyse(markets: list[dict], leads=LEADS) -> dict:
    buckets: dict[float, list[float]] = {l: [] for l in leads}
    drifts: dict[float, list[float]] = {l: [] for l in leads}
    n_used = 0

    for m in markets:
        start = _epoch(m["game_start"])
        if start is None:
            continue
        hist = sorted(fetch_price_history(m["token"]), key=lambda x: x["t"])
        if not hist:
            continue
        close = _price_at(hist, start)
        if close is None:
            continue
        used = False
        for lead in leads:
            p = _price_at(hist, start - int(lead * 3600))
            if p is None:
                continue
            # Ignore already-resolved tracks pinned at 0/1.
            if p in (0.0, 1.0) and close in (0.0, 1.0):
                continue
            buckets[lead].append(abs(close - p))
            drifts[lead].append(close - p)
            used = True
        if used:
            n_used += 1

    rows = []
    for lead in leads:
        vals, dr = buckets[lead], drifts[lead]
        if not vals:
            continue
        rows.append({
            "lead_hours": lead,
            "n": len(vals),
            "move_remaining": round(statistics.mean(vals), 4),
            "drift": round(statistics.mean(dr), 4),
            "pct_moving_over_2c": round(100 * sum(1 for v in vals if v > 0.02) / len(vals), 1),
        })
    return {"n_markets": n_used, "rows": rows}


def run(since: str | None = None, as_json: bool = False) -> dict:
    since = since or (datetime.now(timezone.utc) - timedelta(days=21)).strftime("%Y-%m-%d")
    markets: list[dict] = []
    for tag in TAGS:
        got = fetch_played_markets(tag, since)
        if got:
            print(f"  [timing] {tag}: {len(got)} played market(s)")
        markets.extend(got)
    if not markets:
        print("  No played markets found — widen --since.")
        return {}

    out = analyse(markets)
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    out["since"] = since

    if as_json:
        print(json.dumps(out, indent=2))
        return out

    print(f"\n  POLYMARKET PRICE DISCOVERY — {out['n_markets']} played markets "
          f"since {since}")
    print("  " + "─" * 74)
    print(f"  {'lead':>7}  {'n':>5}  {'move left':>10}  {'drift':>8}  {'>2c moves':>10}")
    for r in out["rows"]:
        print(f"  {r['lead_hours']:>6}h  {r['n']:>5}  {r['move_remaining']:>10.4f}  "
              f"{r['drift']:>+8.4f}  {r['pct_moving_over_2c']:>9.1f}%")
    print("  " + "─" * 74)
    print("  move left = mean |price(T-lead) - final pre-game price|. It is the")
    print("  opportunity still on the table at that lead: the room Polymarket")
    print("  has left to disagree with the sharp number. Falling toward zero")
    print("  means price discovery is already done and scanning later adds")
    print("  nothing; staying high near kickoff means the late scans matter.")

    rows = out["rows"]
    if rows:
        best = max(rows, key=lambda r: r["move_remaining"])
        late = min(rows, key=lambda r: r["lead_hours"])
        print(f"\n  Most room to disagree: {best['lead_hours']}h out "
              f"({best['move_remaining']:.4f}).")
        print(f"  Still unsettled at {late['lead_hours']}h out: "
              f"{late['move_remaining']:.4f}.")
        drift = max(rows, key=lambda r: abs(r["drift"]))
        if abs(drift["drift"]) > 0.005:
            print(f"  NOTE: systematic drift at {drift['lead_hours']}h "
                  f"({drift['drift']:+.4f}) — prices move predictably in one")
            print("  direction from there, which is tradeable on its own.")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2))
    print(f"  wrote {OUT_FILE}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", help="only games on/after this date (YYYY-MM-DD)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()
    run(since=a.since, as_json=a.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
