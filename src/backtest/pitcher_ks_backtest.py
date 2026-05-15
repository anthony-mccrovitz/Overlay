"""
Walk-forward backtest for the production pitcher strikeout prop model.

Tests the formula in src/data/player_props.py::_project_strikeouts against
historical pitcher game logs (2024+) using only prior-game features.

What this answers:
  1. MAE — how off is the projection on average?
  2. O/U hit rate — at typical lines (recent_k_avg rounded to .5), does the
     model pick the correct side better than 50%?
  3. Calibration — when the model says "62% over," does it actually go
     over 62% of the time? (Reliability curve in deciles.)
  4. Edge ROI — bucket bets by claimed edge tier, simulate -110 flat
     betting, report ROI per tier. This is the bottom-line question:
     do high-edge calls actually pay?

Run: python3 -m src.backtest.pitcher_ks_backtest [--season 2024]
"""
from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.models.mlb_pitcher_ks import build_ks_training_data


OUTPUT_CSV = Path("output/pitcher_ks_backtest.csv")


def _poisson_p_over(lam: float, line: float) -> float:
    """P(K > line) where K ~ Poisson(lambda). Floor line for integer cutoff."""
    floor_line = int(line)
    p_under_or_eq = sum(
        math.exp(-lam) * (lam ** k) / math.factorial(k)
        for k in range(floor_line + 1)
    )
    return max(0.0, min(1.0, 1.0 - p_under_or_eq))


def _project_strikeouts_proxy(k9: float, recent_k_avg: float, avg_ip: float, opp_k_rate: float) -> float:
    """
    Mirrors src/data/player_props.py::_project_strikeouts using opp_k_rate
    as a proxy for lineup_ops.

    Calibration: lineup OPS ranges ~0.700 (high-K teams) to ~0.760 (low-K teams).
    K rates range ~0.18 (contact teams) to ~0.27 (whiff-prone). At league avg
    K%=0.225 → OPS≈0.730. Slope from end-points: lineup_ops = 0.880 - 0.67*opp_k_rate.
    """
    recent_k9 = (recent_k_avg / max(avg_ip, 1.0)) * 9.0
    blended_k9 = k9 * 0.4 + recent_k9 * 0.6
    lineup_ops = 0.880 - 0.67 * opp_k_rate
    ops_delta = 0.720 - lineup_ops
    k9_adj = blended_k9 * (1 + ops_delta * 1.5)
    return (k9_adj / 9.0) * avg_ip


def _profit(stake: float, odds: float, won: bool) -> float:
    if not won:
        return -stake
    return stake * (odds / 100.0) if odds > 0 else stake * (100.0 / abs(odds))


