#!/usr/bin/env python3
"""
March Madness Bracket Predictor — CLI Entry Point

Usage:
  python predict.py                          # Generate bracket with defaults
  python predict.py --pool-size 50           # Optimize for 50-person pool
  python predict.py --bankroll 500           # Size bets with $500 bankroll
  python predict.py --year 2026              # Specify tournament year
  python predict.py --refresh                # Re-scrape Barttorvik data
  python predict.py --verbose                # Show per-model predictions
  python predict.py --backtest               # Run historical backtesting
  python predict.py --no-ensemble            # Use XGBoost only (faster)
  python predict.py --sims 20000             # Monte Carlo simulations

Daily edge-finder (multi-sport):
  python predict.py --daily --sport mlb          # MLB model-backed picks
  python predict.py --daily --sport mlb --bankroll 500  # With Kelly sizing
  python predict.py --daily --sport nba          # NBA (line-shopping mode)

Grading (auto-grade against actual results):
  python predict.py --grade --sport mlb          # Grade today's MLB picks
  python predict.py --grade --grade-date 2026-03-31 --sport mlb  # Grade specific date
  python predict.py --grade-poll --sport mlb     # Poll every 30min until all graded
  python predict.py --grade --stake 200          # Grade with $200 flat stake
"""
import argparse
import json
import os
import sys
import warnings
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

from src.data import kaggle_loader, barttorvik, odds_api
from src.data.store import build_training_data, load_team_stats, load_tourney_matchups, _make_matchup_row
from src.features.engineering import prepare_features
from src.models.xgboost_model import XGBoostModel
from src.models.logistic import LogisticModel
from src.models.neural import NeuralModel
from src.models.bayesian import BayesianModel
from src.models.elo import EloModel
from src.models.ensemble import EnsembleModel
from src.simulation.bracket import build_bracket, print_bracket
from src.simulation.monte_carlo import simulate_tournament, print_advancement_probs
from src.simulation.pool_optimizer import optimize_for_pool, print_pool_picks
from src.betting.value_bets import find_value_bets, print_value_bets
from src.betting.kelly import size_bets, print_kelly_bets
from src.output.pick_card import generate_pick_card_image, generate_pick_card_text


def main():
    parser = argparse.ArgumentParser(
        description="March Madness AI Bracket Predictor"
    )
    parser.add_argument("--year", type=int, default=2026, help="Tournament year")
    parser.add_argument("--pool-size", type=int, default=0, help="Pool size for optimization")
    parser.add_argument("--bankroll", type=float, default=0, help="Bankroll for Kelly sizing ($)")
    parser.add_argument("--refresh", action="store_true", help="Re-scrape Barttorvik data")
    parser.add_argument("--min-edge", type=float, default=0.03, help="Min edge for value bets")
    parser.add_argument("--kelly-fraction", type=float, default=0.5, help="Kelly fraction (0.5=half)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    parser.add_argument("--backtest", action="store_true", help="Run backtesting mode")
    parser.add_argument("--no-ensemble", action="store_true", help="Use XGBoost only (faster)")
    parser.add_argument("--sims", type=int, default=10000, help="Monte Carlo simulations")
    parser.add_argument("--daily", action="store_true", help="Daily edge-finder mode (social-ready picks)")
    parser.add_argument(
        "--sport",
        type=str,
        default="ncaab",
        help="Sport key alias: ncaab, nba, mlb, nfl",
    )
    parser.add_argument("--train-mlb", action="store_true", help="Train XGBoost MLB model on historical data")
    parser.add_argument("--train-totals", action="store_true", help="Train MLB totals (over/under) model")
    parser.add_argument(
        "--markets",
        type=str,
        default="all",
        help="Markets to analyze: all, moneyline, spreads, totals (comma-separated)",
    )
    parser.add_argument("--grade", action="store_true", help="Grade today's picks against actual results")
    parser.add_argument("--grade-poll", action="store_true", help="Poll and grade as games finish")
    parser.add_argument("--grade-date", type=str, default=None, help="Date to grade (YYYY-MM-DD)")
    parser.add_argument("--stake", type=float, default=100.0, help="Flat stake per bet for grading ($)")
    parser.add_argument("--tomorrow", action="store_true", help="Run picks for tomorrow (bet tonight for best CLV)")
    parser.add_argument("--close", action="store_true", help="Snapshot closing lines before first pitch for CLV")
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f"  MARCH MADNESS {args.year} — AI BRACKET PREDICTOR")
    print(f"{'='*70}\n")

    if args.train_mlb:
        run_mlb_training(args)
        return
    if args.train_totals:
        run_totals_training(args)
        return
    if args.grade or args.grade_poll:
        run_grade(args)
        return
    if args.backtest:
        sport = _resolve_sport(args.sport) if args.sport != "ncaab" else "basketball_ncaab"
        if sport == "baseball_mlb":
            run_mlb_backtest_cmd(args)
        else:
            run_backtest(args)
        return
    if args.close:
        run_close_snapshot(args)
        return
    if args.daily:
        run_daily(args)
        return

    run_prediction(args)


def _build_model(args, X_train, y_train):
    """Build and train the prediction model (ensemble or XGBoost-only)."""
    if args.no_ensemble:
        print("\nStep 3: Training XGBoost model...")
        model = XGBoostModel()
        model.train(X_train, y_train)
        metrics = model.evaluate(X_train, y_train)
        print(f"  Training accuracy: {metrics['accuracy']:.1%}")
        print(f"  Training log loss: {metrics['log_loss']:.4f}")
        return model

    print("\nStep 3: Training 5-model ensemble...")
    ensemble = EnsembleModel()
    ensemble.add_model(XGBoostModel())
    ensemble.add_model(LogisticModel())
    ensemble.add_model(NeuralModel())
    ensemble.add_model(BayesianModel())
    ensemble.add_model(EloModel())

    ensemble.train(X_train, y_train)

    # Use time-based split for validation weights
    # Last 20% of training data as validation
    n = len(X_train)
    split = int(n * 0.8)
    X_val, y_val = X_train.iloc[split:], y_train.iloc[split:]

    print("\n  Optimizing ensemble weights on validation split...")
    ensemble.optimize_weights(X_val, y_val)

    # Report ensemble vs individual
    ensemble_metrics = ensemble.evaluate(X_train, y_train)
    print(f"\n  Ensemble training accuracy: {ensemble_metrics['accuracy']:.1%}")
    print(f"  Ensemble training log loss: {ensemble_metrics['log_loss']:.4f}")
    print(f"  Active models: {ensemble_metrics['n_models']}/5")

    if args.verbose:
        for m in ensemble._trained_models:
            m_metrics = m.evaluate(X_train, y_train)
            print(f"    {m.name}: {m_metrics['accuracy']:.1%} acc, {m_metrics['log_loss']:.4f} loss")

    return ensemble


