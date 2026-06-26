"""
Walk-forward calibration check of the Asian-handicap cover model, by line size.

The -0.5 cover exactly equals the calibrated win prob (well-anchored), but WIDE
handicaps (±1.5, ±2, ±2.25) depend on the blowout TAIL of the score grid, which
a 2-parameter Poisson-Elo model estimates poorly — manufacturing phantom edges
(e.g. Curaçao +2.25 "model 85% vs market 52%"). This bins out-of-sample cover
calibration by |line| so we set an honest max bettable handicap from data, not
by guessing.

Same walk-forward protocol as validate_soccer.py.

Run:
    python3 scripts/calibrate_soccer_handicap.py
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.soccer_data import load_international_results
from src.models.soccer_model_v2 import SoccerModelV2
from scripts.validate_soccer import _tournament_instances

SoccerModelV2._save = lambda self: None  # type: ignore[assignment]

# Favorite-side handicap lines to probe (home perspective; the model is
# symmetric so this covers dog lines too).
LINES = [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]


def _cover_actual(hs: int, as_: int, line: float) -> float | None:
    """Did home cover `line`? Quarter-lines split; return None on full push."""
    adj = (hs - as_) + line
    if adj > 1e-9:
        return 1.0
    if adj < -1e-9:
        return 0.0
    return None  # exact push at integer line — exclude


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-year", type=int, default=2006)
    args = ap.parse_args()

    print("─" * 64)
    print("SOCCER ASIAN HANDICAP — cover calibration by |line|")
    print("─" * 64)

    all_matches = load_international_results(min_year=args.min_year, competitive_only=True)
    instances = _tournament_instances(all_matches)

    # bucket by |line| → list of (pred_cover, actual_cover)
    buckets: dict[float, list[tuple[float, float]]] = defaultdict(list)
    graded = 0
    for label, start, ms in instances:
        train = [m for m in all_matches if m["date"] < start]
        if len(train) < 500:
            continue
        model = SoccerModelV2()
        model.fit(_matches=train, verbose=False)
        graded += 1
        for m in ms:
            h, a = m["home_team"], m["away_team"]
            if model.get_elo(h) == model.DEFAULT_ELO or model.get_elo(a) == model.DEFAULT_ELO:
                continue
            hs, as_ = m["home_score"], m["away_score"]
            for line in LINES:
                actual = _cover_actual(hs, as_, line)
                if actual is None:
                    continue
                pred = model.handicap_cover_prob(h, a, line, side="home",
                                                 neutral=m.get("neutral", True))
                buckets[abs(line)].append((pred, actual))

    print(f"Graded {graded} tournaments.\n")
    print(f"  {'|line|':>6} {'n':>5} {'pred':>6} {'actual':>7} {'gap':>6} {'Brier':>7}")
    print("  " + "-" * 44)
    for mag in sorted(buckets):
        pairs = buckets[mag]
        n = len(pairs)
        mp = sum(p for p, _ in pairs) / n
        ma = sum(a for _, a in pairs) / n
        brier = sum((p - a) ** 2 for p, a in pairs) / n
        flag = "  ← drifts" if abs(mp - ma) > 0.05 else ""
        print(f"  {mag:>6.1f} {n:>5} {mp:>6.2f} {ma:>7.2f} {mp-ma:>+6.2f} {brier:>7.4f}{flag}")
    print("  " + "-" * 44)
    print("\n  Reliable where |pred − actual| ≤ 0.05. Set the max bettable")
    print("  handicap to the largest |line| that stays calibrated.")
    print("─" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