def run_backtest(seasons: list[int], verbose: bool = True) -> pd.DataFrame:
    if verbose:
        print(f"\n  Building training data for {seasons}...")
    df = build_ks_training_data(seasons=seasons, verbose=verbose)
    if df.empty:
        raise SystemExit("No data — check MLB Stats API access.")

    if verbose:
        print(f"  Loaded {len(df)} historical starts.\n")

    # Filter to legit starts only — exclude openers, bullpen days, and very-early-season
    # rows where prior_starts < 5 (model has too little signal).
    df = df[(df["actual_ip"] >= 4.0) & (df["pitcher_avg_ip"] >= 4.0) & (df["pitcher_starts"] >= 5)]
    if verbose:
        print(f"  After filter (IP≥4, starts≥5): {len(df):,} rows.\n")

    rows = []
    for r in df.itertuples():
        actual = r.actual_ks
        proj = _project_strikeouts_proxy(
            k9=r.pitcher_k9,
            recent_k_avg=r.pitcher_recent_k_avg,
            avg_ip=r.pitcher_avg_ip,
            opp_k_rate=r.opp_team_k_rate,
        )
        # Synthesize the book line as recent_k_avg rounded to nearest .5,
        # which is roughly what BetMGM/FD/DK post for established starters.
        synth_line = round(r.pitcher_recent_k_avg * 2) / 2.0
        if synth_line < 2.5:
            continue  # skip openers / relievers

        p_over = _poisson_p_over(proj, synth_line)
        # Book line at -110 / -110 implies 52.4% breakeven each side
        book_p_over = 0.524
        edge_over = p_over - book_p_over
        edge_under = (1.0 - p_over) - book_p_over

        # Pick the side with positive edge (if any)
        if edge_over >= edge_under and edge_over > 0:
            side = "OVER"
            model_prob = p_over
            edge = edge_over
            won = actual > synth_line
        elif edge_under > 0:
            side = "UNDER"
            model_prob = 1.0 - p_over
            edge = edge_under
            won = actual < synth_line
        else:
            continue  # no claimed edge

        if actual == synth_line:
            continue  # push (rare with .5 lines)

        rows.append({
            "season": r.season,
            "pitcher_id": r.pitcher_id,
            "game_pk": r.game_pk,
            "actual_ks": actual,
            "projected_ks": proj,
            "synth_line": synth_line,
            "side": side,
            "model_prob": model_prob,
            "edge_pct": edge * 100.0,
            "won": won,
            "profit_units": _profit(1.0, -110, won),
        })

    bt = pd.DataFrame(rows)
    if verbose:
        _report(bt, df)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    bt.to_csv(OUTPUT_CSV, index=False)
    if verbose:
        print(f"\n  Detailed results → {OUTPUT_CSV}")
    return bt


