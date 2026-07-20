#!/usr/bin/env python3
"""
Did the maker orders actually fill, and were the fills poisoned?

The scanner logs polymarket_ev picks priced as a RESTING order inside the bid,
which pays no fee and is +EV on paper. That price is only real if the order
fills — and resting orders fill preferentially when the person crossing into
you knows something you don't. That is adverse selection, and it is the whole
reason a maker edge can be positive on a spreadsheet and negative in an
account. This script measures both from the price track.

Method, per logged pick:
  1. Replay the token's price history from when the pick was recorded up to
     game start.
  2. FILLED if the price ever traded at or below the posted limit — someone
     sold into the order.
  3. For filled picks, compare the fair at entry against the price just before
     kickoff (the market's own final say). If fills systematically precede the
     price moving AWAY from us, the fill was information, not a gift.

The honest caveat, restated because it decides how much this is worth: the
history is the market's price track, not our queue position. "Price touched
the limit" is an upper bound on filling — a real order sits behind the size
already resting there. So a poor fill rate here is conclusive, while a good
one is optimistic.

Usage:
  python3 scripts/polymarket_fills.py                 # all logged maker picks
  python3 scripts/polymarket_fills.py --since 2026-07-20
  python3 scripts/polymarket_fills.py --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.polymarket import fetch_price_history   # noqa: E402

PICKS_FILE = Path("data/pnl/picks.json")
OUT_FILE = Path("data/clv/polymarket_fills.json")


def _load_picks() -> list[dict]:
    if not PICKS_FILE.exists():
        return []
    raw = json.loads(PICKS_FILE.read_text())
    return raw.get("picks", raw) if isinstance(raw, dict) else raw


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


def evaluate(pick: dict, history: list[dict]) -> dict | None:
    """Fill outcome for one pick. None when it can't be judged."""
    limit = pick.get("poly_limit")
    posted = _epoch(pick.get("recorded_at"))
    if limit is None or posted is None or not history:
        return None
    start = _epoch(pick.get("poly_game_start"))

    # Only the window the order was actually live: posted → kickoff.
    window = [h for h in history
              if h["t"] >= posted and (start is None or h["t"] <= start)]
    if not window:
        return None

    lows = [h["p"] for h in window]
    filled = min(lows) <= float(limit) + 1e-9
    fill_t = next((h["t"] for h in window if h["p"] <= float(limit) + 1e-9), None)

    fair = pick.get("model_prob")
    last = window[-1]["p"]          # market's final word before kickoff
    # Positive = the market moved TOWARD our side after we filled (we were
    # right); negative = it moved away (we were picked off).
    drift = (last - float(limit)) if filled else None

    return {
        "pick_id": pick.get("pick_id"),
        "team": pick.get("team"),
        "sport": pick.get("sport"),
        "date": pick.get("date"),
        "limit": round(float(limit), 4),
        "fair_at_entry": fair,
        "claimed_ev_pct": pick.get("edge_pct"),
        "filled": filled,
        "minutes_to_fill": (round((fill_t - posted) / 60.0, 1)
                            if fill_t is not None else None),
        "price_at_kickoff": round(last, 4),
        "post_fill_drift": round(drift, 4) if drift is not None else None,
        "n_ticks": len(window),
    }


def summarize(rows: list[dict]) -> dict:
    filled = [r for r in rows if r["filled"]]
    unfilled = [r for r in rows if not r["filled"]]
    drifts = [r["post_fill_drift"] for r in filled if r["post_fill_drift"] is not None]

    def _mean_ev(rs):
        evs = [r["claimed_ev_pct"] for r in rs if r.get("claimed_ev_pct") is not None]
        return round(statistics.mean(evs), 2) if evs else None

    return {
        "n": len(rows),
        "n_filled": len(filled),
        "fill_rate_pct": round(100 * len(filled) / len(rows), 1) if rows else None,
        "claimed_ev_filled": _mean_ev(filled),
        "claimed_ev_unfilled": _mean_ev(unfilled),
        "mean_post_fill_drift": round(statistics.mean(drifts), 4) if drifts else None,
        "median_minutes_to_fill": (
            round(statistics.median([r["minutes_to_fill"] for r in filled
                                     if r["minutes_to_fill"] is not None]), 1)
            if any(r["minutes_to_fill"] is not None for r in filled) else None),
    }


def run(since: str | None = None, as_json: bool = False) -> dict:
    picks = [p for p in _load_picks()
             if p.get("strategy") == "polymarket_ev"
             and p.get("poly_entry_mode") == "make"
             and p.get("poly_token_id")
             and (since is None or str(p.get("date", "")) >= since)]
    if not picks:
        print("  No maker-mode polymarket_ev picks logged yet — "
              "run the scanner without --dry-run first.")
        return {}

    rows = []
    for p in picks:
        hist = fetch_price_history(p["poly_token_id"])
        row = evaluate(p, hist)
        if row:
            rows.append(row)

    if not rows:
        print(f"  {len(picks)} pick(s) found but none had usable price history yet.")
        return {}

    summary = summarize(rows)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "summary": summary, "rows": rows}

    if as_json:
        print(json.dumps(out, indent=2))
        return out

    print(f"\n  POLYMARKET MAKER FILLS — {summary['n']} pick(s)")
    print("  " + "─" * 74)
    print(f"  Fill rate            : {summary['fill_rate_pct']}%  "
          f"({summary['n_filled']}/{summary['n']})")
    if summary["median_minutes_to_fill"] is not None:
        print(f"  Median time to fill  : {summary['median_minutes_to_fill']} min")
    print(f"  Claimed EV, filled   : {summary['claimed_ev_filled']}%")
    print(f"  Claimed EV, unfilled : {summary['claimed_ev_unfilled']}%")
    drift = summary["mean_post_fill_drift"]
    if drift is not None:
        print(f"  Mean post-fill drift : {drift:+.4f} "
              f"({'toward us' if drift > 0 else 'AWAY from us'})")
    print("  " + "─" * 74)

    # The read, stated plainly so a bad result can't be squinted past.
    if summary["n"] < 30:
        print(f"  n={summary['n']} — too few to conclude anything. Keep logging.")
    elif drift is not None and drift < 0:
        print("  ADVERSE SELECTION: filled orders were followed by the price")
        print("  moving away. The maker edge is being paid for with information.")
    elif (summary["claimed_ev_filled"] is not None
          and summary["claimed_ev_unfilled"] is not None
          and summary["claimed_ev_filled"] < summary["claimed_ev_unfilled"]):
        print("  WARNING: the juiciest-looking edges are the ones NOT filling.")
        print("  Paper EV is concentrated in orders that never trade.")
    else:
        print("  No adverse selection detected yet — fills are not systematically")
        print("  worse than misses. Necessary but not sufficient; CLV still rules.")
    print("  Reminder: history is the price track, not queue position, so this")
    print("  fill rate is an UPPER bound. Real fills sit behind resting size.")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2))
    print(f"  wrote {OUT_FILE}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", help="only picks on/after this date (YYYY-MM-DD)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()
    run(since=a.since, as_json=a.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
