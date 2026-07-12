#!/usr/bin/env python3
"""
Backfill vig-consistent CLV onto historical snapshots — no API calls.

The legacy clv_pct mixes a DEVIGGED close with a VIGGED entry, deflating every
price-CLV by the entry vig share (~1.5-2.5%). True no-vig CLV (fair close vs
fair entry) needs the entry board, which wasn't archived historically — but the
raw-vs-raw comparison (raw close implied − raw entry implied, both best-price,
so the vig approximately cancels) is computable from fields every scored
snapshot already stores:

  clv_raw_pct            = (implied(closing_odds) − opening_implied_prob) * 100
  clv_raw_sharp_pct      = same vs Pinnacle's closing price
  price_clv_raw_pct      = same for line markets when close line == open line

Idempotent: recomputes-in-place, safe to run any time.

Usage:
    python3 scripts/backfill_raw_clv.py            # dry-run summary
    python3 scripts/backfill_raw_clv.py --write    # persist
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analytics.clv_tracker import _odds_to_implied  # noqa: E402

SNAPSHOTS_FILE = ROOT / "data" / "clv" / "snapshots.json"


def backfill(write: bool) -> dict:
    snaps = json.loads(SNAPSHOTS_FILE.read_text())
    stats = {"price_raw": 0, "price_raw_sharp": 0, "line_raw": 0, "total": len(snaps)}

    for s in snaps:
        if not isinstance(s, dict):
            continue
        entry_imp = s.get("opening_implied_prob")
        if entry_imp is None:
            continue

        # ── Price markets (moneyline / NRFI / scorer / outright) ─────────────
        if s.get("clv_pct") is not None and s.get("closing_odds") is not None:
            s["clv_raw_pct"] = round(
                (_odds_to_implied(s["closing_odds"]) - entry_imp) * 100, 3)
            stats["price_raw"] += 1
            if s.get("closing_odds_sharp") is not None:
                s["clv_raw_sharp_pct"] = round(
                    (_odds_to_implied(s["closing_odds_sharp"]) - entry_imp) * 100, 3)
                stats["price_raw_sharp"] += 1

        # ── Line markets: raw price CLV only at the matched line ─────────────
        elif (s.get("line_clv") is not None
              and s.get("price_clv_pct") is not None
              and s.get("closing_odds") is not None):
            s["price_clv_raw_pct"] = round(
                (_odds_to_implied(s["closing_odds"]) - entry_imp) * 100, 3)
            stats["line_raw"] += 1

    if write:
        SNAPSHOTS_FILE.write_text(json.dumps(snaps, indent=2))
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="Persist the backfill")
    args = ap.parse_args()

    stats = backfill(write=args.write)
    mode = "WROTE" if args.write else "DRY-RUN (pass --write to persist)"
    print(f"  [backfill_raw_clv] {mode}")
    print(f"    snapshots scanned:        {stats['total']}")
    print(f"    price clv_raw_pct:        {stats['price_raw']}")
    print(f"    price clv_raw_sharp_pct:  {stats['price_raw_sharp']}")
    print(f"    line  price_clv_raw_pct:  {stats['line_raw']}")


if __name__ == "__main__":
    main()