def run_prediction(args):
    """Main prediction pipeline: data → model → bracket → Monte Carlo → bets."""

    # Step 1: Load data
    print("Step 1: Loading data...")

    if not kaggle_loader.check_data_exists():
        print("\n  ERROR: Kaggle data not found!")
        print("  " + "─" * 50)
        print("  Download the March Machine Learning Mania dataset:")
        print("    1. pip install kaggle")
        print("    2. Search: kaggle competitions list -s 'march machine learning mania'")
        print("    3. kaggle competitions download -c <competition-slug>")
        print("    4. Unzip into data/kaggle/")
        print("  " + "─" * 50)
        sys.exit(1)

    # Step 2: Build training data from historical tournaments
    print("\nStep 2: Building training data...")
    # Use KenPom/Barttorvik advanced stats for training if available
    from src.data import kenpom as kenpom_module
    use_advanced = kenpom_module.check_data_exists()
    if use_advanced:
        print("  Using KenPom advanced stats for historical training")
    try:
        X_train, y_train = build_training_data(
            min_year=2010,
            max_year=args.year - 1,
            use_barttorvik=use_advanced,
        )
        print(f"  Training data: {len(X_train)} historical matchups")
        print(f"  Higher seed win rate: {y_train.mean():.1%}")
    except Exception as e:
        print(f"\n  ERROR building training data: {e}")
        sys.exit(1)

    # Step 3: Train model (ensemble or XGBoost-only)
    model = _build_model(args, X_train, y_train)

    if args.verbose and hasattr(model, 'feature_importance'):
        print("\n  Feature importance:")
        importance = model.feature_importance()
        for feat, imp in sorted(importance.items(), key=lambda x: -x[1])[:10]:
            print(f"    {feat}: {imp:.3f}")

    # Step 4: Load current season data
    print(f"\nStep 4: Loading {args.year} season data...")
    try:
        current_stats = load_team_stats(
            season=args.year,
            use_barttorvik=True,
            refresh=args.refresh,
        )
        seeds = load_tourney_matchups(args.year)
        print(f"  Tournament teams: {len(seeds)}")
    except Exception as e:
        print(f"\n  ERROR loading current season: {e}")
        sys.exit(1)

    # Build team lookup
    teams_df = kaggle_loader.load_teams()
    team_names = dict(zip(teams_df["TeamID"], teams_df["CanonicalName"]))
    seed_map = dict(zip(seeds["TeamID"], seeds["SeedNum"]))

    # Step 5: Build prediction function
    def predict_matchup(team_a_id, team_b_id, seed_a, seed_b):
        """Predict P(team_a wins) for a single matchup."""
        stats_a = current_stats[current_stats["TeamID"] == team_a_id]
        stats_b = current_stats[current_stats["TeamID"] == team_b_id]

        if stats_a.empty or stats_b.empty:
            # Fallback: use seed-based prior
            seed_diff = seed_b - seed_a
            return 1 / (1 + np.exp(-0.15 * seed_diff))

        row = _make_matchup_row(stats_a.iloc[0], stats_b.iloc[0], seed_a, seed_b, args.year)
        df = pd.DataFrame([row])
        prob = model.predict_proba(df)[0]
        return prob

    # Step 6: Generate bracket (deterministic — always picks the favorite)
    print(f"\nStep 5: Generating bracket...")
    bracket = build_bracket(
        seeds_df=seeds,
        team_names=team_names,
        predict_fn=predict_matchup,
        year=args.year,
    )

    bracket_str = print_bracket(bracket)
    print(bracket_str)

    # Step 7: Monte Carlo simulation
    print(f"Step 6: Running Monte Carlo simulation ({args.sims:,} tournaments)...")
    # Build win probability matrix for all possible matchups
    tourney_team_ids = seeds["TeamID"].values
    win_probs = {}
    for i, team_a in enumerate(tourney_team_ids):
        seed_a = seed_map.get(team_a, 8)
        for team_b in tourney_team_ids[i + 1:]:
            seed_b = seed_map.get(team_b, 8)
            # Always store with lower seed first
            if seed_a <= seed_b:
                prob = predict_matchup(team_a, team_b, seed_a, seed_b)
                win_probs[(team_a, team_b)] = prob
            else:
                prob = predict_matchup(team_b, team_a, seed_b, seed_a)
                win_probs[(team_b, team_a)] = prob

    adv_probs = simulate_tournament(
        win_probs=win_probs,
        seeds_df=seeds,
        n_sims=args.sims,
    )
    print(print_advancement_probs(adv_probs, team_names))

    # Step 8: Pool optimization (if pool size specified)
    if args.pool_size > 0:
        print(f"Step 7: Optimizing for {args.pool_size}-person pool...")
        pool_picks = optimize_for_pool(
            advancement_probs=adv_probs,
            pool_size=args.pool_size,
        )
        print(print_pool_picks(pool_picks, team_names, args.pool_size))

    # Step 9: Odds comparison and value bets
    print("Step 8: Checking odds...")
    odds_df = odds_api.fetch_odds(refresh=args.refresh)

    if not odds_df.empty:
        best_odds = odds_api.get_best_odds(odds_df)

        # Build predictions dict for value bet comparison
        predictions = {}
        for game in bracket.games:
            if game.round_num == 1:  # Only bet on R64 games (most odds available)
                predictions[(game.team_a_name, game.team_b_name)] = game.win_prob_a

        value_bets = find_value_bets(predictions, best_odds, min_edge=args.min_edge)
        print(print_value_bets(value_bets, args.bankroll))

        # Step 10: Kelly sizing
        if args.bankroll > 0 and not value_bets.empty:
            sized_bets = size_bets(
                value_bets,
                bankroll=args.bankroll,
                kelly_fraction_pct=args.kelly_fraction,
            )
            print(print_kelly_bets(sized_bets, args.bankroll))
    else:
        print("  No odds available. Set ODDS_API_KEY in .env for betting analysis.")

    # Save outputs
    os.makedirs("output", exist_ok=True)

    bracket_data = pd.DataFrame(bracket.to_dict())
    bracket_data.to_csv(f"output/bracket_{args.year}.csv", index=False)
    print(f"\n  Bracket saved to output/bracket_{args.year}.csv")

    adv_probs_out = adv_probs.copy()
    adv_probs_out["TeamName"] = adv_probs_out["TeamID"].map(team_names)
    adv_probs_out.to_csv(f"output/advancement_{args.year}.csv", index=False)
    print(f"  Advancement probs saved to output/advancement_{args.year}.csv")

    if args.pool_size > 0:
        pool_out = pool_picks.copy()
        pool_out["TeamName"] = pool_out["TeamID"].map(team_names)
        pool_out.to_csv(f"output/pool_picks_{args.year}.csv", index=False)
        print(f"  Pool picks saved to output/pool_picks_{args.year}.csv")


def run_mlb_training(args):
    """
    Professional-grade MLB model training.

    Uses 16 seasons (2008-2024), walk-forward CV, probability calibration,
    and evaluates on held-out 2025 season.
    """
    from src.models.mlb_xgboost import (
        train_mlb_model, print_training_results,
        TRAIN_SEASONS, TEST_SEASONS,
    )

    print(f"\n{'='*70}")
    print("  MLB v3 — STACKING ENSEMBLE + ELO + REST/BULLPEN/TRAVEL")
    print(f"{'='*70}")
    print(f"\n  Training on {len(TRAIN_SEASONS)} seasons: {TRAIN_SEASONS[0]}-{TRAIN_SEASONS[-1]}")
    print(f"  Testing on: {TEST_SEASONS}")
    print(f"  v3: XGBoost + LightGBM + CatBoost + stacking meta-learner")
    print(f"  v3: Elo ratings, rest days, bullpen ERA, travel distance")

    results, model = train_mlb_model(
        train_seasons=TRAIN_SEASONS,
        test_seasons=TEST_SEASONS,
        calibrate=True,
    )
    print(print_training_results(results))

    # Compare to Pythagorean baseline
    print("\nRunning Pythagorean backtest on 2025 for comparison...")
    from src.backtest.mlb_backtest import run_mlb_backtest, print_backtest_results
    pyth_results = run_mlb_backtest(seasons=[2025], verbose=False)
    print(print_backtest_results(pyth_results))

    tr = results.get("test_result")
    if tr and pyth_results:
        pyth_acc = pyth_results[0].accuracy
        xgb_acc = tr["accuracy"]
        print(f"\n  {'='*50}")
        print(f"  HEAD-TO-HEAD: 2025 SEASON ({tr['test_n']:,} games)")
        print(f"  {'='*50}")
        print(f"  Home baseline:        {tr['home_baseline']:.1%}")
        print(f"  Pythagorean model:    {pyth_acc:.1%}")
        print(f"  XGBoost (calibrated): {xgb_acc:.1%}")
        delta = xgb_acc - pyth_acc
        print(f"  XGB vs Pyth:          {delta*100:+.1f}%")
        if tr.get("confident_n", 0) > 0 and pyth_results[0].confident_games > 0:
            print(f"\n  HIGH-CONFIDENCE PICKS:")
            print(f"  Pythagorean: {pyth_results[0].confident_accuracy:.1%} "
                  f"({pyth_results[0].confident_games} games)")
            print(f"  XGBoost:     {tr['confident_accuracy']:.1%} "
                  f"({tr['confident_n']} games)")
        print(f"  {'='*50}\n")

    os.makedirs("output", exist_ok=True)
    # Save results (without non-serializable objects)
    safe_results = {k: v for k, v in results.items()
                    if k not in ("feature_importance", "cv_results")}
    pd.DataFrame([safe_results]).to_json(
        "output/mlb_xgboost_results.json", orient="records", indent=2
    )
    print("  Results saved to output/mlb_xgboost_results.json")


def run_totals_training(args):
    """Train the MLB over/under totals model."""
    from src.models.mlb_totals import train_totals_model

    print(f"\n{'='*70}")
    print("  MLB TOTALS MODEL TRAINING")
    print(f"{'='*70}\n")

    results = train_totals_model(verbose=True)
    if results:
        os.makedirs("output", exist_ok=True)
        safe = {k: v for k, v in results.items() if k not in ("cv_seasons",)}
        pd.DataFrame([safe]).to_json("output/mlb_totals_results.json",
                                     orient="records", indent=2)
        print("  Results saved to output/mlb_totals_results.json")


def run_mlb_backtest_cmd(args):
    """Run MLB historical backtest."""
    from src.backtest.mlb_backtest import run_mlb_backtest, print_backtest_results

    print(f"\n{'='*70}")
    print("  MLB MODEL BACKTESTING")
    print(f"{'='*70}\n")

    seasons = [2024, 2025]
    results = run_mlb_backtest(seasons=seasons, verbose=args.verbose)
    print(print_backtest_results(results))

    os.makedirs("output", exist_ok=True)
    rows = []
    for r in results:
        rows.append({
            "Season": r.season,
            "Games": r.total_games,
            "Accuracy": round(r.accuracy, 4),
            "HomeBaseline": round(r.always_home_accuracy, 4),
            "Lift": round(r.accuracy - r.always_home_accuracy, 4),
            "BrierScore": round(r.brier_score, 4),
            "ConfidentGames": r.confident_games,
            "ConfidentAccuracy": round(r.confident_accuracy, 4) if r.confident_games else 0,
        })
    pd.DataFrame(rows).to_csv("output/mlb_backtest_results.csv", index=False)
    print("  Results saved to output/mlb_backtest_results.csv")


def _resolve_sport(sport_alias: str) -> str:
    mapping = {
        "ncaab": "basketball_ncaab",
        "nba": "basketball_nba",
        "mlb": "baseball_mlb",
        "nfl": "americanfootball_nfl",
        "basketball_ncaab": "basketball_ncaab",
        "basketball_nba": "basketball_nba",
        "baseball_mlb": "baseball_mlb",
        "americanfootball_nfl": "americanfootball_nfl",
    }
    if sport_alias not in mapping:
        raise ValueError(
            "Invalid --sport. Use one of: ncaab, nba, mlb, nfl "
            "or full keys (basketball_ncaab, basketball_nba, baseball_mlb, americanfootball_nfl)."
        )
    return mapping[sport_alias]