def _report(bt: pd.DataFrame, df: pd.DataFrame) -> None:
    print("=" * 78)
    print("  PITCHER STRIKEOUT PROP — WALK-FORWARD BACKTEST")
    print("=" * 78)

    # 1. MAE on filtered starts only (the same set we evaluated bets on)
    full_pred = []
    full_actual = []
    df_filtered = df[(df["actual_ip"] >= 4.0) & (df["pitcher_avg_ip"] >= 4.0) & (df["pitcher_starts"] >= 5)]
    for r in df_filtered.itertuples():
        proj = _project_strikeouts_proxy(
            k9=r.pitcher_k9, recent_k_avg=r.pitcher_recent_k_avg,
            avg_ip=r.pitcher_avg_ip, opp_k_rate=r.opp_team_k_rate,
        )
        full_pred.append(proj)
        full_actual.append(r.actual_ks)
    arr_p, arr_a = np.array(full_pred), np.array(full_actual)
    mae = np.mean(np.abs(arr_p - arr_a))
    baseline_mae = np.mean(np.abs(arr_a.mean() - arr_a))
    rmse = float(np.sqrt(np.mean((arr_p - arr_a) ** 2)))
    bias = float(np.mean(arr_p - arr_a))

    print(f"\n  PROJECTION CALIBRATION")
    print(f"  {'─'*60}")
    print(f"  Sample size:           {len(arr_a):,} starts")
    print(f"  Actual mean Ks:        {arr_a.mean():.2f}")
    print(f"  Projected mean Ks:     {arr_p.mean():.2f}")
    print(f"  MAE:                   {mae:.2f} Ks")
    print(f"  Baseline MAE (mean):   {baseline_mae:.2f} Ks")
    print(f"  Lift over baseline:    {(baseline_mae-mae)/baseline_mae*100:+.1f}%")
    print(f"  RMSE:                  {rmse:.2f} Ks")
    print(f"  Bias (proj-actual):    {bias:+.2f} Ks  {'(over-projecting)' if bias > 0 else '(under-projecting)'}")

    if bt.empty:
        print(f"\n  ⚠️  No bets cleared the 0% edge threshold — model never disagrees with synthetic line.")
        return

    # 2. O/U hit rate
    print(f"\n  BETTING SIMULATION (-110 flat, 1u stake)")
    print(f"  {'─'*60}")
    n = len(bt)
    wins = bt["won"].sum()
    losses = n - wins
    profit = bt["profit_units"].sum()
    roi = profit / n * 100
    print(f"  Total picks:           {n:,}")
    print(f"  Record:                {wins}-{losses}  ({wins/n:.1%} WR)")
    print(f"  Profit:                {profit:+.1f}u")
    print(f"  ROI:                   {roi:+.2f}%")
    print(f"  Breakeven WR @ -110:   52.4%")

    # 3. Edge tier breakdown — THE KEY QUESTION
    print(f"\n  EDGE TIER ROI — does claimed edge translate to realized profit?")
    print(f"  {'─'*60}")
    tiers = [
        ("0-5%",   0.0,   5.0),
        ("5-10%",  5.0,  10.0),
        ("10-15%",10.0,  15.0),
        ("15-20%",15.0,  20.0),
        ("20-30%",20.0,  30.0),
        ("30%+",  30.0, 100.0),
    ]
    print(f"  {'TIER':<10} {'BETS':>6} {'WR':>7} {'BREAKEVEN':>10} {'ROI':>8}  EXPECTED-vs-REALIZED")
    for label, lo, hi in tiers:
        sub = bt[(bt["edge_pct"] >= lo) & (bt["edge_pct"] < hi)]
        if len(sub) < 10:
            print(f"  {label:<10} {len(sub):>6}  (too few to evaluate)")
            continue
        wr = sub["won"].mean()
        sub_roi = sub["profit_units"].sum() / len(sub) * 100
        # Expected EV at midpoint of tier
        midpoint_edge = (lo + hi) / 2
        expected_roi = midpoint_edge  # rough: edge%→ROI%
        diff = sub_roi - expected_roi
        flag = "✅" if diff > -3 else "⚠️ " if diff > -10 else "❌"
        print(f"  {label:<10} {len(sub):>6}  {wr:>5.1%}  {52.4:>8.1f}%   {sub_roi:>+5.1f}%   model claimed ~{midpoint_edge:.0f}% → got {sub_roi:+.1f}%  {flag}")

    # 4. Calibration — model prob bins vs actual hit rate
    print(f"\n  PROBABILITY CALIBRATION (reliability)")
    print(f"  {'─'*60}")
    print(f"  {'BIN':<14} {'BETS':>6} {'CLAIMED':>10} {'ACTUAL':>10} {'DELTA':>8}")
    bins = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.80), (0.80, 1.01)]
    for lo, hi in bins:
        sub = bt[(bt["model_prob"] >= lo) & (bt["model_prob"] < hi)]
        if len(sub) < 10:
            continue
        claimed = sub["model_prob"].mean()
        actual = sub["won"].mean()
        delta = actual - claimed
        flag = "✅" if abs(delta) < 0.03 else "⚠️ " if abs(delta) < 0.07 else "❌"
        print(f"  {lo:.2f}-{hi:.2f}     {len(sub):>6}  {claimed:>9.1%}  {actual:>9.1%}  {delta:>+7.1%}  {flag}")

    # 5. Bottom line
    print(f"\n  {'='*60}")
    print(f"  VERDICT")
    print(f"  {'='*60}")
    if roi < -2:
        print(f"  ❌ NEGATIVE EV — production formula is leaking money.")
        print(f"     Recommend: throttle K props or rebuild model.")
    elif roi < 1:
        print(f"  ⚠️  MARGINAL — claimed edges are roughly market-priced.")
        print(f"     Recommend: only post highest-edge tier; small stakes.")
    else:
        print(f"  ✅ POSITIVE EV — formula has real signal at the realized rate.")
        print(f"     Recommend: continue posting, study which edge tiers pay best.")
    print(f"  {'='*60}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int, default=[2024, 2025])
    args = ap.parse_args()
    run_backtest(args.seasons, verbose=True)


if __name__ == "__main__":
    main()
