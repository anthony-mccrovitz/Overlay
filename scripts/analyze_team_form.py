#!/usr/bin/env python3
"""Phase 2 → Phase 3 bridge: analyze team_form vs outcomes.

Slices settled MLB picks by whether teams were HOT, COLD, or NEUTRAL at
bet time (based on 7d RS/RA vs season averages), then reports W-L/ROI
for each slice. The goal is to surface — with real data — whether team
form matters before we touch the model.

Definitions (configurable):
  HOT offense  : 7d RS/g >= 1.10 × season RS/g
  COLD offense : 7d RS/g <= 0.90 × season RS/g

For totals picks, the relevant signal is matchup form (both teams):
  - HOT both     → both offenses hot     → expect OVER bias
  - COLD both    → both offenses cold    → expect UNDER bias
  - MIXED        → one hot, one cold
  - NEUTRAL      → neither team flagged

Usage:
  python3 scripts/analyze_team_form.py
  python3 scripts/analyze_team_form.py --market total --min-n 10
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"

HOT_THRESHOLD  = 1.10
COLD_THRESHOLD = 0.90


def _form_class(form: dict | None) -> str:
    """Return 'hot', 'cold', or 'neutral' based on 7d vs season RS/g."""
    if not form or "form_7d" not in form or not form["form_7d"]:
        return "unknown"
    f7 = form["form_7d"]
    season = form.get("season_rs_per_g")
    if not season or season <= 0 or not f7.get("rs_per_game"):
        return "unknown"
    ratio = f7["rs_per_game"] / season
    if ratio >= HOT_THRESHOLD:
        return "hot"
    if ratio <= COLD_THRESHOLD:
        return "cold"
    return "neutral"


def _matchup_class(team_form: dict | None) -> str:
    """Classify a (home, away) form pair into HOT_BOTH / COLD_BOTH / MIXED / NEUTRAL."""
    if not team_form:
        return "unknown"
    home_c = _form_class(team_form.get("home"))
    away_c = _form_class(team_form.get("away"))
    if home_c == "unknown" or away_c == "unknown":
        return "unknown"
    if home_c == "hot" and away_c == "hot":
        return "hot_both"
    if home_c == "cold" and away_c == "cold":
        return "cold_both"
    if "hot" in (home_c, away_c) and "cold" in (home_c, away_c):
        return "mixed"
    if "hot" in (home_c, away_c):
        return "one_hot"
    if "cold" in (home_c, away_c):
        return "one_cold"
    return "neutral"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="total",
                    help="Market to slice (default: total)")
    ap.add_argument("--min-n", type=int, default=10,
                    help="Only show buckets with at least N picks (default 10)")
    args = ap.parse_args()

    data = json.loads(PICKS_FILE.read_text())
    picks = data.get("picks", data) if isinstance(data, dict) else data

    subset = [
        p for p in picks
        if p.get("sport") == "mlb"
        and (p.get("market") or "").lower() == args.market
        and p.get("result") in ("win", "loss", "push")
        and p.get("team_form")
    ]

    if not subset:
        print(f"No settled MLB {args.market} picks with team_form yet. "
              f"Run scripts/backfill_team_form.py first or wait for more data.")
        return 0

    print(f"Analyzing {len(subset)} settled MLB {args.market} picks with team_form")
    print(f"HOT  = 7d RS/g >= {HOT_THRESHOLD}× season")
    print(f"COLD = 7d RS/g <= {COLD_THRESHOLD}× season")
    print()

    # ── Slice by matchup form class ──────────────────────────────────────────
    buckets: dict[str, list[dict]] = defaultdict(list)
    direction_buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for p in subset:
        cls = _matchup_class(p["team_form"])
        buckets[cls].append(p)
        direction = (p.get("direction") or "?").upper()
        direction_buckets[(cls, direction)].append(p)

    def _summary(rows: list[dict]) -> str:
        w = sum(1 for r in rows if r["result"] == "win")
        l = sum(1 for r in rows if r["result"] == "loss")
        pnl = sum(r.get("profit") or 0 for r in rows)
        if w + l == 0:
            return f"{len(rows)} picks (no wins/losses graded)"
        wr = w / (w + l) * 100
        roi = pnl / (w + l) * 100
        return f"{w}W-{l}L  WR {wr:.1f}%  P/L {pnl:+.2f}u  ROI {roi:+.1f}%  n={len(rows)}"

    print("── BY MATCHUP FORM CLASS ──")
    for cls in ["hot_both", "one_hot", "neutral", "mixed", "one_cold", "cold_both", "unknown"]:
        rows = buckets.get(cls, [])
        if len(rows) < args.min_n:
            continue
        print(f"  {cls:<12}  {_summary(rows)}")

    print()
    print("── BY DIRECTION × FORM (does OVER outperform on hot matchups?) ──")
    for cls in ["hot_both", "cold_both", "mixed", "neutral"]:
        for direction in ["OVER", "UNDER"]:
            rows = direction_buckets.get((cls, direction), [])
            if len(rows) < args.min_n:
                continue
            print(f"  {cls:<10} × {direction:<6}  {_summary(rows)}")

    print()
    print("Note: small sample sizes are noisy. Target N ≥ 30 per bucket before "
          "drawing strong conclusions. Phase 3 model decision should wait until "
          "key buckets reach that threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
