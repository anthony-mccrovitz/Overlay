"""
Reliability / calibration report for the club soccer models (no odds, no API).

A model's edge is only trustworthy if its probabilities are calibrated: when it
says 60%, that outcome should happen ~60% of the time. This walks the model
forward (fit on the earlier split, predict the later split from causal
snapshots), pools every 1X2 prediction, bins by predicted probability, and
compares predicted vs actual frequency. Reports per-bin reliability + ECE
(expected calibration error) with and without the fitted temperature.

Run:  python3 scripts/calibrate_club_report.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.soccer_club_data import load_club_matches
from src.models.soccer_club_model import SoccerClubModel

LEAGUES = ["soccer_usa_mls", "soccer_mexico_ligamx"]
TRAIN_FRAC = 0.70
BINS = [(0.0, 0.15), (0.15, 0.25), (0.25, 0.35), (0.35, 0.45),
        (0.45, 0.55), (0.55, 0.70), (0.70, 1.01)]


def _collect(sport_key: str):
    matches = sorted(load_club_matches(sport_key), key=lambda x: x["date"])
    n = len(matches)
    split = int(n * TRAIN_FRAC)
    train = matches[:split]

    m = SoccerClubModel(sport_key)
    m.fit(verbose=False, _matches=train)
    T = m.temperature

    m2 = SoccerClubModel(sport_key)
    m2.k_factor = m.k_factor
    m2.xg_sot, m2.xg_off = m.xg_sot, m.xg_off
    snaps = m2._compute_rolling_elo(matches)
    for a in ("mu", "alpha", "beta", "delta", "gamma", "c_alt", "c_travel",
              "c_rest", "rho", "temperature", "tempo_shrink", "league_avg"):
        setattr(m2, a, getattr(m, a))

    # (predicted_prob, occurred) pooled over all 3 outcomes; keep raw (T=1) too.
    pairs, pairs_raw = [], []
    for i in range(split, n):
        mt = matches[i]
        eh, ea, ah, da, aa, dh, *_ = snaps[i]
        h, a = mt["home_team"], mt["away_team"]
        m2.elo_ratings[h], m2.elo_ratings[a] = eh, ea
        m2.atk_ratings[h], m2.dfn_ratings[h] = ah, dh
        m2.atk_ratings[a], m2.dfn_ratings[a] = aa, da
        occ = (mt["home_score"] > mt["away_score"], mt["home_score"] == mt["away_score"],
               mt["home_score"] < mt["away_score"])
        m2.temperature = T
        r = m2.matchup(h, a, neutral=False)
        for p, o in zip((r["home_win"], r["draw"], r["away_win"]), occ):
            pairs.append((p, int(o)))
        m2.temperature = 1.0
        r0 = m2.matchup(h, a, neutral=False)
        for p, o in zip((r0["home_win"], r0["draw"], r0["away_win"]), occ):
            pairs_raw.append((p, int(o)))
    return pairs, pairs_raw, T, len(matches) - split


def _reliability(pairs):
    rows, ece, ntot = [], 0.0, len(pairs)
    for lo, hi in BINS:
        b = [(p, o) for p, o in pairs if lo <= p < hi]
        if not b:
            continue
        pred = sum(p for p, _ in b) / len(b)
        act = sum(o for _, o in b) / len(b)
        rows.append((lo, hi, len(b), pred, act))
        ece += (len(b) / ntot) * abs(pred - act)
    return rows, ece


def main() -> int:
    out = {}
    for lg in LEAGUES:
        print("=" * 66)
        pairs, pairs_raw, T, ntest = _collect(lg)
        rows, ece = _reliability(pairs)
        _, ece_raw = _reliability(pairs_raw)
        print(f"  {lg}  (test predictions: {len(pairs)} over {ntest} matches)  T={T:.2f}")
        print(f"  {'bin':>12} {'n':>5} {'predicted':>10} {'actual':>8}  reliability")
        for lo, hi, n, pred, act in rows:
            bar = "" if abs(pred - act) < 0.03 else ("  under-confident" if act > pred else "  over-confident")
            print(f"  {lo:.2f}-{hi:.2f} {n:>7} {pred:>10.3f} {act:>8.3f}{bar}")
        print(f"  ECE (calibrated T={T:.2f}): {ece:.4f}   |   ECE (raw T=1): {ece_raw:.4f}")
        verdict = "well-calibrated" if ece < 0.03 else ("acceptable" if ece < 0.05 else "MISCALIBRATED")
        print(f"  → {verdict} (ECE {ece:.3f}; <0.03 good, <0.05 ok)")
        out[lg] = {"T": T, "ece": round(ece, 4), "ece_raw": round(ece_raw, 4),
                   "n_test_matches": ntest, "verdict": verdict,
                   "bins": [{"lo": lo, "hi": hi, "n": n, "pred": round(pred, 4),
                             "act": round(act, 4)} for lo, hi, n, pred, act in rows]}
    Path("data/models/soccer_club_calibration.json").write_text(json.dumps(out, indent=2))
    print("=" * 66)
    print("  wrote data/models/soccer_club_calibration.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