def _build_market_predictions(raw_odds: pd.DataFrame) -> dict[tuple[str, str], float]:
    """
    Build fair-price win probabilities from sportsbook consensus (vig removed).
    This provides a sport-agnostic baseline prediction stream for daily content.
    """
    if raw_odds.empty:
        return {}

    predictions = {}
    for game_id in raw_odds["GameID"].dropna().unique():
        game = raw_odds[raw_odds["GameID"] == game_id].copy()
        if game.empty:
            continue
        if "HomeImpliedProb" not in game.columns or "AwayImpliedProb" not in game.columns:
            continue

        probs = game[["HomeImpliedProb", "AwayImpliedProb"]].dropna()
        if probs.empty:
            continue

        # Remove overround per bookmaker row, then aggregate median fair price.
        sums = probs["HomeImpliedProb"] + probs["AwayImpliedProb"]
        fair_home = (probs["HomeImpliedProb"] / sums.replace(0, np.nan)).dropna()
        if fair_home.empty:
            continue

        home = game["HomeTeamCanonical"].iloc[0] or game["HomeTeam"].iloc[0]
        away = game["AwayTeamCanonical"].iloc[0] or game["AwayTeam"].iloc[0]
        predictions[(home, away)] = float(fair_home.median())

    return predictions


def _rebook_to_tier1(picks_df: pd.DataFrame, raw_odds: pd.DataFrame) -> pd.DataFrame:
    """
    For any pick whose Sportsbook is NOT tier-1, replace it with the best
    available tier-1 book (DK/FD/BetMGM/BetRivers) for that game and side.
    If no tier-1 alternative exists, leave the pick unchanged.
    """
    from src.data.odds_api import TIER1_BOOKS

    if picks_df.empty or raw_odds.empty:
        return picks_df

    tier1 = raw_odds[raw_odds["Sportsbook"].isin(TIER1_BOOKS)]
    if tier1.empty:
        return picks_df

    result = picks_df.copy()
    for idx, row in result.iterrows():
        if str(row.get("Sportsbook", "")) in TIER1_BOOKS:
            continue

        mkt     = str(row.get("Market", "moneyline")).lower()
        game_id = str(row.get("GameID", "") or "")
        game_t1 = tier1[tier1["GameID"] == game_id] if game_id else pd.DataFrame()
        if game_t1.empty:
            continue

        if mkt == "moneyline":
            team = str(row.get("Team", "")).lower()
            home = str(game_t1["HomeTeamCanonical"].iloc[0] if "HomeTeamCanonical" in game_t1
                       else game_t1["HomeTeam"].iloc[0]).lower()
            is_home = team in home or home in team
            col = "HomeMoneyline" if is_home else "AwayMoneyline"
            if col not in game_t1.columns:
                continue
            valid = game_t1.dropna(subset=[col])
            if valid.empty:
                continue
            best = valid.loc[valid[col].idxmax()]
            result.at[idx, "BestOdds"]   = int(best[col])
            result.at[idx, "Sportsbook"] = best["Sportsbook"]

        elif mkt == "spread":
            team = str(row.get("Team", "")).lower()
            home = str(row.get("HomeTeam", "")).lower()
            is_home = team in home or home in team
            col = "HomeSpreadOdds" if is_home else "AwaySpreadOdds"
            if col not in game_t1.columns:
                continue
            valid = game_t1.dropna(subset=[col])
            if valid.empty:
                continue
            best = valid.loc[valid[col].idxmax()]
            result.at[idx, "BestOdds"]   = int(best[col])
            result.at[idx, "Sportsbook"] = best["Sportsbook"]

        elif mkt == "total":
            direction = str(row.get("Direction", "UNDER")).upper()
            col = "OverOdds" if direction == "OVER" else "UnderOdds"
            if col not in game_t1.columns:
                continue
            valid = game_t1.dropna(subset=[col])
            if valid.empty:
                continue
            best = valid.loc[valid[col].idxmax()]
            result.at[idx, "BestOdds"]   = int(best[col])
            result.at[idx, "Sportsbook"] = best["Sportsbook"]

    return result


