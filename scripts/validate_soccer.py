"""
Multi-tournament walk-forward validation for the soccer model.

Honest out-of-sample test: for each major international tournament since 2010,
train SoccerModelV2 on every competitive match that finished *before* the
tournament kicked off, then predict every match in that tournament. Aggregate
calibration + accuracy across all of them so we judge the model on ~300+
knockout-quality matches instead of a single 60-game World Cup.

Correctness guarantees:
  - Walk-forward: training set is strictly < tournament start date (no leakage).
  - No live eloratings.net seed: that would inject *today's* ratings into a
    2014 prediction. Backtest uses only causally-rolled Elo from training data.
  - Does NOT overwrite the production model pickle (._save is neutered here).

Run:
    python3 scripts/validate_soccer.py
    python3 scripts/validate_soccer.py --min-year 2006 --verbose
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.soccer_data import load_international_results
from src.models.soccer_model_v2 import SoccerModelV2

# Tournament-style finals most comparable to the World Cup (neutral-ish, mixed
# confederations, knockout). Names match the martj42 `tournament` field.
TARGET_TOURNAMENTS = {
    "FIFA World Cup",
    "UEFA Euro",
    "Copa América",
    "Copa America",
    "Africa Cup of Nations",
    "African Nations Cup",
    "AFC Asian Cup",
}

# Don't let a fitted backtest model stomp the deployed pickle.
SoccerModelV2._save = lambda self: None  # type: ignore[assignment]


def _metrics(preds_1x2, actuals_1x2, preds_ou, actuals_ou):
    """Return dict of headline metrics for a set of predictions."""
    n = len(preds_1x2)
    if n == 0:
        return None
    # Multi-class Brier, normalised to [0,1] (divide by 2). Naive uniform = 0.333.
    brier = sum(
        (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2 + (p[2] - a[2]) ** 2
        for p, a in zip(preds_1x2, actuals_1x2)
    ) / n / 2
    # Log loss on the true outcome. Naive uniform = 1.0986.
    ll = -sum(
        math.log(max(p[a.index(1)], 1e-9)) for p, a in zip(preds_1x2, actuals_1x2)
    ) / n
    # Modal-pick accuracy.
    correct = sum(
        1 for p, a in zip(preds_1x2, actuals_1x2)
        if p.index(max(p)) == a.index(1)
    )
    out = {
        "n": n,
        "brier_1x2": brier,
        "log_loss": ll,
        "acc": correct / n,
    }
    if preds_ou:
        out["brier_ou"] = sum((p - a) ** 2 for p, a in zip(preds_ou, actuals_ou)) / len(preds_ou)
        out["over_rate"] = sum(actuals_ou) / len(actuals_ou)
    return out


def _temperature(prob3, T):
    """Soften/sharpen a (h,d,a) prob tuple by temperature T (>1 softens)."""
    logits = [math.log(max(p, 1e-9)) / T for p in prob3]
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    s = sum(exps)
    return tuple(e / s for e in exps)


def _best_temperature(preds_1x2, actuals_1x2):
    """Grid-search the temperature that minimises pooled log loss."""
    best_T, best_ll = 1.0, float("inf")
    T = 0.6
    while T <= 2.4:
        ll = -sum(
            math.log(max(_temperature(p, T)[a.index(1)], 1e-9))
            for p, a in zip(preds_1x2, actuals_1x2)
        ) / len(preds_1x2)
        if ll < best_ll:
            best_ll, best_T = ll, T
        T += 0.05
    return best_T


def _calibration(pairs, n_bins=10):
    """pairs: list of (predicted_prob, outcome 0/1). Returns reliability rows."""
    bins = defaultdict(lambda: [0.0, 0, 0])  # sum_pred, sum_outcome, count
    for p, o in pairs:
        b = min(int(p * n_bins), n_bins - 1)
        bins[b][0] += p
        bins[b][1] += o
        bins[b][2] += 1
    rows = []
    for b in range(n_bins):
        if bins[b][2] == 0:
            continue
        cnt = bins[b][2]
        rows.append((bins[b][0] / cnt, bins[b][1] / cnt, cnt))
    return rows


def _tournament_instances(matches):
    """Group target-tournament matches into (label, start_date, [matches])."""
    groups = defaultdict(list)
    for m in matches:
        if m["tournament"] in TARGET_TOURNAMENTS:
            groups[(m["tournament"], m["year"])].append(m)
    instances = []
    for (tourn, year), ms in groups.items():
        if len(ms) < 16:  # filter out stray / partial entries; keep real finals
            continue
        ms.sort(key=lambda x: x["date"])
        instances.append((f"{tourn} {year}", ms[0]["date"], ms))
    instances.sort(key=lambda x: x[1])
    return instances


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-year", type=int, default=2006,
                    help="Earliest match year to load for training depth")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--json", default=None,
                    help="Write aggregate + calibration + per-tournament metrics to this JSON path")
    args = ap.parse_args()

    print("─" * 68)
    print("SOCCER MODEL — multi-tournament walk-forward validation (v2)")
    print("─" * 68)

    all_matches = load_international_results(min_year=args.min_year, competitive_only=True)
    print(f"Loaded {len(all_matches):,} competitive matches since {args.min_year}.")

    instances = _tournament_instances(all_matches)
    print(f"Found {len(instances)} tournament instances to test.\n")

    agg_p1, agg_a1, agg_po, agg_ao = [], [], [], []
    cal_fav, cal_ou = [], []  # calibration: favorite win prob; over 2.5
    per_tourn = []

    for label, start, ms in instances:
        train = [m for m in all_matches if m["date"] < start]
        if len(train) < 500:
            continue
        model = SoccerModelV2()
        model.fit(_matches=train, verbose=False)

        p1, a1, po, ao = [], [], [], []
        for m in ms:
            h, a = m["home_team"], m["away_team"]
            if model.get_elo(h) == model.DEFAULT_ELO or model.get_elo(a) == model.DEFAULT_ELO:
                continue
            pr = model.matchup(h, a, neutral=m.get("neutral", True))
            ph, pd, pa, pov = pr["home_win"], pr["draw"], pr["away_win"], pr["over_2_5"]
            hs, as_ = m["home_score"], m["away_score"]
            act = (1, 0, 0) if hs > as_ else ((0, 1, 0) if hs == as_ else (0, 0, 1))
            ou = 1 if hs + as_ > 2 else 0
            p1.append((ph, pd, pa)); a1.append(act)
            po.append(pov); ao.append(ou)
            # calibration feeds
            fav = max(ph, pd, pa)
            cal_fav.append((fav, 1 if (ph, pd, pa).index(fav) == act.index(1) else 0))
            cal_ou.append((pov, ou))

        mt = _metrics(p1, a1, po, ao)
        if not mt:
            continue
        per_tourn.append((label, mt))
        agg_p1 += p1; agg_a1 += a1; agg_po += po; agg_ao += ao

    # ── Aggregate ────────────────────────────────────────────────────────────
    agg = _metrics(agg_p1, agg_a1, agg_po, agg_ao)
    print("=" * 68)
    print("AGGREGATE (all tournaments pooled)")
    print("=" * 68)
    print(f"  Matches graded:        {agg['n']}")
    print(f"  1X2 Brier (norm):      {agg['brier_1x2']:.4f}   (naive uniform = 0.3333)")
    print(f"  1X2 Log loss:          {agg['log_loss']:.4f}   (naive uniform = 1.0986)")
    print(f"  1X2 Modal accuracy:    {agg['acc']*100:.1f}%")
    print(f"  O/U 2.5 Brier:         {agg['brier_ou']:.4f}   (naive base rate = 0.2500)")
    print(f"  O/U 2.5 actual over:   {agg['over_rate']*100:.1f}%")

    # Temperature-scaling headroom: how much does fixing overconfidence help?
    T = _best_temperature(agg_p1, agg_a1)
    scaled = [_temperature(p, T) for p in agg_p1]
    sc = _metrics(scaled, agg_a1, [], [])
    print(f"\n  Calibration headroom — temperature scaling (T={T:.2f}):")
    print(f"    1X2 Log loss:  {agg['log_loss']:.4f}  →  {sc['log_loss']:.4f}")
    print(f"    1X2 Brier:     {agg['brier_1x2']:.4f}  →  {sc['brier_1x2']:.4f}")

    print("\n  Favorite-pick calibration (predicted vs actual hit-rate):")
    for pred, obs, cnt in _calibration(cal_fav):
        bar = "█" * round(obs * 20)
        print(f"    pred {pred:5.2f}  actual {obs:5.2f}  (n={cnt:3d})  {bar}")

    print("\n  Over-2.5 calibration:")
    for pred, obs, cnt in _calibration(cal_ou):
        bar = "█" * round(obs * 20)
        print(f"    pred {pred:5.2f}  actual {obs:5.2f}  (n={cnt:3d})  {bar}")

    print("\n" + "=" * 68)
    print("PER TOURNAMENT")
    print("=" * 68)
    print(f"  {'Tournament':<24} {'n':>4} {'Brier':>7} {'LogL':>7} {'Acc':>6} {'OU-Br':>7}")
    for label, mt in per_tourn:
        print(f"  {label:<24} {mt['n']:>4} {mt['brier_1x2']:>7.3f} "
              f"{mt['log_loss']:>7.3f} {mt['acc']*100:>5.1f}% {mt.get('brier_ou', float('nan')):>7.3f}")

    print("─" * 68)

    if args.json:
        import json as _json
        from datetime import date as _date
        out = {
            "generated": _date.today().isoformat(),
            "n_tournaments": len(per_tourn),
            "n_matches": agg["n"],
            "min_year": args.min_year,
            "aggregate": {
                "brier_1x2": round(agg["brier_1x2"], 4),
                "brier_naive": 0.3333,
                "log_loss": round(agg["log_loss"], 4),
                "log_loss_naive": 1.0986,
                "modal_acc": round(agg["acc"], 4),
                "brier_ou": round(agg.get("brier_ou", float("nan")), 4),
                "brier_ou_naive": 0.25,
                "over_rate": round(agg.get("over_rate", 0.0), 4),
            },
            "calibration_favorite": [
                {"pred": round(p, 3), "actual": round(o, 3), "n": c}
                for p, o, c in _calibration(cal_fav)
            ],
            "calibration_over25": [
                {"pred": round(p, 3), "actual": round(o, 3), "n": c}
                for p, o, c in _calibration(cal_ou)
            ],
            "per_tournament": [
                {"label": label, "n": mt["n"], "brier_1x2": round(mt["brier_1x2"], 3),
                 "log_loss": round(mt["log_loss"], 3), "acc": round(mt["acc"], 4)}
                for label, mt in per_tourn
            ],
        }
        from pathlib import Path as _Path
        _Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        _Path(args.json).write_text(_json.dumps(out, indent=2))
        print(f"  Wrote metrics → {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
