"""
Walk-forward calibration of the soccer totals model (TEMPO_SHRINK).

The rolling attack/defense terms (β, δ) are fit by MLE to in-sample recent-form
signal, but they over-swing the expected total out-of-sample — on one 2026 World
Cup slate exp_total ranged 1.76–3.39, manufacturing phantom ±30% totals edges.

This script grid-searches a single shrinkage factor s ∈ [0,1] applied to (β, δ)
at prediction time, and reports the s that minimises POOLED out-of-sample
O/U-2.5 Brier across every comparable tournament since --min-year. Same
walk-forward protocol as validate_soccer.py (train strictly before each
tournament; no live Elo seed; production pickle untouched).

Run:
    python3 scripts/calibrate_soccer_totals.py
    python3 scripts/calibrate_soccer_totals.py --min-year 2006 --json data/models/soccer_totals_calibration.json
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.soccer_data import load_international_results
from src.models.soccer_model_v2 import SoccerModelV2

# Reuse the exact tournament-selection logic from the validation harness.
from scripts.validate_soccer import TARGET_TOURNAMENTS, _tournament_instances

# Don't let a fitted backtest model stomp the deployed pickle.
SoccerModelV2._save = lambda self: None  # type: ignore[assignment]

# Shrinkage grid: 0.0 (pure Elo+μ baseline, no tempo) → 1.0 (raw MLE β,δ).
SHRINK_GRID = [round(0.1 * i, 1) for i in range(0, 11)]


def _ece(pairs, n_bins=10) -> float:
    """Expected calibration error: mean |pred − observed| weighted by bin count."""
    bins = defaultdict(lambda: [0.0, 0.0, 0])  # sum_pred, sum_obs, count
    for p, o in pairs:
        b = min(int(p * n_bins), n_bins - 1)
        bins[b][0] += p
        bins[b][1] += o
        bins[b][2] += 1
    n = sum(b[2] for b in bins.values())
    if n == 0:
        return float("nan")
    return sum(
        (b[2] / n) * abs(b[0] / b[2] - b[1] / b[2])
        for b in bins.values() if b[2]
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-year", type=int, default=2006)
    ap.add_argument("--json", default=None, help="Write per-shrink metrics here")
    args = ap.parse_args()

    print("─" * 70)
    print("SOCCER TOTALS — walk-forward TEMPO_SHRINK calibration")
    print("─" * 70)

    all_matches = load_international_results(min_year=args.min_year, competitive_only=True)
    instances = _tournament_instances(all_matches)
    print(f"Loaded {len(all_matches):,} matches; {len(instances)} tournament instances.\n")

    # For each shrink value, pooled (pred_over, actual_over) across all tournaments.
    pooled: dict[float, list[tuple[float, int]]] = {s: [] for s in SHRINK_GRID}
    exp_totals: dict[float, list[float]] = {s: [] for s in SHRINK_GRID}

    graded_tournaments = 0
    for label, start, ms in instances:
        train = [m for m in all_matches if m["date"] < start]
        if len(train) < 500:
            continue
        model = SoccerModelV2()
        model.fit(_matches=train, verbose=False)
        graded_tournaments += 1

        for m in ms:
            h, a = m["home_team"], m["away_team"]
            if model.get_elo(h) == model.DEFAULT_ELO or model.get_elo(a) == model.DEFAULT_ELO:
                continue
            actual_over = 1 if (m["home_score"] + m["away_score"]) > 2 else 0
            for s in SHRINK_GRID:
                model.tempo_shrink = s
                pr = model.matchup(h, a, neutral=m.get("neutral", True))
                pooled[s].append((pr["over_2_5"], actual_over))
                exp_totals[s].append(pr["exp_total"])

    if not graded_tournaments:
        print("No tournaments had enough training depth — nothing to calibrate.")
        return 1

    n = len(pooled[SHRINK_GRID[0]])
    base_rate = sum(o for _, o in pooled[1.0]) / n
    print(f"Graded {graded_tournaments} tournaments, {n} matches. "
          f"Actual over-2.5 rate: {base_rate*100:.1f}%\n")

    print(f"  {'shrink':>6} {'O/U Brier':>10} {'LogLoss':>9} {'ECE':>7} "
          f"{'exp_tot σ':>10} {'mean':>6}")
    print("  " + "-" * 56)

    results = []
    for s in SHRINK_GRID:
        pairs = pooled[s]
        brier = sum((p - o) ** 2 for p, o in pairs) / len(pairs)
        ll = -sum(
            math.log(max(p if o else 1 - p, 1e-9)) for p, o in pairs
        ) / len(pairs)
        ece = _ece(pairs)
        ets = exp_totals[s]
        mean_et = sum(ets) / len(ets)
        std_et = (sum((x - mean_et) ** 2 for x in ets) / len(ets)) ** 0.5
        results.append({
            "shrink": s, "brier": brier, "log_loss": ll, "ece": ece,
            "exp_total_std": std_et, "exp_total_mean": mean_et,
        })
        print(f"  {s:>6.1f} {brier:>10.4f} {ll:>9.4f} {ece:>7.4f} "
              f"{std_et:>10.3f} {mean_et:>6.2f}")

    best = min(results, key=lambda r: r["brier"])
    raw = next(r for r in results if r["shrink"] == 1.0)
    print("  " + "-" * 56)
    print(f"\n  Raw (s=1.0):   Brier {raw['brier']:.4f}  exp_total σ {raw['exp_total_std']:.3f}")
    print(f"  BEST (s={best['shrink']:.1f}):  Brier {best['brier']:.4f}  "
          f"exp_total σ {best['exp_total_std']:.3f}")
    impr = (raw["brier"] - best["brier"]) / raw["brier"] * 100
    print(f"  → {impr:+.1f}% O/U Brier improvement; tempo swing cut "
          f"{(1 - best['exp_total_std']/raw['exp_total_std'])*100:.0f}%.")
    print(f"\n  Set SoccerModelV2.TEMPO_SHRINK = {best['shrink']:.1f}")
    print("─" * 70)

    if args.json:
        import json as _json
        from datetime import date as _date
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(_json.dumps({
            "generated": _date.today().isoformat(),
            "min_year": args.min_year,
            "n_tournaments": graded_tournaments,
            "n_matches": n,
            "actual_over_rate": round(base_rate, 4),
            "best_shrink": best["shrink"],
            "grid": [{k: round(v, 4) if isinstance(v, float) else v
                      for k, v in r.items()} for r in results],
        }, indent=2))
        print(f"  Wrote → {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