def _run_mlb_daily(args, sport: str):
    """
    MLB daily pipeline using ensemble (Pythagorean + XGBoost) predictions:
      MLB Stats API → Ensemble model → odds comparison → edges → picks
    """
    from src.data.mlb_stats import get_todays_matchups
    from src.models.mlb_ensemble import predict_all_ensemble, ensemble_to_dict
    from src.models.mlb_model import predict_all_games, predictions_to_dict
    from src.models.mlb_xgboost import load_mlb_model

    from datetime import timedelta
    target_date = date.today() + timedelta(days=1) if getattr(args, "tomorrow", False) else None
    date_label = "tomorrow" if target_date else "today"

    print(f"Step 1: Fetching MLB schedule and team stats...")
    matchups = get_todays_matchups(game_date=target_date)
    if not matchups:
        print(f"  No MLB games found for {date_label}.")
        return

    print(f"  Found {len(matchups)} games")
    for m in matchups:
        hp = m.home_pitcher.name if m.home_pitcher else "TBD"
        ap = m.away_pitcher.name if m.away_pitcher else "TBD"
        print(f"    {m.away_team.name} ({ap}) @ {m.home_team.name} ({hp})")

    loaded = load_mlb_model()
    use_ensemble = loaded is not None
    if use_ensemble:
        n_models = len([m for m in loaded[2:5] if m is not None]) + 1
        print(f"\nStep 2: Running ensemble ({n_models} models + Pythagorean) — v6 features, 91 total...")
        ensemble_preds = predict_all_ensemble(matchups)
        for ep in ensemble_preds:
            fav = ep.home_team if ep.ensemble_prob >= 0.5 else ep.away_team
            prob = ep.ensemble_prob if ep.ensemble_prob >= 0.5 else 1 - ep.ensemble_prob
            agree = "AGREE" if ep.model_agreement else "SPLIT"
            print(f"  {ep.away_team} @ {ep.home_team}: {fav} {prob:.1%} [{agree}]")
            print(f"    Pyth: {ep.pyth_prob:.1%}  XGB: {ep.xgb_prob:.1%}  Ens: {ep.ensemble_prob:.1%}")
        predictions = ensemble_to_dict(ensemble_preds)
        why_lookup = {}
        fallback_rows = []
        for ep in ensemble_preds:
            why_lookup[(ep.home_team, ep.away_team)] = ep.edge_drivers[0] if ep.edge_drivers else ""
            fav = ep.home_team if ep.ensemble_prob >= 0.5 else ep.away_team
            opp = ep.away_team if ep.ensemble_prob >= 0.5 else ep.home_team
            prob = ep.ensemble_prob if ep.ensemble_prob >= 0.5 else 1 - ep.ensemble_prob
            fallback_rows.append({
                "Team": fav, "Opponent": opp,
                "ModelProb": prob, "ImpliedProb": None,
                "Edge": 0.0, "BestOdds": 0,
                "Why": ep.edge_drivers[0] if ep.edge_drivers else "",
            })
    else:
        print("\nStep 2: Running Pythagorean model (run --train-mlb to enable ensemble)...")
        game_preds = predict_all_games(matchups)
        for gp in game_preds:
            fav = gp.home_team if gp.home_win_prob >= 0.5 else gp.away_team
            prob = gp.home_win_prob if gp.home_win_prob >= 0.5 else 1 - gp.home_win_prob
            print(f"  {gp.away_team} @ {gp.home_team}: {fav} {prob:.1%}")
        predictions = predictions_to_dict(game_preds)
        why_lookup = {}
        fallback_rows = []
        for gp in game_preds:
            why_lookup[(gp.home_team, gp.away_team)] = gp.edge_drivers[0] if gp.edge_drivers else ""
            fav = gp.home_team if gp.home_win_prob >= 0.5 else gp.away_team
            opp = gp.away_team if gp.home_win_prob >= 0.5 else gp.home_team
            prob = gp.home_win_prob if gp.home_win_prob >= 0.5 else 1 - gp.home_win_prob
            fallback_rows.append({
                "Team": fav, "Opponent": opp,
                "ModelProb": prob, "ImpliedProb": None,
                "Edge": 0.0, "BestOdds": 0,
                "Why": gp.edge_drivers[0] if gp.edge_drivers else "",
            })

    print("\nStep 3: Fetching LIVE sportsbook odds...")
    # Daily mode always refreshes — stale odds break +EV and CLV tracking.
    raw_odds = odds_api.fetch_odds(refresh=True, sport=sport)
    if raw_odds.empty:
        print("  No odds data. Set ODDS_API_KEY for edge detection.")
        print("  Model predictions above are still useful for social content.")
        _save_picks(pd.DataFrame(fallback_rows), sport, args)
        return

    print(odds_api.odds_freshness_summary(raw_odds))

    markets = {m.strip().lower() for m in args.markets.split(",")}
    use_all = "all" in markets

    all_picks: list[pd.DataFrame] = []

    from src.data.odds_api import get_consensus_prob, TIER1_BOOKS

    # ── Moneyline (Method A — ML model) ──────────────────────────────────────
    if use_all or "moneyline" in markets:
        best_odds = odds_api.get_best_odds(raw_odds)
        ml_bets = find_value_bets(predictions, best_odds, min_edge=args.min_edge)
        if not ml_bets.empty:
            ml_bets = ml_bets.copy()
            ml_bets["Market"] = "moneyline"
            ml_bets["Method"] = "ML"
            ml_bets["Why"] = ml_bets.apply(
                lambda row: why_lookup.get(
                    (row.get("Team", ""), row.get("Opponent", "")),
                    why_lookup.get(
                        (row.get("Opponent", ""), row.get("Team", "")),
                        f"Model edge ({row['Edge']*100:.1f}%).",
                    ),
                ),
                axis=1,
            )
            if args.bankroll > 0:
                ml_bets = size_bets(ml_bets, bankroll=args.bankroll,
                                    kelly_fraction_pct=args.kelly_fraction)
                print(print_kelly_bets(ml_bets, args.bankroll))
            else:
                print(print_value_bets(ml_bets, args.bankroll))
            all_picks.append(ml_bets)

    # ── Moneyline (Method B — Sharp consensus de-vig) ─────────────────────────
    # De-vigs DK + FD + BetMGM to get the "true" probability, then compares it
    # to the best available price.  Picks where both methods agree = LOCK tier.
    consensus_probs_raw = get_consensus_prob(raw_odds)
    if consensus_probs_raw and (use_all or "moneyline" in markets):
        # flatten (home_p, away_p) → {(home, away): home_p} for find_value_bets
        consensus_probs = {k: v[0] for k, v in consensus_probs_raw.items()}
        # Use ALL books to detect line discrepancies (offshore may lag sharp consensus).
        # _rebook_to_tier1 will replace the recommended book with a tier-1 alternative.
        best_odds_all = odds_api.get_best_odds(raw_odds, all_books=True)
        consensus_bets = find_value_bets(consensus_probs, best_odds_all, min_edge=args.min_edge)
        if not consensus_bets.empty:
            consensus_bets = consensus_bets.copy()
            consensus_bets["Market"] = "moneyline"
            consensus_bets["Method"] = "Consensus"
            consensus_bets["Why"] = consensus_bets.apply(
                lambda row: why_lookup.get(
                    (row.get("Team", ""), row.get("Opponent", "")),
                    why_lookup.get(
                        (row.get("Opponent", ""), row.get("Team", "")),
                        "Sharp consensus edge.",
                    ),
                ),
                axis=1,
            )
            print(f"\n  Method B — Sharp consensus ({len(consensus_bets)} edges):")
            for _, b in consensus_bets.iterrows():
                print(f"    {b['Team']} vs {b['Opponent']}: "
                      f"Consensus {b['ModelProb']:.1%} → Edge +{b['Edge']*100:.1f}%")
            all_picks.append(consensus_bets)

    # ── Run Line (Spreads) ────────────────────────────────────────────────────
    if use_all or "spreads" in markets or "spread" in markets:
        from src.models.mlb_spreads import find_spread_edges
        spread_edges = find_spread_edges(predictions, raw_odds, min_edge_runs=0.4)
        if spread_edges:
            spread_rows = []
            for e in spread_edges:
                why = why_lookup.get((e["home_team"], e["away_team"]),
                                     why_lookup.get((e["away_team"], e["home_team"]), ""))
                # Use separate team/opponent/line fields (not combined direction string)
                away_at_home = f"{e['away_team']} @ {e['home_team']}"
                # BetLine = the spread for the team we're betting on.
                # If team is home: their spread = market_spread (e.g. -1.5 for home fav).
                # If team is away: their spread = -market_spread (e.g. +1.5 for away dog).
                is_home_bet = (e["team"] == e["home_team"])
                bet_line_val = e["market_spread"] if is_home_bet else -e["market_spread"]
                spread_rows.append({
                    "Team": e["team"],
                    "BetLine": f"{bet_line_val:+.1f}",
                    "Opponent": e["opponent"],
                    "Matchup": away_at_home,
                    "Market": "spread",
                    "ModelProb": e["model_prob"],
                    "ImpliedProb": 0.5,
                    "Edge": e["edge_runs"],
                    "BestOdds": e["best_odds"],
                    "Sportsbook": e["sportsbook"],
                    "ModelMargin": e["model_margin"],
                    "MarketSpread": e["market_spread"],
                    "Why": why,
                    "GameID": e.get("game_id", ""),
                    "HomeTeam": e["home_team"],
                })
            all_picks.append(pd.DataFrame(spread_rows))

    # ── Totals (Over/Under) ───────────────────────────────────────────────────
    if use_all or "totals" in markets or "total" in markets:
        from src.models.mlb_totals import find_totals_edges
        totals_edges = find_totals_edges(matchups, raw_odds, min_edge_runs=1.5)
        if totals_edges:
            totals_rows = []
            for e in totals_edges:
                matchup = f"{e['away_team']} @ {e['home_team']}"
                totals_rows.append({
                    "Team": f"{e['direction']} {e['market_line']}",
                    "BetLine": str(e["market_line"]),
                    "Opponent": matchup,
                    "Matchup": matchup,
                    "Market": "total",
                    "ModelProb": e.get("model_prob", 0.0),
                    "ImpliedProb": 0.5,
                    "Edge": e["edge_runs"],
                    "BestOdds": e["best_odds"],
                    "Sportsbook": e["sportsbook"],
                    "PredictedTotal": e["predicted_total"],
                    "MarketLine": e["market_line"],
                    "Direction": e["direction"],
                    "Why": "",
                    "GameID": e.get("game_id", ""),
                    "HomeTeam": e.get("home_team", ""),
                })
            all_picks.append(pd.DataFrame(totals_rows))

    if not all_picks:
        print("  No edges above threshold across any market today.")
        _save_picks(pd.DataFrame(fallback_rows), sport, args)
        return

    combined = pd.concat(all_picks, ignore_index=True)

    # Fill Method for any rows that didn't get tagged (spread/totals)
    if "Method" not in combined.columns:
        combined["Method"] = "ML"
    else:
        combined["Method"] = combined["Method"].where(combined["Method"].notna(), "ML")

    # Detect "Both" — same team flagged by ML model AND sharp consensus.
    # These are the highest-confidence picks (two independent methods agree).
    ml_teams: set[str] = set()
    for _, row in combined[combined["Method"] == "ML"].iterrows():
        if str(row.get("Market", "moneyline")).lower() == "moneyline":
            ml_teams.add(str(row.get("Team", "")).lower().strip())

    def _tag_both(row):
        m = str(row.get("Method", "ML"))
        if m == "Consensus" and str(row.get("Market", "moneyline")).lower() == "moneyline":
            if str(row.get("Team", "")).lower().strip() in ml_teams:
                return "Both"
        return m

    combined["Method"] = combined.apply(_tag_both, axis=1)

    # Also upgrade the ML side of a "Both" pair
    both_teams: set[str] = set()
    for _, row in combined[combined["Method"] == "Both"].iterrows():
        both_teams.add(str(row.get("Team", "")).lower().strip())

    def _upgrade_ml(row):
        m = str(row.get("Method", "ML"))
        if m == "ML" and str(row.get("Market", "moneyline")).lower() == "moneyline":
            if str(row.get("Team", "")).lower().strip() in both_teams:
                return "Both"
        return m

    combined["Method"] = combined.apply(_upgrade_ml, axis=1)

    if both_teams:
        print(f"\n  LOCK picks (both methods agree): {', '.join(sorted(both_teams))}")

    # Attach model agreement signal to spread/total rows.
    if use_ensemble:
        _agree = {ep.home_team.lower(): ep.model_agreement for ep in ensemble_preds}
        _agree.update({ep.away_team.lower(): ep.model_agreement for ep in ensemble_preds})
        def _agreement(row):
            if str(row.get("Market", "moneyline")).lower() == "moneyline":
                return row.get("ModelAgreement", True)
            team = str(row.get("Team", "")).lower()
            if str(row.get("Market", "")).lower() == "total":
                opp = str(row.get("Opponent", "")).lower()
                parts = [p.strip() for p in opp.replace(" @ ", "@").split("@")]
                for part in parts:
                    for k, v in _agree.items():
                        if k in part or part in k:
                            return v
                return True
            for k, v in _agree.items():
                if k in team or team in k:
                    return v
            return True
        combined["ModelAgreement"] = combined.apply(_agreement, axis=1)

    # ── Filter offshore books → tier-1 alternatives ───────────────────────────
    # We use ALL books to find edges, but only recommend tier-1 books to followers.
    combined = _rebook_to_tier1(combined, raw_odds)

    # Sort by normalized edge: 1 run ≈ 10% ML.
    # "Both" picks get +30% bonus, "Consensus" get +15%. SPLIT picks penalized 40%.
    def _norm_edge(row):
        mkt = str(row.get("Market", "moneyline")).lower()
        edge = float(row.get("Edge", 0) or 0)
        score = edge if mkt == "moneyline" else edge * 0.05
        method = str(row.get("Method", "ML"))
        if method == "Both":
            score *= 1.30
        elif method == "Consensus":
            score *= 1.15
        if not row.get("ModelAgreement", True):
            score *= 0.60
        return score

    combined["_norm"] = combined.apply(_norm_edge, axis=1)
    combined = combined.sort_values("_norm", ascending=False)

    # Deduplicate: keep only the highest-ranked pick per game.
    # With dedup, a "Both" ML+Consensus duplicate collapses to a single top pick.
    seen_games: set[frozenset] = set()
    dedup_rows = []
    for _, row in combined.iterrows():
        team = str(row.get("Team", "")).lower().strip()
        opp  = str(row.get("Opponent", "")).lower().strip()
        _raw_m = row.get("Matchup")
        matchup_str = "" if (pd.isna(_raw_m) if _raw_m is not None else False) else str(_raw_m or "").lower().strip()
        if matchup_str:
            parts = [p.strip() for p in matchup_str.replace(" @ ", "@").split("@")]
            game_key = frozenset(p for p in parts if p)
        else:
            game_key = frozenset([team, opp])
        if game_key not in seen_games:
            seen_games.add(game_key)
            dedup_rows.append(row)

    combined = pd.DataFrame(dedup_rows).drop(columns=["_norm"]).reset_index(drop=True)

    # Guard: drop any pick whose line has already been pulled by books.
    # Books pull moneylines when a game goes live — these can't be bet.
    live_teams: set[str] = set()
    for _, odds_row in odds_api.get_best_odds(raw_odds).iterrows():
        live_teams.add(str(odds_row.get("HomeTeam", "")).lower().strip())
        live_teams.add(str(odds_row.get("AwayTeam", "")).lower().strip())

    def _line_still_live(row) -> bool:
        mkt = str(row.get("Market", "moneyline")).lower()
        if mkt not in ("moneyline",):
            return True   # spread/totals lines checked separately
        team = str(row.get("Team", "")).lower().strip()
        if team and team not in live_teams:
            print(f"  ⚠ Line pulled for {row.get('Team')} — game may have started. Dropping from card.")
            return False
        return True

    before = len(combined)
    combined = combined[combined.apply(_line_still_live, axis=1)].reset_index(drop=True)
    if len(combined) < before:
        print(f"  ({before - len(combined)} pick(s) removed — lines no longer available)")

    _print_daily_summary(combined, sport, target_date=target_date)
    _save_picks(combined, sport, args, ensemble_preds=ensemble_preds if use_ensemble else None, raw_odds=raw_odds)

    # ── Player props ──────────────────────────────────────────────────────────
    try:
        from src.data.player_props import find_prop_edges, format_props_for_card
        print("\nStep 6: Scanning player props for edges...")
        # Build matchup stats dicts for the prop engine
        prop_matchup_inputs = []
        for ep in (ensemble_preds if use_ensemble else []):
            m_obj = next(
                (m for m in matchups
                 if m.home_team.name == ep.home_team and m.away_team.name == ep.away_team),
                None,
            )
            if not m_obj:
                continue
            prop_matchup_inputs.append({
                "event_id": None,  # looked up by team name in find_prop_edges
                "home_team": ep.home_team,
                "away_team": ep.away_team,
                "home_sp_name": m_obj.home_pitcher.name if m_obj.home_pitcher else "",
                "home_sp_k9": m_obj.home_pitcher.k_per_9 if m_obj.home_pitcher else 7.5,
                "home_sp_k9_l10": m_obj.home_pitcher.k_per_9 if m_obj.home_pitcher else 7.5,
                "away_sp_name": m_obj.away_pitcher.name if m_obj.away_pitcher else "",
                "away_sp_k9": m_obj.away_pitcher.k_per_9 if m_obj.away_pitcher else 7.5,
                "away_sp_k9_l10": m_obj.away_pitcher.k_per_9 if m_obj.away_pitcher else 7.5,
                "home_lineup_ops": 0.720,
                "away_lineup_ops": 0.720,
            })

        prop_edges = find_prop_edges(prop_matchup_inputs, game_date=target_date)
        if prop_edges:
            print(f"  Found {len(prop_edges)} prop edge(s):")
            for pe in prop_edges[:10]:
                print(f"    {pe['label']}  edge={pe['edge_pct']}%  odds={pe['odds']:+d}  [{pe['book']}]")
            # Save props to output
            import json as _json
            _game_date = target_date or date.today()
            ts = _game_date.strftime("%Y%m%d")
            props_dir = Path("output/picks") / sport / ts
            props_dir.mkdir(parents=True, exist_ok=True)
            (props_dir / "props.json").write_text(_json.dumps(prop_edges, indent=2))
            print(f"  Props saved → output/picks/{sport}/{ts}/props.json")
            # Render props card image
            try:
                from src.output.card_html import render_props_card_html
                props_img = render_props_card_html(prop_edges[:10], sport=sport, card_date=_game_date)
                if props_img:
                    print(f"  Props card → {props_img}")
            except Exception as _pci:
                print(f"  [props card] {_pci}")
            # Props caption
            try:
                from src.output.captions import props_caption
                pcap = props_caption(prop_edges[:10], card_date=_game_date)
                _pcap_path = props_dir / "caption_props.txt"
                _pcap_path.write_text(pcap, encoding="utf-8")
                print(f"  Props caption → {_pcap_path}")
            except Exception as _pce:
                print(f"  [props caption] {_pce}")
        else:
            print("  No prop edges found (no ODDS_API_KEY, or no lines posted yet).")
    except Exception as _prop_err:
        print(f"  [props] Skipped: {_prop_err}")

    # ── NRFI / YRFI ──────────────────────────────────────────────────────────
    try:
        from src.data.nrfi import find_nrfi_edges
        print("\nStep 7: Building NRFI/YRFI plays...")
        nrfi_inputs = []
        for ep in (ensemble_preds if use_ensemble else []):
            m_obj = next(
                (m for m in matchups
                 if m.home_team.name == ep.home_team and m.away_team.name == ep.away_team),
                None,
            )
            if not m_obj:
                continue
            nrfi_inputs.append({
                "home_team": ep.home_team,
                "away_team": ep.away_team,
                "home_sp_name": m_obj.home_pitcher.name if m_obj.home_pitcher else "TBD",
                "home_sp_era":  m_obj.home_pitcher.era  if m_obj.home_pitcher else 4.20,
                "home_sp_k9":   m_obj.home_pitcher.k_per_9 if m_obj.home_pitcher else 8.5,
                "away_sp_name": m_obj.away_pitcher.name if m_obj.away_pitcher else "TBD",
                "away_sp_era":  m_obj.away_pitcher.era  if m_obj.away_pitcher else 4.20,
                "away_sp_k9":   m_obj.away_pitcher.k_per_9 if m_obj.away_pitcher else 8.5,
            })
        nrfi_plays = find_nrfi_edges(nrfi_inputs, game_date=target_date)
        if nrfi_plays:
            print(f"  Found {len(nrfi_plays)} NRFI/YRFI play(s):")
            for np_ in nrfi_plays[:5]:
                edge_info = f"edge={np_['edge_pct']}%" if np_["edge_pct"] else f"proj {np_['projected_nrfi']*100:.0f}% NRFI"
                print(f"    {np_['label']}  {edge_info}")
            # Save JSON
            import json as _json
            _game_date = target_date or date.today()
            ts = _game_date.strftime("%Y%m%d")
            nrfi_dir = Path("output/picks") / sport / ts
            nrfi_dir.mkdir(parents=True, exist_ok=True)
            (nrfi_dir / "nrfi.json").write_text(_json.dumps(nrfi_plays, indent=2))
            # Log NRFI picks to pnl tracker (graded tonight by --grade)
            try:
                from src.grading.auto_grade import _update_pnl_nrfi
                _update_pnl_nrfi(nrfi_plays[:5], [], _game_date)
                print(f"  NRFI picks logged to pnl ({len(nrfi_plays[:5])} picks)")
            except Exception as _pnl_err:
                print(f"  [nrfi pnl] {_pnl_err}")
            # Render card
            try:
                from src.output.card_html import render_nrfi_card_html
                nrfi_img = render_nrfi_card_html(nrfi_plays[:5], sport=sport, card_date=_game_date)
                if nrfi_img:
                    print(f"  NRFI card → {nrfi_img}")
            except Exception as _nci:
                print(f"  [nrfi card] {_nci}")
            # Caption
            try:
                from src.output.captions import nrfi_caption
                ncap = nrfi_caption(nrfi_plays[:5], card_date=_game_date)
                (nrfi_dir / "caption_nrfi.txt").write_text(ncap, encoding="utf-8")
                print(f"  NRFI caption → {nrfi_dir}/caption_nrfi.txt")
            except Exception as _nce:
                print(f"  [nrfi caption] {_nce}")
        else:
            print("  No NRFI plays generated.")
    except Exception as _nrfi_err:
        print(f"  [nrfi] Skipped: {_nrfi_err}")



