#!/usr/bin/env python3
"""What is half a point worth? Measured from our own archives, per sport×market.

WHY: CLV on a line market is stored in POINTS (`mlb/total` reports "+0.19pt").
A point is not a unit of value. It cannot be compared across sports — half a run
on an MLB total is worth far more than half a point on an NBA total — it cannot
be compared with a moneyline CLV in %, and it cannot be turned into expected
profit. So the one live lane's headline number is, as stored, unconvertible.

HOW: identify the slope d(fair probability)/d(line) from CROSS-BOOK disagreement
within the same event at the same moment. When FanDuel posts 7.5 and DraftKings
posts 8, both at the same instant on the same game, the gap between their
devigged Over probabilities is caused by the half-point and nothing else — no
news, no steam, no time passing. Measured on real archives, 60% of MLB total
events and 97% of pitcher-strikeout events carry at least two distinct lines, so
there is ample identifying variation.

Estimator: within-event demeaned OLS (an event fixed effect). Demeaning removes
every event-level difference — the teams, the park, the weather, the starters —
leaving only the within-event, across-book relationship between line and price.
Pooling raw levels instead would mostly measure "high-total games have high
totals", which is true and useless.

Output: data/clv/line_value.json, consumed by the CLV tracker to convert line
movement into probability so line and price movement can finally be added up.

Usage:  python3 scripts/calibrate_line_value.py [--days 60] [--min-events 20]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analytics.devig import devig  # noqa: E402

OUT_PATH = ROOT / "data" / "clv" / "line_value.json"

# Minimum share of within-event price variation the line must explain before we
# trust the slope as a conversion factor. Below this the "relationship" is noise.
MIN_R2 = 0.25

# Odds API market key → the internal market name used across the registry.
MARKET_ALIASES = {
    "totals": "total",
    "totals_1st_5_innings": "f5_total",
    "totals_1st_1_innings": "nrfi",
    "spreads": "spread",
}


def _internal(market: str) -> str:
    return MARKET_ALIASES.get(market, market)


def _sport_of(path: Path) -> str:
    """mlb_2026-07-29.json → mlb ; tennis_atp_x_2026-07-29.json → tennis_atp_x."""
    return path.stem[:-11] if len(path.stem) > 11 else path.stem


def _observations(rec: dict, market: str) -> list[tuple[float, float]]:
    """(line, fair_prob) for one event, one per book that prices a full pair."""
    by_book: dict[str, dict] = defaultdict(dict)
    for r in rec.get("all_odds") or []:
        if r.get("Market") != market:
            continue
        line = r.get("Line") if r.get("Line") is not None else r.get("Point")
        odds = r.get("Odds")
        if line is None or odds is None:
            continue
        sel = str(r.get("Selection") or r.get("Name") or "").strip()
        if not sel:
            continue
        by_book[str(r.get("Sportsbook") or "")][sel] = (float(line), float(odds))

    out: list[tuple[float, float]] = []
    for _book, sides in by_book.items():
        if len(sides) != 2:
            continue                      # need a complete market to devig
        keys = sorted(sides)
        lo = {k.lower() for k in keys}
        if lo == {"over", "under"}:
            first = next(k for k in keys if k.lower() == "over")
        else:
            # Spreads: selections are team names. Canonicalise on the
            # alphabetically-first team so every book in an event contributes the
            # SAME side — mixing sides would flip the sign of half the rows and
            # regress the slope toward zero.
            first = keys[0]
        second = next(k for k in keys if k != first)
        line, odds_first = sides[first]
        _line2, odds_second = sides[second]
        fair = devig([odds_first, odds_second], market=_internal(market))
        if fair is None:
            continue
        out.append((line, fair[0]))
    return out


def calibrate(days: int, min_events: int) -> dict:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    # lane -> [Σxy, Σxx, Σyy, n_obs, n_events]
    acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0, 0])

    for f in sorted(glob.glob(str(ROOT / "data" / "clv" / "closing" / "*.json"))):
        p = Path(f)
        if p.stem[-10:] < cutoff:
            continue
        sport = _sport_of(p)
        try:
            recs = json.loads(p.read_text().replace("NaN", "null"))
        except (json.JSONDecodeError, ValueError, OSError):
            continue
        if not isinstance(recs, list):
            continue
        for rec in recs:
            markets = {r.get("Market") for r in (rec.get("all_odds") or [])}
            for market in markets:
                if not market:
                    continue
                obs = _observations(rec, market)
                if len(obs) < 2:
                    continue
                lines = {o[0] for o in obs}
                if len(lines) < 2:
                    continue          # no within-event variation → no information
                mx = sum(o[0] for o in obs) / len(obs)
                my = sum(o[1] for o in obs) / len(obs)
                cell = acc[f"{sport}::{_internal(market)}"]
                for x, y in obs:
                    dx, dy = x - mx, y - my
                    cell[0] += dx * dy
                    cell[1] += dx * dx
                    cell[2] += dy * dy
                cell[3] += len(obs)
                cell[4] += 1

    lanes: dict[str, dict] = {}
    for lane, (sxy, sxx, syy, n_obs, n_ev) in sorted(acc.items()):
        if n_ev < min_events or sxx <= 0:
            continue
        slope = sxy / sxx
        r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
        # A slope with no explanatory power is not a conversion factor. Some
        # lanes genuinely lack one: mlb/pitcher_outs came back at r²=0.01, and
        # the WNBA player props at ~0.00, because books there disagree on the
        # line without disagreeing on the price — the number moves but the
        # market's opinion doesn't. Converting a line CLV through a slope like
        # that would manufacture precision from noise, so those lanes are
        # recorded (for visibility) but flagged unusable, and the tracker leaves
        # their CLV in raw points rather than inventing a probability.
        lanes[lane] = {
            "prob_per_point": round(slope, 6),
            "prob_per_half_point": round(abs(slope) * 0.5, 6),
            "r2": round(r2, 4),
            "n_events": n_ev,
            "n_obs": n_obs,
            "usable": bool(r2 >= MIN_R2 and n_ev >= min_events),
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "method": "within-event demeaned OLS on cross-book line disagreement",
        "lanes": lanes,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--min-events", type=int, dest="min_events", default=20)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    blob = calibrate(args.days, args.min_events)
    lanes = blob["lanes"]
    if not lanes:
        print("  No lane had enough within-event line variation to calibrate.")
        return 1

    print(f"\n  LINE VALUE — d(fair probability) per point of line")
    print(f"  {blob['method']}, last {args.days}d")
    print(f"  {'LANE':34}{'prob/pt':>10}{'per ½pt':>10}{'r²':>8}{'events':>8}{'obs':>7}")
    print(f"  {'-'*77}")
    for lane, v in sorted(lanes.items(), key=lambda kv: -kv[1]["n_events"]):
        mark = "" if v["usable"] else "   ✗ unusable (r² too low)"
        print(f"  {lane:34}{v['prob_per_point']:>+10.4f}"
              f"{v['prob_per_half_point']:>10.4f}{v['r2']:>8.2f}"
              f"{v['n_events']:>8}{v['n_obs']:>7}{mark}")

    if args.dry_run:
        print("\n  --dry-run: not written.")
        return 0
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(blob, indent=2))
    print(f"\n  → {OUT_PATH.relative_to(ROOT)}  ({len(lanes)} lane(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
