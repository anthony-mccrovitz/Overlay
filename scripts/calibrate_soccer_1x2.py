"""
Walk-forward calibration of the soccer 1X2 temperature (CALIBRATION_T).

The favorite-pick calibration on 852 tournament matches shows the model is
systematically UNDER-confident on the favorite (actual hit-rate > predicted in
every probability bin). The deployed CALIBRATION_T=1.25 *softens* — the wrong
direction. This grid-searches the net temperature applied to the raw (h,d,a)
probabilities to minimise pooled out-of-sample 1X2 log loss (the proper scoring
rule for probability sharpness), reporting Brier alongside.

T < 1 sharpens (more confident), T > 1 softens. Same walk-forward protocol as
validate_soccer.py (train strictly before each tournament; no live Elo seed).

Run:
    python3 scripts/calibrate_soccer_1x2.py
    python3 scripts/calibrate_soccer_1x2.py --json data/models/soccer_1x2_calibration.json
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.soccer_data import load_international_results
from src.models.soccer_model_v2 import SoccerModelV2
from scripts.validate_soccer import _tournament_instances

SoccerModelV2._save = lambda self: None  # type: ignore[assignment]

# Net temperature grid. < 1 sharpens, > 1 softens.
T_GRID = [round(0.50 + 0.05 * i, 2) for i in range(0, 31)]  # 0.50 … 2.00


def _temp(prob3, T):
    logits = [math.log(max(p, 1e-9)) / T for p in prob3]
    mx = max(logits)
    exps = [math.exp(x - mx) for x in logits]
    s = sum(exps)
    return tuple(e / s for e in exps)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-year", type=int, default=2006)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    print("─" * 70)
    print("SOCCER 1X2 — walk-forward CALIBRATION_T (temperature) search")
    print("─" * 70)

    all_matches = load_international_results(min_year=args.min_year, competitive_only=True)
    instances = _tournament_instances(all_matches)
    print(f"Loaded {len(all_matches):,} matches; {len(instances)} tournament instances.\n")

    # Collect RAW (temperature-off) (h,d,a) preds + actuals across tournaments.
    raw_preds: list[tuple] = []
    actuals: list[tuple] = []
    graded = 0
    for label, start, ms in instances:
        train = [m for m in all_matches if m["date"] < start]
        if len(train) < 500:
            continue
        model = SoccerModelV2()
        model.fit(_matches=train, verbose=False)
        model.temperature = 1.0  # RAW — we search the temperature ourselves
        graded += 1
        for m in ms:
            h, a = m["home_team"], m["away_team"]
            if model.get_elo(h) == model.DEFAULT_ELO or model.get_elo(a) == model.DEFAULT_ELO:
                continue
            pr = model.matchup(h, a, neutral=m.get("neutral", True))
            raw_preds.append((pr["home_win"], pr["draw"], pr["away_win"]))
            hs, as_ = m["home_score"], m["away_score"]
            actuals.append((1, 0, 0) if hs > as_ else ((0, 1, 0) if hs == as_ else (0, 0, 1)))

    n = len(raw_preds)
    print(f"Graded {graded} tournaments, {n} matches.\n")
    print(f"  {'net T':>6} {'LogLoss':>9} {'Brier':>9} {'note':>10}")
    print("  " + "-" * 40)

    results = []
    for T in T_GRID:
        scaled = [_temp(p, T) for p in raw_preds]
        ll = -sum(math.log(max(s[a.index(1)], 1e-9))
                  for s, a in zip(scaled, actuals)) / n
        brier = sum(
            (s[0]-a[0])**2 + (s[1]-a[1])**2 + (s[2]-a[2])**2
            for s, a in zip(scaled, actuals)
        ) / n / 2
        results.append({"T": T, "log_loss": ll, "brier": brier})

    best = min(results, key=lambda r: r["log_loss"])
    cur = min(results, key=lambda r: abs(r["T"] - 1.25))  # deployed value
    raw1 = min(results, key=lambda r: abs(r["T"] - 1.0))
    for r in results:
        note = ""
        if r["T"] == best["T"]:
            note = "← BEST"
        elif abs(r["T"] - 1.25) < 1e-9:
            note = "deployed"
        # Only print a readable subset around the action.
        if 0.70 <= r["T"] <= 1.30 or note:
            print(f"  {r['T']:>6.2f} {r['log_loss']:>9.4f} {r['brier']:>9.4f} {note:>10}")

    print("  " + "-" * 40)
    print(f"\n  Deployed (T=1.25): LogLoss {cur['log_loss']:.4f}  Brier {cur['brier']:.4f}")
    print(f"  Raw      (T=1.00): LogLoss {raw1['log_loss']:.4f}  Brier {raw1['brier']:.4f}")
    print(f"  BEST     (T={best['T']:.2f}): LogLoss {best['log_loss']:.4f}  Brier {best['brier']:.4f}")
    impr = (cur["brier"] - best["brier"]) / cur["brier"] * 100
    print(f"  → vs deployed: {impr:+.1f}% Brier; "
          f"{'SHARPEN' if best['T'] < 1 else 'SOFTEN'} (model was "
          f"{'under' if best['T'] < 1.25 else 'over'}-confident).")
    print(f"\n  Set SoccerModelV2.CALIBRATION_T = {best['T']:.2f}")
    print("─" * 70)

    if args.json:
        import json as _json
        from datetime import date as _date
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(_json.dumps({
            "generated": _date.today().isoformat(),
            "min_year": args.min_year,
            "n_tournaments": graded,
            "n_matches": n,
            "best_T": best["T"],
            "deployed_T": 1.25,
            "grid": [{k: round(v, 4) if isinstance(v, float) else v
                      for k, v in r.items()} for r in results],
        }, indent=2))
        print(f"  Wrote → {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