def _save_model_only_picks(game_preds, sport: str, args):
    """Save model predictions even when no odds are available."""
    rows = []
    for gp in game_preds:
        if gp.home_win_prob >= 0.5:
            rows.append({
                "Team": gp.home_team, "Opponent": gp.away_team,
                "ModelProb": gp.home_win_prob, "ImpliedProb": None,
                "Edge": 0.0, "BestOdds": 0, "Why": gp.edge_drivers[0] if gp.edge_drivers else "",
            })
        else:
            rows.append({
                "Team": gp.away_team, "Opponent": gp.home_team,
                "ModelProb": 1 - gp.home_win_prob, "ImpliedProb": None,
                "Edge": 0.0, "BestOdds": 0, "Why": gp.edge_drivers[0] if gp.edge_drivers else "",
            })
    import pandas as _pd
    _save_picks(_pd.DataFrame(rows), sport, args)


def _kelly_pct(model_prob: float, american_odds: float, fraction: float = 0.25) -> float:
    """Fractional Kelly bet size as a fraction of bankroll (default 25% Kelly)."""
    if not model_prob or model_prob <= 0 or not american_odds or american_odds == 0:
        return 0.0
    if american_odds > 0:
        b = american_odds / 100.0
    else:
        b = 100.0 / abs(american_odds)
    p = model_prob
    q = 1.0 - p
    kelly = (b * p - q) / b
    if kelly <= 0:
        return 0.0
    return min(kelly * fraction, 0.10)  # cap at 10% of bankroll


