#!/usr/bin/env python3
"""
Walk-forward backtest: fit Dixon-Coles on pre-WC2022 data, predict all 64 WC2022 matches.

Outputs:
  - Brier score for 1X2 (home/draw/away)
  - Brier score for over/under 2.5 goals
  - Calibration breakdown by round
  - Per-game predictions vs actual (--verbose)

Usage:
    python3 scripts/backtest_soccer.py
    python3 scripts/backtest_soccer.py --verbose
    python3 scripts/backtest_soccer.py --min-year 2015  # train on fewer years
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.soccer_data import load_training_data, load_world_cup_history
from src.models.soccer_model import SoccerModel

WC2022_START = date(2022, 11, 20)


def _brier_1x2(preds: list[tuple[float, float, float]], actuals: list[tuple[int, int, int]]) -> float:
    """Multi-class Brier score for 1X2. Naive baseline = 2/3 ≈ 0.667."""
    n = len(preds)
    if n == 0:
        return float("nan")
    total = 0.0
    for (ph, pd, pa), (ah, ad, aa) in zip(preds, actuals):
        total += (ph - ah) ** 2 + (pd - ad) ** 2 + (pa - aa) ** 2
    return total / n / 2  # divide by 2 to normalise to [0,1]


def _brier_binary(preds: list[float], actuals: list[int]) -> float:
    """Binary Brier score. Naive baseline = 0.25."""
    n = len(preds)
    if n == 0:
        return float("nan")
    return sum((p - a) ** 2 for p, a in zip(preds, actuals)) / n


def _log_loss_1x2(preds: list[tuple[float, float, float]], actuals: list[tuple[int, int, int]]) -> float:
    eps = 1e-9
    n = len(preds)
    if n == 0:
        return float("nan")
    total = 0.0
    for (ph, pd, pa), (ah, ad, aa) in zip(preds, actuals):
        total += ah * math.log(ph + eps) + ad * math.log(pd + eps) + aa * math.log(pa + eps)
    return -total / n


def _round_label(match_date: date) -> str:
    """Infer WC2022 round from date."""
    d = match_date
    if d < date(2022, 12, 3):
        return "Group stage"
    if d <= date(2022, 12, 6):
        return "Round of 16"
    if d <= date(2022, 12, 10):
        return "Quarter-finals"
    if d <= date(2022, 12, 14):
        return "Semi-finals"
    return "Final/3rd place"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", "-v", action="store_true", help="Print each game prediction")
    ap.add_argument("--min-year", type=int, default=2012, help="Min year for training data")
    args = ap.parse_args()

    print("─" * 60)
    print("WC2022 Backtest — Dixon-Coles")
    print("─" * 60)

    # ── Training data (pre-WC2022) ────────────────────────────────────────────
    all_matches = load_training_data(min_year=args.min_year)
    train_matches = [m for m in all_matches if m["date"] < WC2022_START]
    print(f"Training: {len(train_matches):,} competitive matches (up to {WC2022_START})")

    # ── Fit model ─────────────────────────────────────────────────────────────
    model = SoccerModel()
    model.fit(_matches=train_matches, verbose=False)

    # ── Test data: WC2022 ─────────────────────────────────────────────────────
    wc2022_matches = load_world_cup_history([2022])
    wc2022_matches = [m for m in wc2022_matches if m["date"] >= WC2022_START]
    print(f"Testing:  {len(wc2022_matches)} WC2022 matches\n")

    if not wc2022_matches:
        print("ERROR: No WC2022 matches found. Check data/cache/soccer/ for wc_2022.json.")
        return 1

    # ── Predict + evaluate ────────────────────────────────────────────────────
    preds_1x2:  list[tuple[float, float, float]] = []
    actuals_1x2: list[tuple[int, int, int]]       = []
    preds_ou:   list[float] = []
    actuals_ou: list[int]   = []

    # Per-round buckets
    rounds: dict[str, dict] = {}

    correct_1x2 = 0

    if args.verbose:
        print(f"{'Date':<12} {'Matchup':<35} {'P(H):P(D):P(A)':<20} {'Actual':<8} {'Correct'}")
        print("─" * 90)

    for m in wc2022_matches:
        home = m["home_team"]
        away = m["away_team"]
        hs   = m["home_score"]
        as_  = m["away_score"]

        if home not in model.teams or away not in model.teams:
            if args.verbose:
                print(f"  SKIP: {home} vs {away} — team not in model")
            continue

        probs = model.matchup(home, away, neutral=True)
        ph = probs["home_win"]
        pd = probs["draw"]
        pa = probs["away_win"]
        p_over25 = probs["over_2_5"]

        # Actual outcomes
        if hs > as_:
            actual_1x2 = (1, 0, 0)
            outcome_label = "H"
        elif hs == as_:
            actual_1x2 = (0, 1, 0)
            outcome_label = "D"
        else:
            actual_1x2 = (0, 0, 1)
            outcome_label = "A"

        actual_ou = 1 if (hs + as_) > 2 else 0

        preds_1x2.append((ph, pd, pa))
        actuals_1x2.append(actual_1x2)
        preds_ou.append(p_over25)
        actuals_ou.append(actual_ou)

        # Did the model's most likely outcome match?
        max_prob = max(ph, pd, pa)
        predicted_label = "H" if max_prob == ph else ("D" if max_prob == pd else "A")
        is_correct = predicted_label == outcome_label
        if is_correct:
            correct_1x2 += 1

        # Round bucket
        rnd = _round_label(m["date"])
        if rnd not in rounds:
            rounds[rnd] = {"preds_1x2": [], "actuals_1x2": [], "n": 0}
        rounds[rnd]["preds_1x2"].append((ph, pd, pa))
        rounds[rnd]["actuals_1x2"].append(actual_1x2)
        rounds[rnd]["n"] += 1

        if args.verbose:
            matchup_str = f"{home} vs {away}"
            prob_str = f"{ph:.2f}:{pd:.2f}:{pa:.2f}"
            correct_str = "✓" if is_correct else "✗"
            print(f"{str(m['date']):<12} {matchup_str:<35} {prob_str:<20} {outcome_label:<8} {correct_str}")

    n_games = len(preds_1x2)
    if n_games == 0:
        print("No games predicted.")
        return 1

    brier_1x2   = _brier_1x2(preds_1x2, actuals_1x2)
    log_loss    = _log_loss_1x2(preds_1x2, actuals_1x2)
    brier_ou    = _brier_binary(preds_ou, actuals_ou)
    accuracy_1x2 = correct_1x2 / n_games * 100
    over25_actual_rate = sum(actuals_ou) / len(actuals_ou)

    print("\n1X2 Results:")
    print(f"  Brier score:          {brier_1x2:.4f}  (naive baseline = {2/3:.4f})")
    print(f"  Log loss:             {log_loss:.4f}")
    print(f"  Accuracy (max prob):  {correct_1x2}/{n_games} ({accuracy_1x2:.1f}%)")

    print(f"\nOver/Under 2.5 Results:")
    print(f"  Brier score:          {brier_ou:.4f}  (naive baseline = 0.2500)")
    print(f"  Over-2.5 actual rate: {over25_actual_rate:.2f} ({sum(actuals_ou)}/{n_games} games)")

    print("\nBy round:")
    round_order = ["Group stage", "Round of 16", "Quarter-finals", "Semi-finals", "Final/3rd place"]
    for rnd in round_order:
        if rnd not in rounds:
            continue
        rd = rounds[rnd]
        rb = _brier_1x2(rd["preds_1x2"], rd["actuals_1x2"])
        print(f"  {rnd:<20} ({rd['n']:2d} games): Brier 1X2 = {rb:.4f}")

    # ── Summary verdict ───────────────────────────────────────────────────────
    print()
    if brier_1x2 < 0.60:
        verdict = "STRONG — meaningfully below naive baseline"
    elif brier_1x2 < 0.64:
        verdict = "GOOD — below naive baseline"
    elif brier_1x2 < 0.67:
        verdict = "FAIR — marginally below naive baseline"
    else:
        verdict = "WEAK — at or above naive baseline (model needs improvement)"
    print(f"Model verdict: {verdict}")
    print("─" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
