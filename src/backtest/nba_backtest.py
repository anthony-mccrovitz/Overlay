"""
NBA model backtest — out-of-sample test of project_game() against historical
games.

Pulls 2024-25 season game results + 2024-25 season-long team ratings from
nba_api, runs the production model on each game, compares projections to
actual scores. Synthesizes -110 spread/total lines at the rounded model
projection ± half-point intervals to test if the model can identify pricing
errors.

Caveats:
  - "Season-long" ratings include data from the games being predicted (mild
    in-sample leakage). True walk-forward backtest would need date-filtered
    rating snapshots, which is ~164 API calls per season. This test is the
    fast sanity check: if the model can't beat random in-sample, it's broken.
  - Synthetic lines (rounded projection ±2 pts) test edge identification when
    book disagrees with model. Real book lines weren't archived.

Run: python3 -m src.backtest.nba_backtest [--season 2024-25]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.models.nba_model import project_game
from src.data.nba_stats import _save_cache, _load_cache


OUTPUT_CSV = Path("output/nba_backtest.csv")


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _profit(stake: float, odds: float, won: bool) -> float:
    if not won:
        return -stake
    return stake * (odds / 100.0) if odds > 0 else stake * (100.0 / abs(odds))


def fetch_season_ratings(season: str) -> list[dict]:
    """Season-long team ratings (Advanced)."""
    cache_key = f"team_advanced_{season.replace('-', '_')}"
    cached = _load_cache(cache_key)
    if cached:
        return cached
    from nba_api.stats.endpoints import leaguedashteamstats
    resp = leaguedashteamstats.LeagueDashTeamStats(
        season=season,
        measure_type_detailed_defense="Advanced",
        timeout=30,
    )
    teams = resp.get_data_frames()[0].to_dict("records")
    _save_cache(cache_key, teams)
    return teams


def fetch_season_games(season: str) -> pd.DataFrame:
    """All regular-season games + scores for given season."""
    cache_key = f"games_{season.replace('-', '_')}"
    cached = _load_cache(cache_key)
    if cached:
        return pd.DataFrame(cached)
    from nba_api.stats.endpoints import leaguegamefinder
    resp = leaguegamefinder.LeagueGameFinder(
        season_nullable=season,
        season_type_nullable="Regular Season",
        league_id_nullable="00",
        timeout=30,
    )
    df = resp.get_data_frames()[0]
    _save_cache(cache_key, df.to_dict("records"))
    return df



def run_backtest(season: str = "2024-25", verbose: bool = True) -> pd.DataFrame:
    if verbose:
        print(f"\n  Fetching {season} ratings + games...")
    teams = fetch_season_ratings(season)
    games_df = fetch_season_games(season)

    # leaguegamefinder returns one row per team per game — pivot to one row per game
    if verbose:
        print(f"  {len(games_df)} team-game rows. Pivoting to game-level...")

    # Each game has two rows (one per team). Match on GAME_ID.
    away_rows = games_df[games_df["MATCHUP"].str.contains("@")].copy()
    home_rows = games_df[games_df["MATCHUP"].str.contains("vs.")].copy()

    games = away_rows.merge(
        home_rows[["GAME_ID", "TEAM_NAME", "PTS"]],
        on="GAME_ID", suffixes=("_away", "_home"),
    )
    games = games.rename(columns={
        "TEAM_NAME_away": "away_team",
        "TEAM_NAME_home": "home_team",
        "PTS_away": "away_score",
        "PTS_home": "home_score",
    })
    games["game_date"] = pd.to_datetime(games["GAME_DATE"])
    games = games.sort_values("game_date").reset_index(drop=True)

    if verbose:
        print(f"  {len(games)} games available for {season}.\n")

    # Run model on each game
    rows = []
    for _, g in games.iterrows():
        try:
            proj = project_game(
                away_team=g["away_team"],
                home_team=g["home_team"],
                all_teams=teams,
            )
        except Exception:
            continue

        actual_total = g["away_score"] + g["home_score"]
        # Convention: home spread negative when home favored
        actual_home_margin = g["home_score"] - g["away_score"]
        proj_total = proj["projected_total"]
        proj_home_margin = -proj["projected_spread"]  # away spread → home margin
        proj_home_score = proj["home_proj"]
        proj_away_score = proj["away_proj"]

        rows.append({
            "season":              season,
            "game_id":             g["GAME_ID"],
            "date":                g["game_date"].strftime("%Y-%m-%d"),
            "away_team":           g["away_team"],
            "home_team":           g["home_team"],
            "actual_away":         g["away_score"],
            "actual_home":         g["home_score"],
            "actual_total":        actual_total,
            "actual_home_margin":  actual_home_margin,
            "proj_away":           proj_away_score,
            "proj_home":           proj_home_score,
            "proj_total":          proj_total,
            "proj_home_margin":    proj_home_margin,
            "proj_home_winprob":   proj["home_win_prob"],
        })

    bt = pd.DataFrame(rows)
    if verbose:
        _report(bt)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    bt.to_csv(OUTPUT_CSV, index=False)
    if verbose:
        print(f"\n  Detailed results → {OUTPUT_CSV}")
    return bt


def _report(bt: pd.DataFrame) -> None:
    print("=" * 78)
    print("  NBA MODEL — IN-SAMPLE BACKTEST  (caveat: ratings include in-sample data)")
    print("=" * 78)

    n = len(bt)
    if n == 0:
        print("  No games — aborting.")
        return

    # 1. Total / spread MAE + bias
    total_err = bt["proj_total"] - bt["actual_total"]
    spread_err = bt["proj_home_margin"] - bt["actual_home_margin"]
    print(f"\n  PROJECTION ACCURACY  ({n:,} games)")
    print(f"  {'─'*60}")
    print(f"  Avg actual total:      {bt['actual_total'].mean():.1f}")
    print(f"  Avg projected total:   {bt['proj_total'].mean():.1f}")
    print(f"  Total MAE:             {total_err.abs().mean():.2f} pts")
    print(f"  Total bias:            {total_err.mean():+.2f} pts  {'(over-projecting)' if total_err.mean()>0 else '(under-projecting)'}")
    print(f"  Spread MAE:            {spread_err.abs().mean():.2f} pts")
    print(f"  Spread bias:           {spread_err.mean():+.2f} pts")

    # 2. ML accuracy
    bt["ml_pick"]    = bt["proj_home_winprob"] > 0.5
    bt["ml_actual"]  = bt["actual_home_margin"] > 0
    ml_correct = (bt["ml_pick"] == bt["ml_actual"]).sum()
    print(f"\n  MONEYLINE ACCURACY (sign of projected margin)")
    print(f"  {'─'*60}")
    print(f"  Picks correct:         {ml_correct}/{n} ({ml_correct/n:.1%})")
    print(f"  Home baseline:         {bt['ml_actual'].mean():.1%}")
    print(f"  Lift over baseline:    {(ml_correct/n - bt['ml_actual'].mean())*100:+.1f}pp")

    # 3. ATS at synthetic line (line = projected margin, see if ACTUAL covers)
    # Edge tier: |proj - synth_line| in pts. We synthesize lines as round(proj)
    # offsets the test toward "is our edge real". Better: compare to a flat
    # 0-pt line (always pick favored side).
    # Build synthetic edges: book line = round(proj) ± random offset 0/1/2/3
    # → compute "claimed edge" via normal CDF, bucket by edge tier.
    print(f"\n  ATS SIMULATION  (synthetic lines = projection ± offset)")
    print(f"  {'─'*60}")
    print(f"  {'OFFSET':<8} {'BETS':>6} {'WR':>7} {'ROI':>8}")

    SPREAD_STD = 12.0
    rows = []
    for offset in [-3, -2, -1, 0, 1, 2, 3]:
        # Book line: home margin = proj_home_margin - offset (positive offset = book shaded toward away)
        # Bet HOME if model thinks proj_home_margin > book_line; pick wins if actual_home_margin > book_line
        book_line = bt["proj_home_margin"] - offset
        # If offset > 0, book line is BELOW projection → bet over (home wins by more) → bet HOME spread
        # If offset < 0, book line is ABOVE projection → bet UNDER → bet AWAY spread
        bet_home = offset > 0
        if offset == 0:
            continue
        won = (bt["actual_home_margin"] > book_line) if bet_home else (bt["actual_home_margin"] < book_line)
        push = (bt["actual_home_margin"] == book_line)
        valid = ~push
        wr = won[valid].mean()
        # -110 flat
        profits = won[valid].apply(lambda w: _profit(1.0, -110, bool(w)))
        roi = profits.sum() / valid.sum() * 100
        side = "HOME" if bet_home else "AWAY"
        rows.append((offset, side, valid.sum(), wr, roi))
        print(f"  {offset:+d}pts {side:<5} {valid.sum():>6} {wr:>6.1%}  {roi:>+6.1f}%")

    # 4. O/U at synthetic line
    print(f"\n  O/U SIMULATION  (synthetic line = projected total ± offset)")
    print(f"  {'─'*60}")
    print(f"  {'OFFSET':<8} {'BETS':>6} {'WR':>7} {'ROI':>8}")
    for offset in [-3, -2, -1, 1, 2, 3]:
        book_line = bt["proj_total"] - offset
        # offset > 0: book lower than projection → bet OVER
        bet_over = offset > 0
        won = (bt["actual_total"] > book_line) if bet_over else (bt["actual_total"] < book_line)
        push = (bt["actual_total"] == book_line)
        valid = ~push
        wr = won[valid].mean()
        profits = won[valid].apply(lambda w: _profit(1.0, -110, bool(w)))
        roi = profits.sum() / valid.sum() * 100
        side = "OVER" if bet_over else "UNDER"
        print(f"  {offset:+d}pts {side:<5} {valid.sum():>6} {wr:>6.1%}  {roi:>+6.1f}%")

    # 5. Verdict
    print(f"\n  {'='*60}")
    print(f"  VERDICT")
    print(f"  {'='*60}")
    if total_err.abs().mean() > 14:
        print(f"  ❌ Total MAE > 14 pts — projections too noisy to find total edges.")
    elif total_err.abs().mean() > 11:
        print(f"  ⚠️  Total MAE 11-14 pts — borderline. Edges only at >5pt offsets.")
    else:
        print(f"  ✅ Total MAE < 11 pts — projections tight enough for edge detection.")
    if abs(total_err.mean()) > 3:
        print(f"  ⚠️  Total bias {total_err.mean():+.1f} — recalibrate global scale.")
    if abs(spread_err.mean()) > 2:
        print(f"  ⚠️  Spread bias {spread_err.mean():+.1f} — home-court / rest weights need tuning.")
    if ml_correct / n < 0.55:
        print(f"  ❌ ML accuracy {ml_correct/n:.1%} — barely above home baseline.")
    elif ml_correct / n < 0.62:
        print(f"  ⚠️  ML accuracy {ml_correct/n:.1%} — average. Look at Kelly sizing carefully.")
    else:
        print(f"  ✅ ML accuracy {ml_correct/n:.1%} — strong sign of signal.")
    print(f"  {'='*60}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2024-25")
    args = ap.parse_args()
    run_backtest(args.season, verbose=True)


if __name__ == "__main__":
    main()