def _print_daily_summary(picks_df: pd.DataFrame, sport: str, target_date=None) -> None:
    """Print a clean, ranked 'TODAY'S PLAYS' table — the only thing you need to read."""
    from datetime import date as _date, timedelta

    W = 70
    label = sport.replace("baseball_", "").replace("basketball_", "").replace("americanfootball_", "").upper()
    game_date = target_date or _date.today()
    date_label = game_date.strftime("%B %d, %Y")
    header_prefix = "TOMORROW'S" if target_date and target_date > _date.today() else "TODAY'S"

    print(f"\n{'═'*W}")
    print(f"  {header_prefix} TOP PLAYS — {label} · {date_label}")
    print(f"{'═'*W}\n")

    if picks_df.empty:
        print("  No plays today.\n")
        return

    # Sort: moneyline by edge%, spreads/totals by edge runs — normalize to rank.
    # 1 run of edge on a totals/spread bet ≈ 10% ML equivalent (makes them
    # compete fairly: a 0.5R edge = 5%, a 1.0R edge = 10%).
    def sort_key(row):
        mkt = str(row.get("Market", "moneyline")).lower()
        edge = float(row.get("Edge", 0) or 0)
        return edge if mkt == "moneyline" else edge * 0.10

    picks_sorted = picks_df.copy()
    picks_sorted["_sort"] = picks_sorted.apply(sort_key, axis=1)
    picks_sorted = picks_sorted.sort_values("_sort", ascending=False).head(8).drop(columns=["_sort"])

    # Table header
    print(f"  {'#':<3} {'MARKET':<10} {'BET':<30} {'ODDS':>6}  {'EDGE':>8}  {'KELLY':>7}  BOOK")
    print(f"  {'─'*72}")

    ml_count = sp_count = to_count = 0
    for i, (_, row) in enumerate(picks_sorted.iterrows(), 1):
        mkt    = str(row.get("Market", "moneyline")).lower()
        team   = str(row.get("Team", ""))
        edge   = float(row.get("Edge", 0) or 0)
        _raw_odds = row.get("BestOdds", 0)
        odds   = int(_raw_odds) if _raw_odds is not None and str(_raw_odds) not in ("nan", "NaN", "") else 0
        book   = str(row.get("Sportsbook", "") or "")[:10]
        model_prob = float(row.get("ModelProb", 0) or 0)

        if mkt == "moneyline":
            ml_count += 1
            bet_str  = f"{team[:26]} ML"
            edge_str = f"+{edge*100:.1f}%"
        elif mkt == "spread":
            sp_count += 1
            line     = str(row.get("BetLine", ""))
            bet_str  = f"{team[:20]} {line} RL"
            edge_str = f"+{edge:.2f}R"
        else:
            to_count += 1
            matchup  = str(row.get("Matchup", row.get("Opponent", "")) or "")
            # Show "UNDER 10.5 (NYY@BOS)" — keep short
            teams_short = matchup.replace(" @ ", "@")
            parts = [p.split()[-1] for p in teams_short.split("@")]  # last word = city/nickname
            game_tag  = "@".join(parts)[:16] if len(parts) == 2 else matchup[:16]
            bet_str   = f"{team[:12]} ({game_tag})"
            edge_str  = f"+{edge:.2f}R"

        mkt_label = {"moneyline": "MONEYLINE", "spread": "RUN LINE", "total": "TOTAL"}.get(mkt, mkt.upper())
        odds_str  = f"{odds:+d}" if odds else "  N/A"

        kelly = _kelly_pct(model_prob, odds) if mkt == "moneyline" and odds != 0 else 0.0
        kelly_str = f"{kelly*100:.1f}%" if kelly > 0 else "   —"

        print(f"  {i:<3} {mkt_label:<10} {bet_str:<30} {odds_str:>6}  {edge_str:>8}  {kelly_str:>7}  {book}")

    print(f"\n  {'─'*72}")

    # Best bet callout
    top = picks_sorted.iloc[0]
    top_mkt  = str(top.get("Market", "moneyline")).lower()
    top_team = str(top.get("Team", ""))
    top_odds = int(top.get("BestOdds", 0) or 0)
    top_book = str(top.get("Sportsbook", "") or "")
    top_edge = float(top.get("Edge", 0) or 0)
    top_prob = float(top.get("ModelProb", 0) or 0)

    if top_mkt == "moneyline":
        top_edge_str = f"{top_edge*100:.1f}% ML edge"
        top_bet_str  = f"{top_team} ML {top_odds:+d} @ {top_book}"
    elif top_mkt == "spread":
        top_line = str(top.get("BetLine", ""))
        top_edge_str = f"{top_edge:.2f} run RL edge"
        top_bet_str  = f"{top_team} {top_line} {top_odds:+d} @ {top_book}"
    else:
        top_edge_str = f"{top_edge:.2f} run totals edge"
        top_bet_str  = f"{top_team} {top_odds:+d} @ {top_book}"

    print(f"\n  ⚡ BEST BET: {top_bet_str}")
    print(f"     {top_edge_str}")

    # Kelly sizing for the best bet (moneyline only)
    if top_mkt == "moneyline" and top_odds != 0 and top_prob > 0:
        top_kelly = _kelly_pct(top_prob, top_odds)
        if top_kelly > 0:
            print(f"     Kelly: {top_kelly*100:.1f}% of bankroll  "
                  f"($50 → ${top_kelly*50:.2f}/bet  |  $200 → ${top_kelly*200:.2f}/bet)")

    totals_str = f"  Moneyline: {ml_count}  |  Run Line: {sp_count}  |  Totals: {to_count}"
    print(f"\n{totals_str}")
    print(f"{'═'*W}\n")


_PNL_FILE = Path("data/pnl/picks.json")


def _auto_log_picks(picks_list: list[dict], game_date: date | None = None) -> int:
    """
    Auto-log generated picks to data/pnl/picks.json using canonical schema.
    Deduplicates on pick_id. Returns count of new picks added.

    game_date: the actual game date — critical when picks are generated a day
    in advance (--tomorrow) or grading runs the morning after.
    """
    from src.tracking.schema import make_pick_id

    _PNL_FILE.parent.mkdir(parents=True, exist_ok=True)

    if _PNL_FILE.exists():
        try:
            existing = json.loads(_PNL_FILE.read_text())
            if "picks" not in existing:
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            existing = {"picks": []}
    else:
        existing = {"picks": []}

    today  = (game_date or date.today()).isoformat()
    now_ts = datetime.now(tz=timezone.utc).isoformat()

    # Dedup on pick_id — robust against all field variations
    existing_ids = {p.get("pick_id", "") for p in existing["picks"]}

    added = 0
    for rank, pick in enumerate(picks_list):
        team = str(pick.get("Team", "")).strip()
        if not team:
            continue

        market    = str(pick.get("Market", "moneyline")).lower().strip()
        direction = str(pick.get("Direction", "")).upper().strip()
        if not direction:
            direction = "WIN" if market == "moneyline" else "COVER" if market == "spread" else "OVER"

        pick_id = make_pick_id("mlb", today, team, market, direction)
        if pick_id in existing_ids:
            continue

        odds_raw  = pick.get("BestOdds", 0) or 0
        try:
            odds = int(float(odds_raw))
        except (ValueError, TypeError):
            odds = None

        # Extract line for spread/total picks
        line: float | None = None
        if market in ("spread", "total"):
            try:
                line = float(pick.get("BetLine") or pick.get("MarketLine") or 0) or None
            except (ValueError, TypeError):
                line = None

        matchup  = str(pick.get("Matchup", "") or pick.get("Opponent", "")).strip()
        edge_raw = pick.get("Edge")
        try:
            edge_pct = float(edge_raw) if edge_raw is not None else None
        except (ValueError, TypeError):
            edge_pct = None

        card_pick = rank < 5
        # ModelAgreement: True = Pythagorean + XGBoost both agree on direction
        agreement = pick.get("ModelAgreement")
        if agreement is None:
            agreement = pick.get("model_agreement")
        entry = {
            "pick_id":          pick_id,
            "date":             today,
            "sport":            "mlb",
            "market":           market,
            "direction":        direction,
            "team":             team,
            "matchup":          matchup,
            "odds":             odds,
            "line":             line,
            "sportsbook":       pick.get("Sportsbook"),
            "model_prob":       pick.get("ModelProb"),
            "edge_pct":         edge_pct,
            "model_agreement":  bool(agreement) if agreement is not None else None,
            "stake":            1.0 if card_pick else 0.0,
            "card_pick":        card_pick,
            "result":           None,
            "profit":           None,
            "recorded_at":      now_ts,
            "resulted_at":      None,
        }
        existing["picks"].append(entry)
        existing_ids.add(pick_id)
        added += 1

    if added > 0:
        _PNL_FILE.write_text(json.dumps(existing, indent=2))

    return added


def _save_picks(value_bets, sport: str, args, ensemble_preds=None, raw_odds=None):
    """Write pick cards (JSON + text + images) to output/picks/."""
    # Use game date (not UTC now) so --tomorrow picks land in the correct folder.
    from datetime import timedelta as _td
    _game_date = date.today() + _td(days=1) if getattr(args, "tomorrow", False) else date.today()
    ts = _game_date.strftime("%Y%m%d")
    out_dir = Path("output/picks") / sport / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    picks_json = out_dir / "picks.json"
    # Stamp each pick with the exact time odds were locked in — required for CLV calc.
    fetched_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    picks_with_ts = value_bets.copy()
    picks_with_ts["OddsLockedAt"] = fetched_at
    picks_with_ts.to_json(picks_json, orient="records", indent=2)

    # Freeze opening lines for CLV tracking — must happen right after saving picks
    # so odds are locked at the exact time we generated picks.
    try:
        from src.analytics.clv_tracker import snapshot_opening_lines
        n_snapped = snapshot_opening_lines(
            picks_json_path=str(picks_json),
            sport=sport,
            game_date=_game_date,
        )
        if n_snapped > 0:
            print(f"  [CLV] Snapshotted opening lines for {n_snapped} pick(s) [{_game_date}]")
    except Exception as _clv_err:
        print(f"  [CLV] Opening-line snapshot failed: {_clv_err}")

    picks_list = value_bets.to_dict(orient="records")

    # Inject kelly_pct into each pick (25% fractional Kelly, moneyline only)
    for pick in picks_list:
        prob = float(pick.get("ModelProb") or 0)
        odds = int(pick.get("BestOdds") or 0)
        mkt  = str(pick.get("Market", "moneyline")).lower()
        pick["kelly_pct"] = round(_kelly_pct(prob, odds) * 100, 2) if mkt == "moneyline" and odds != 0 else 0.0

    text = generate_pick_card_text(picks_list, sport=sport, card_date=_game_date)
    (out_dir / "picks.md").write_text(text, encoding="utf-8")

    # Save picks_card.json — top 5 moneyline picks only (no spreads/totals on the card).
    # Grader reads this instead of picks.json so they always match.
    import json as _json
    card_picks = [p for p in picks_list if str(p.get("Market", "moneyline")).lower() == "moneyline"][:5]
    if not card_picks:
        card_picks = picks_list[:5]  # fallback: no ML edges today, show whatever we have
    (out_dir / "picks_card.json").write_text(_json.dumps(card_picks, indent=2, default=str))

    # ── Moneyline card — always generate, fall back to top model confidence picks ─
    ml_edge_picks = [p for p in picks_list if str(p.get("Market", "moneyline")).lower() == "moneyline"]
    if ml_edge_picks:
        ml_card_picks = ml_edge_picks
    elif ensemble_preds:
        # No ML edges today — show top 5 by model confidence with real current odds
        sorted_eps = sorted(ensemble_preds, key=lambda ep: max(ep.ensemble_prob, 1 - ep.ensemble_prob), reverse=True)
        ml_card_picks = []

        # Build odds lookup: team name (lower) → (best_odds, book)
        odds_lookup: dict[str, tuple[int, str]] = {}
        if raw_odds is not None and not raw_odds.empty:
            try:
                from src.data.odds_api import get_best_odds as _gbo
                _best = _gbo(raw_odds)
                for _, _row in _best.iterrows():
                    ht = str(_row.get("HomeTeam", "")).lower()
                    at = str(_row.get("AwayTeam", "")).lower()
                    ho = _row.get("BestHomeML")
                    ao = _row.get("BestAwayML")
                    hb = _row.get("BestHomeSportsbook", "")
                    ab = _row.get("BestAwaySportsbook", "")
                    if ho and not pd.isna(ho):
                        odds_lookup[ht] = (int(ho), str(hb))
                    if ao and not pd.isna(ao):
                        odds_lookup[at] = (int(ao), str(ab))
            except Exception:
                pass

        for ep in sorted_eps[:5]:
            fav  = ep.home_team if ep.ensemble_prob >= 0.5 else ep.away_team
            opp  = ep.away_team if ep.ensemble_prob >= 0.5 else ep.home_team
            prob = ep.ensemble_prob if ep.ensemble_prob >= 0.5 else 1 - ep.ensemble_prob
            best_odds, book = odds_lookup.get(fav.lower(), (0, ""))
            ml_card_picks.append({
                "Team": fav, "Opponent": opp,
                "Market": "moneyline",
                "ModelProb": round(prob, 3),
                "ImpliedProb": 0.5,
                "Edge": round(prob - 0.5, 3),
                "BestOdds": best_odds,
                "Sportsbook": book,
                "Why": ep.edge_drivers[0] if ep.edge_drivers else "",
            })
    else:
        ml_card_picks = picks_list[:5]

    img_path = generate_pick_card_image(ml_card_picks, sport=sport, card_date=_game_date)
    if img_path:
        print(f"  Moneyline card → {img_path}")

    # ── Run Line card — always generate, fall back to model top plays ─────────
    spread_picks = [p for p in picks_list if str(p.get("Market", "")).lower() == "spread"]
    if not spread_picks and ensemble_preds and raw_odds is not None and not raw_odds.empty:
        try:
            from src.data.odds_api import get_best_odds as _gbo
            _spread_best = _gbo(raw_odds, market="spreads")
            # Build lookup: home_team_lower → spread row
            _sp_lookup = {}
            for _, _sr in _spread_best.iterrows():
                _sp_lookup[str(_sr.get("HomeTeam","")).lower()] = _sr
                _sp_lookup[str(_sr.get("AwayTeam","")).lower()] = _sr
            sorted_eps = sorted(ensemble_preds, key=lambda ep: max(ep.ensemble_prob, 1 - ep.ensemble_prob), reverse=True)
            for ep in sorted_eps[:5]:
                fav  = ep.home_team if ep.ensemble_prob >= 0.5 else ep.away_team
                opp  = ep.away_team if ep.ensemble_prob >= 0.5 else ep.home_team
                prob = ep.ensemble_prob if ep.ensemble_prob >= 0.5 else 1 - ep.ensemble_prob
                _sr  = _sp_lookup.get(fav.lower())
                if _sr is None:
                    continue
                is_home = fav.lower() == str(_sr.get("HomeTeam","")).lower()
                if is_home:
                    bet_line = float(_sr.get("HomeSpread", -1.5) or -1.5)
                    odds     = int(_sr.get("BestHomeSpreadOdds", -110) or -110)
                    book     = str(_sr.get("BestHomeSpreadBook", "") or "")
                else:
                    bet_line = float(_sr.get("AwaySpread", 1.5) or 1.5)
                    odds     = int(_sr.get("BestAwaySpreadOdds", -110) or -110)
                    book     = str(_sr.get("BestAwaySpreadBook", "") or "")
                spread_picks.append({
                    "Team": fav, "Opponent": opp,
                    "BetLine": f"{bet_line:+.1f}",
                    "Market": "spread",
                    "ModelProb": round(prob, 3),
                    "Edge": round(prob - 0.5, 3),
                    "BestOdds": odds,
                    "Sportsbook": book,
                    "Matchup": f"{ep.away_team} @ {ep.home_team}",
                })
        except Exception as _spe:
            print(f"  [run line fallback] {_spe}")

    if spread_picks:
        try:
            from src.output.card_html import render_runline_card_html
            rl_path = render_runline_card_html(spread_picks[:5], sport=sport, card_date=_game_date)
            if rl_path:
                print(f"  Run line card → {rl_path}")
        except Exception as _e:
            print(f"  [run line card] {_e}")
        try:
            from src.output.captions import picks_caption
            rl_cap = picks_caption(spread_picks[:5], card_date=_game_date)
            (out_dir / "caption_runline.txt").write_text(rl_cap, encoding="utf-8")
        except Exception:
            pass

    # ── Totals card (over/under picks) ────────────────────────────────────────
    totals_picks = [p for p in picks_list if str(p.get("Market", "")).lower() == "total"]
    if totals_picks:
        try:
            from src.output.card_html import render_totals_card_html
            ou_path = render_totals_card_html(totals_picks[:5], sport=sport, card_date=_game_date)
            if ou_path:
                print(f"  Totals card → {ou_path}")
        except Exception as _e:
            print(f"  [totals card] {_e}")
        try:
            from src.output.captions import picks_caption
            ou_cap = picks_caption(totals_picks[:5], card_date=_game_date)
            (out_dir / "caption_totals.txt").write_text(ou_cap, encoding="utf-8")
        except Exception:
            pass

    # ── Instagram captions ────────────────────────────────────────────────────
    ml_picks = [p for p in picks_list if str(p.get("Market", "moneyline")).lower() == "moneyline"]
    card_picks_for_caption = ml_picks[:5] if ml_picks else picks_list[:5]  # fallback to best picks
    try:
        from src.output.captions import picks_caption
        caption = picks_caption(card_picks_for_caption, card_date=_game_date)
        caption_path = out_dir / "caption_picks.txt"
        caption_path.write_text(caption, encoding="utf-8")
        print(f"  Picks caption → {caption_path}")
    except Exception as _e:
        print(f"  [captions] {_e}")

    # ── Pick of the Day card ──────────────────────────────────────────────────
    try:
        from src.output.card_html import render_pick_of_day_card_html
        ml_picks_for_pod = [p for p in picks_list if str(p.get("Market", "moneyline")).lower() == "moneyline"]
        best_pick = max(ml_picks_for_pod, key=lambda x: float(x.get("Edge") or 0)) if ml_picks_for_pod else (picks_list[0] if picks_list else None)
        if best_pick:
            pod_path = render_pick_of_day_card_html(best_pick, sport=sport, card_date=_game_date)
            if pod_path:
                print(f"  Pick of day card → {pod_path}")
    except Exception as _pod_err:
        print(f"  [pick of day card] {_pod_err}")

    # ── Slate card (all picks overview) ───────────────────────────────────────
    try:
        from src.output.card_html import render_slate_card_html
        slate_picks = []
        for p in picks_list[:5]:
            mkt = str(p.get("Market", "moneyline")).lower()
            slate_picks.append({"type": mkt, "team": p.get("Team", ""), "opponent": p.get("Opponent", ""),
                                 "odds": p.get("BestOdds", 0), "edge": p.get("Edge", 0),
                                 "book": p.get("Sportsbook", ""), "label": p.get("Team", "")})
        if slate_picks:
            slate_path = render_slate_card_html(slate_picks, sport=sport, card_date=_game_date)
            if slate_path:
                print(f"  Slate card → {slate_path}")
    except Exception as _slate_err:
        print(f"  [slate card] {_slate_err}")

    # Auto-log picks to pnl tracker — pass game_date so grading matches the right entries
    n_logged = _auto_log_picks(picks_list, game_date=_game_date)
    if n_logged > 0:
        print(f"  Auto-logged {n_logged} pick(s) to {_PNL_FILE}")
    elif picks_list:
        print(f"  (All picks already in {_PNL_FILE} — skipped duplicates)")

    print(f"\nSaved picks to {out_dir}/")


def run_close_snapshot(args):
    """
    Fetch current odds and save them as the closing-line snapshot for CLV.
    Run this ~30 min before first pitch — books pull lines at game time.
    """
    from src.data.odds_api import fetch_odds, get_best_odds
    from src.analytics.clv_tracker import compute_clv, print_clv_report
    import json as _json

    sport = _resolve_sport(args.sport)
    print(f"\n{'='*70}")
    print(f"  CLOSING LINE SNAPSHOT — {sport}")
    print(f"{'='*70}\n")

    # Fetch fresh odds — this overwrites the cache with closing lines
    print("  Fetching closing lines from sportsbooks...")
    raw_df = fetch_odds(markets="h2h", sport=sport, refresh=True)
    if raw_df.empty:
        print("  No odds returned — books may have already pulled lines.")
        return
    odds_df = get_best_odds(raw_df, market="h2h")
    if odds_df.empty:
        print("  No odds returned — books may have already pulled lines.")
        return

    print(f"  Got lines for {len(odds_df)} games.")

    # Save raw odds to a dated closing-line file so we never lose them
    close_dir = Path("data/clv/closing")
    close_dir.mkdir(parents=True, exist_ok=True)
    close_file = close_dir / f"{sport}_{date.today().isoformat()}.json"
    close_file.write_text(odds_df.to_json(orient="records", indent=2))
    print(f"  Closing lines saved to {close_file}")

    # Also write to the standard cache path compute_clv() reads from
    cache_dir = Path("data/cache/odds")
    cache_dir.mkdir(parents=True, exist_ok=True)

    # compute_clv reads the raw Odds API format — rebuild it from odds_df rows
    raw_games = []
    for _, row in odds_df.iterrows():
        raw_games.append({
            "bookmakers": [{
                "key": "best",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": row["HomeTeam"], "price": row["BestHomeML"]},
                        {"name": row["AwayTeam"], "price": row["BestAwayML"]},
                    ],
                }],
            }]
        })
    (cache_dir / f"{sport}_latest.json").write_text(_json.dumps(raw_games, indent=2))

    # Compute CLV now that we have closing lines
    print("\n  Computing CLV against opening lines...")
    updated = compute_clv(date_str=date.today().isoformat())
    if updated:
        print_clv_report()
    else:
        print("  No opening-line snapshots found for today.")
        print("  Did you run --daily or --tomorrow last night?")


def run_grade(args):
    """Grade picks against actual game results."""
    from src.grading.auto_grade import grade_picks, grade_slate, poll_and_grade

    sport = _resolve_sport(args.sport)
    grade_date = None
    if args.grade_date:
        grade_date = date.fromisoformat(args.grade_date)

    if args.grade_poll:
        poll_and_grade(
            pick_date=grade_date,
            sport=sport,
            flat_stake=args.stake,
            interval_min=30,
            max_hours=8.0,
        )
    else:
        grade_picks(
            pick_date=grade_date,
            sport=sport,
            flat_stake=args.stake,
            verbose=True,
        )
        # Also grade the full slate (all games, all lines) for accuracy tracking
        grade_slate(pick_date=grade_date, sport=sport, verbose=True)

        # Compute CLV now that lines have closed
        try:
            from src.analytics.clv_tracker import compute_clv, print_clv_report
            date_str = grade_date.isoformat() if grade_date else None
            updated = compute_clv(date_str=date_str)
            if updated:
                print_clv_report()
        except Exception as _clv_err:
            print(f"  [CLV] Closing-line compute failed: {_clv_err}")

        # Auto-generate results reveal card for social posting
        try:
            from src.output.results_card import generate_results_card
            generate_results_card(sport=sport, card_date=grade_date)
        except Exception as _e:
            print(f"  (Results card skipped: {_e})")

        # Update public stats for the web app track record page
        try:
            from src.analytics.public_stats import write_public_stats
            write_public_stats()
        except Exception as _e:
            print(f"  [stats] public_stats update failed: {_e}")


def run_daily(args):
    """
    Daily edge-finder pipeline. Uses sport-specific models where available,
    falls back to line-shopping for sports without a trained model.
    """
    sport = _resolve_sport(args.sport)
    print(f"\n{'='*70}")
    print(f"  DAILY EDGE FINDER — {sport}")
    print(f"{'='*70}\n")

    if sport == "baseball_mlb":
        _run_mlb_daily(args, sport)
        return

    # Fallback: line-shopping mode for sports without a dedicated model
    print("  (Line-shopping mode — no sport-specific model yet)")
    raw_odds = odds_api.fetch_odds(refresh=args.refresh, sport=sport)
    if raw_odds.empty:
        print("No odds returned. Check ODDS_API_KEY or try a different sport/time.")
        return

    best_odds = odds_api.get_best_odds(raw_odds)
    predictions = _build_market_predictions(raw_odds)
    value_bets = find_value_bets(predictions, best_odds, min_edge=args.min_edge)

    if value_bets.empty:
        print("No edges above threshold today.")
        return

    if args.bankroll > 0:
        value_bets = size_bets(
            value_bets,
            bankroll=args.bankroll,
            kelly_fraction_pct=args.kelly_fraction,
        )
        print(print_kelly_bets(value_bets, args.bankroll))
    else:
        print(print_value_bets(value_bets, args.bankroll))

    value_bets = value_bets.copy()
    value_bets["Why"] = value_bets["Edge"].apply(
        lambda edge: f"Line-shopping edge ({edge * 100:.1f}% vs market consensus)."
    )

    _save_picks(value_bets, sport, args)


def run_backtest(args):
    """Backtest model against historical tournaments."""
    use_ensemble = not args.no_ensemble
    model_name = "Ensemble (5 models)" if use_ensemble else "XGBoost"

    print(f"Running backtesting mode with {model_name}...")
    print("  Testing years: 2010-2025 (excluding 2020)")

    results = []
    test_years = [y for y in range(2010, args.year) if y != 2020]

    for test_year in test_years:
        try:
            # Train on all years BEFORE test_year
            X_train, y_train = build_training_data(
                min_year=2003,
                max_year=test_year - 1,
                use_barttorvik=False,
            )

            if len(X_train) < 50:
                print(f"  Skipping {test_year}: insufficient training data")
                continue

            # Test on the test_year tournament
            X_test, y_test = build_training_data(
                min_year=test_year,
                max_year=test_year,
                use_barttorvik=False,
            )

            if len(X_test) == 0:
                continue

            if use_ensemble:
                model = EnsembleModel()
                model.add_model(XGBoostModel())
                model.add_model(LogisticModel())
                model.add_model(NeuralModel())
                model.add_model(BayesianModel())
                model.add_model(EloModel())
                model.train(X_train, y_train)

                # Optimize weights using last chunk of training data
                n = len(X_train)
                split = int(n * 0.8)
                model.optimize_weights(X_train.iloc[split:], y_train.iloc[split:])
            else:
                model = XGBoostModel()
                model.train(X_train, y_train)

            metrics = model.evaluate(X_test, y_test)

            row = {
                "Year": test_year,
                "Accuracy": metrics["accuracy"],
                "LogLoss": metrics["log_loss"],
                "Games": metrics.get("n_samples", len(y_test)),
                "TrainSize": len(X_train),
            }

            # Add per-model metrics for ensemble
            if use_ensemble:
                row["Models"] = metrics.get("n_models", "?")

            results.append(row)

            extra = f" ({metrics.get('n_models', '?')} models)" if use_ensemble else ""
            print(
                f"  {test_year}: {metrics['accuracy']:.1%} accuracy, "
                f"{metrics['log_loss']:.4f} log loss "
                f"({metrics.get('n_samples', len(y_test))} games){extra}"
            )

        except Exception as e:
            print(f"  {test_year}: FAILED — {e}")

    if results:
        df = pd.DataFrame(results)
        print(f"\n  {'='*50}")
        print(f"  BACKTEST SUMMARY ({model_name})")
        print(f"  {'='*50}")
        print(f"  Years tested: {len(results)}")
        print(f"  Average accuracy: {df['Accuracy'].mean():.1%}")
        print(f"  Average log loss: {df['LogLoss'].mean():.4f}")
        print(f"  Best year: {df.loc[df['Accuracy'].idxmax(), 'Year']} "
              f"({df['Accuracy'].max():.1%})")
        print(f"  Worst year: {df.loc[df['Accuracy'].idxmin(), 'Year']} "
              f"({df['Accuracy'].min():.1%})")
        print(f"  {'='*50}\n")

        os.makedirs("output", exist_ok=True)
        df.to_csv("output/backtest_results.csv", index=False)
        print(f"  Results saved to output/backtest_results.csv")


if __name__ == "__main__":
    main()
