"""
MLB game totals (over/under) prediction model.

Predicts the expected total runs in a game using team offense/defense
stats and pitcher features. Trained on the same historical data as the
win probability model but with a regression target (home_score + away_score).
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBRegressor

from src.data.odds_api import TOTAL_LINE_MAX, TOTAL_LINE_MIN
from src.data.park_factors import apply_park_factor, OUTDOOR_PARKS
from src.data.weather import get_game_weather, weather_run_adjustment
from src.models.mlb_xgboost import build_training_data, FEATURE_COLS

MODEL_PATH = Path("models/mlb_totals.pkl")

TOTALS_FEATURES = [
    "home_rs_g", "home_ra_g", "away_rs_g", "away_ra_g",
    "rs_g_diff", "ra_g_diff",
    "home_pyth", "away_pyth", "pyth_diff",
    "home_rs_std", "away_rs_std",
    "home_sp_era", "away_sp_era", "sp_era_diff",
    "home_sp_whip", "away_sp_whip", "sp_whip_diff",
    "home_sp_k9", "away_sp_k9", "sp_k9_diff",
    "home_sp_bb9", "away_sp_bb9",
    "home_sp_fip_proxy", "away_sp_fip_proxy", "sp_fip_proxy_diff",
    "home_sp_ip", "away_sp_ip",
    "home_bullpen_era", "away_bullpen_era", "bullpen_era_diff",
    "home_elo", "away_elo", "elo_diff",
    "home_rest_days", "away_rest_days",
    "season_progress",
    "has_pitcher_data",
]


def train_totals_model(
    train_seasons: list[int] | None = None,
    test_seasons: list[int] | None = None,
    verbose: bool = True,
) -> dict:
    """Train an XGBoost regression model for game totals."""
    from src.models.mlb_xgboost import ALL_SEASONS, TEST_SEASONS

    if train_seasons is None:
        train_seasons = ALL_SEASONS
    if test_seasons is None:
        test_seasons = TEST_SEASONS

    if verbose:
        print("\n  Building training data for totals model...")

    df = build_training_data(seasons=train_seasons + test_seasons, verbose=verbose)
    if df.empty:
        print("  No training data.")
        return {}

    df["total_runs"] = df["home_score"] + df["away_score"]

    available_feats = [f for f in TOTALS_FEATURES if f in df.columns]
    if verbose:
        print(f"  Using {len(available_feats)}/{len(TOTALS_FEATURES)} features")

    train_mask = df["season"].isin(train_seasons)
    test_mask = df["season"].isin(test_seasons)

    X_train = df.loc[train_mask, available_feats].fillna(0)
    y_train = df.loc[train_mask, "total_runs"]
    X_test = df.loc[test_mask, available_feats].fillna(0)
    y_test = df.loc[test_mask, "total_runs"]

    if verbose:
        print(f"  Train: {len(X_train)} games, Test: {len(X_test)} games")
        print(f"  Train mean total: {y_train.mean():.2f}, Test mean total: {y_test.mean():.2f}")

    model = XGBRegressor(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=10,
        reg_alpha=0.5,
        reg_lambda=1.0,
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train, y_train)

    train_pred = model.predict(X_train)
    test_pred = model.predict(X_test)

    train_mae = np.mean(np.abs(train_pred - y_train))
    test_mae = np.mean(np.abs(test_pred - y_test))
    train_rmse = np.sqrt(np.mean((train_pred - y_train) ** 2))
    test_rmse = np.sqrt(np.mean((test_pred - y_test) ** 2))

    # Baseline: always predict league average
    baseline_pred = y_train.mean()
    baseline_mae = np.mean(np.abs(baseline_pred - y_test))
    baseline_rmse = np.sqrt(np.mean((baseline_pred - y_test) ** 2))

    # Over/under accuracy at the median line
    median_line = y_test.median()
    model_ou_correct = np.mean(
        (test_pred > median_line) == (y_test > median_line)
    )
    baseline_ou_correct = 0.5

    # Walk-forward CV for O/U accuracy
    cv_correct = []
    sorted_seasons = sorted(set(df["season"]))
    for i in range(max(3, len(sorted_seasons) - 3), len(sorted_seasons)):
        cv_train_seasons = sorted_seasons[:i]
        cv_test_season = sorted_seasons[i]
        cv_train = df[df["season"].isin(cv_train_seasons)]
        cv_test = df[df["season"] == cv_test_season]
        if len(cv_test) < 50:
            continue

        cv_X_train = cv_train[available_feats].fillna(0)
        cv_y_train = cv_train["total_runs"]
        cv_X_test = cv_test[available_feats].fillna(0)
        cv_y_test = cv_test["total_runs"]

        cv_model = XGBRegressor(
            n_estimators=300, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
            reg_alpha=0.5, reg_lambda=1.0, random_state=42, verbosity=0,
        )
        cv_model.fit(cv_X_train, cv_y_train)
        cv_pred = cv_model.predict(cv_X_test)

        line = cv_y_train.mean()
        acc = np.mean((cv_pred > line) == (cv_y_test > line))
        cv_correct.append({"season": cv_test_season, "accuracy": acc, "games": len(cv_test)})

    cv_mean = np.mean([c["accuracy"] for c in cv_correct]) if cv_correct else 0

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({
            "model": model,
            "features": available_feats,
            "train_mean": float(y_train.mean()),
        }, f)

    results = {
        "train_mae": train_mae,
        "test_mae": test_mae,
        "train_rmse": train_rmse,
        "test_rmse": test_rmse,
        "baseline_mae": baseline_mae,
        "baseline_rmse": baseline_rmse,
        "model_ou_accuracy": model_ou_correct,
        "baseline_ou_accuracy": baseline_ou_correct,
        "cv_mean_ou_accuracy": cv_mean,
        "cv_seasons": cv_correct,
        "train_mean_total": float(y_train.mean()),
    }

    if verbose:
        print(f"\n  {'='*50}")
        print(f"  TOTALS MODEL RESULTS")
        print(f"  {'='*50}")
        print(f"  Train MAE: {train_mae:.2f} runs | RMSE: {train_rmse:.2f}")
        print(f"  Test  MAE: {test_mae:.2f} runs | RMSE: {test_rmse:.2f}")
        print(f"  Baseline MAE: {baseline_mae:.2f} | RMSE: {baseline_rmse:.2f}")
        print(f"  O/U Accuracy: {model_ou_correct:.1%} (baseline: 50%)")
        print(f"  CV Mean O/U: {cv_mean:.1%}")
        for c in cv_correct:
            print(f"    {c['season']}: {c['accuracy']:.1%} ({c['games']} games)")
        print(f"  Model saved to {MODEL_PATH}")
        print(f"  {'='*50}\n")

    return results


def load_totals_model() -> tuple | None:
    """Load trained totals model. Returns (model, features, train_mean) or None."""
    if not MODEL_PATH.exists():
        return None
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)
    return data["model"], data["features"], data["train_mean"]


def predict_total(
    home_stats: dict, away_stats: dict,
    model=None, features: list[str] | None = None,
    home_team: str | None = None,
) -> float:
    """Predict total runs for a single game.

    If *home_team* is supplied, applies a park-factor multiplier and
    optionally adds a weather-based run adjustment (outdoor parks only).
    """
    loaded = load_totals_model() if model is None else None
    if model is None:
        if loaded is None:
            raw = home_stats.get("rs_g", 4.5) + away_stats.get("rs_g", 4.5)
            if home_team:
                raw = apply_park_factor(raw, home_team)
            return raw
        model, features, _ = loaded

    row = {}
    for f in features:
        if f.startswith("home_"):
            key = f[5:]
            row[f] = home_stats.get(key, 0)
        elif f.startswith("away_"):
            key = f[5:]
            row[f] = away_stats.get(key, 0)
        elif f.endswith("_diff"):
            parts = f.rsplit("_diff", 1)[0]
            home_key = f"home_{parts}"
            away_key = f"away_{parts}"
            row[f] = row.get(home_key, 0) - row.get(away_key, 0)
        else:
            row[f] = home_stats.get(f, away_stats.get(f, 0))

    X = pd.DataFrame([row])[features].fillna(0)
    raw_total = float(model.predict(X)[0])

    # Sanity check: MLB games essentially never finish outside 4-25 runs total.
    # If the model produces something impossible, fall back to the simple sum.
    TOTAL_MIN, TOTAL_MAX = 4.0, 25.0
    if raw_total < TOTAL_MIN or raw_total > TOTAL_MAX:
        import warnings
        warnings.warn(
            f"predict_total: model output {raw_total:.2f} is outside plausible range "
            f"[{TOTAL_MIN}, {TOTAL_MAX}]. Falling back to rs_g + ra_g.",
            RuntimeWarning,
            stacklevel=2,
        )
        raw_total = home_stats.get("rs_g", 4.5) + away_stats.get("rs_g", 4.5)

    if not home_team:
        return raw_total

    # Apply park factor
    adjusted = apply_park_factor(raw_total, home_team)

    # Apply weather adjustment (outdoor parks only)
    is_outdoor = home_team in OUTDOOR_PARKS
    weather = get_game_weather(home_team)
    if weather is not None and is_outdoor:
        wind_adj = weather_run_adjustment(
            weather["wind_mph"],
            weather["wind_dir_deg"],
            is_outdoor=True,
        )
        adjusted += wind_adj

    # Apply umpire tendency adjustment (home plate ump O/U lean)
    try:
        from src.data.umpires import get_game_ump_adjustment
        ump_adj, ump_name = get_game_ump_adjustment(home_team)
        if ump_adj != 0.0:
            adjusted += ump_adj
    except Exception:
        pass

    return adjusted


def find_totals_edges(
    matchups,
    odds_df: pd.DataFrame,
    min_edge_runs: float = 0.5,
) -> list[dict]:
    """
    Find over/under edges by comparing model predicted total vs market line.

    Returns list of dicts with team names, predicted total, market line,
    direction (over/under), and edge in runs.
    """
    loaded = load_totals_model()
    if loaded is None:
        model, features, train_mean = None, None, None
    else:
        model, features, train_mean = loaded

    edges = []
    for game_id in odds_df["GameID"].unique():
        game_rows = odds_df[odds_df["GameID"] == game_id]
        if "Total" not in game_rows.columns:
            continue

        tl = game_rows["Total"].dropna()
        tl = tl[(tl >= TOTAL_LINE_MIN) & (tl <= TOTAL_LINE_MAX)]
        if tl.empty:
            continue
        total_line = float(tl.median())
        if total_line == 0:
            continue

        home = game_rows["HomeTeamCanonical"].iloc[0] or game_rows["HomeTeam"].iloc[0]
        away = game_rows["AwayTeamCanonical"].iloc[0] or game_rows["AwayTeam"].iloc[0]

        matchup = None
        for m in matchups:
            if (m.home_team.name == home and m.away_team.name == away) or (
                m.home_team.name == away and m.away_team.name == home
            ):
                matchup = m
                break
        if matchup is None:
            continue

        ht = matchup.home_team
        at = matchup.away_team

        # Estimate bullpen ERA from team ERA minus SP contribution
        # SP covers ~61% of innings; remainder is bullpen
        _SP_FRAC = 0.61
        h_sp_era = matchup.home_pitcher.era if matchup.home_pitcher and matchup.home_pitcher.era > 0 else (ht.era or 4.5)
        a_sp_era = matchup.away_pitcher.era if matchup.away_pitcher and matchup.away_pitcher.era > 0 else (at.era or 4.5)
        h_team_era = ht.era or 4.5
        a_team_era = at.era or 4.5
        h_bp_era = max(2.5, min(7.5, (h_team_era - h_sp_era * _SP_FRAC) / max(1 - _SP_FRAC, 0.2)))
        a_bp_era = max(2.5, min(7.5, (a_team_era - a_sp_era * _SP_FRAC) / max(1 - _SP_FRAC, 0.2)))

        # Elo proxy from win percentage (neutral=1500, each 10pp win% ≈ 40 Elo pts)
        h_win_pct = ht.wins / max(ht.wins + ht.losses, 1) if (ht.wins + ht.losses) > 0 else 0.5
        a_win_pct = at.wins / max(at.wins + at.losses, 1) if (at.wins + at.losses) > 0 else 0.5
        h_elo = 1500 + (h_win_pct - 0.5) * 400
        a_elo = 1500 + (a_win_pct - 0.5) * 400

        home_stats = {
            "rs_g": ht.rs_per_game or 4.5, "ra_g": ht.ra_per_game or 4.5,
            "pyth": 0.5, "win_pct": h_win_pct,
            "games": ht.games or 30, "rs_std": 2.5,
            "sp_era": h_sp_era,
            "sp_whip": matchup.home_pitcher.whip if matchup.home_pitcher else 1.3,
            "sp_k9": matchup.home_pitcher.k_per_9 if matchup.home_pitcher else 8.0,
            "sp_bb9": matchup.home_pitcher.bb_per_9 if matchup.home_pitcher else 3.0,
            "sp_ip": matchup.home_pitcher.innings_pitched if matchup.home_pitcher else 50,
            "sp_fip_proxy": 0, "sp_era_vs_team": 0,
            "bullpen_era": h_bp_era, "elo": h_elo, "rest_days": 1,
            "last10_pct": 0.5, "last5_pct": 0.5, "last20_pct": 0.5,
            "momentum": 0, "run_diff_g": 0, "home_pct": 0.5, "pyth_residual": 0,
        }
        away_stats = {
            "rs_g": at.rs_per_game or 4.5, "ra_g": at.ra_per_game or 4.5,
            "pyth": 0.5, "win_pct": a_win_pct,
            "games": at.games or 30, "rs_std": 2.5,
            "sp_era": a_sp_era,
            "sp_whip": matchup.away_pitcher.whip if matchup.away_pitcher else 1.3,
            "sp_k9": matchup.away_pitcher.k_per_9 if matchup.away_pitcher else 8.0,
            "sp_bb9": matchup.away_pitcher.bb_per_9 if matchup.away_pitcher else 3.0,
            "sp_ip": matchup.away_pitcher.innings_pitched if matchup.away_pitcher else 50,
            "sp_fip_proxy": 0, "sp_era_vs_team": 0,
            "bullpen_era": a_bp_era, "elo": a_elo, "rest_days": 1,
            "away_pct": 0.5, "last10_pct": 0.5, "last5_pct": 0.5, "last20_pct": 0.5,
            "momentum": 0, "run_diff_g": 0, "pyth_residual": 0,
        }

        pred_total = predict_total(
            home_stats, away_stats,
            model, features if model is not None else None,
            home_team=matchup.home_team.name,
        )

        # Lineup quality adjustment — shift prediction based on confirmed lineups.
        # League avg OPS ≈ 0.720. Each 0.050 OPS above/below avg ≈ +/- 0.3 runs.
        # Only applies when lineup is confirmed (posted ~2-3h before first pitch).
        try:
            from src.data.mlb_stats import fetch_lineup_quality
            _LEAGUE_OPS = 0.720
            _OPS_SCALE = 6.0  # runs per unit OPS delta per team
            home_lq = fetch_lineup_quality(matchup.home_team.team_id, matchup.game_id,
                                           pitcher_throws=getattr(matchup.away_pitcher, "throws", "R") or "R")
            away_lq = fetch_lineup_quality(matchup.away_team.team_id, matchup.game_id,
                                           pitcher_throws=getattr(matchup.home_pitcher, "throws", "R") or "R")
            if home_lq.get("lineup_confirmed") or away_lq.get("lineup_confirmed"):
                ops_adj = (
                    (home_lq["lineup_ops"] - _LEAGUE_OPS) * _OPS_SCALE
                    + (away_lq["lineup_ops"] - _LEAGUE_OPS) * _OPS_SCALE
                )
                pred_total = round(pred_total + ops_adj, 2)
        except Exception:
            pass

        diff = pred_total - total_line

        if abs(diff) >= min_edge_runs:
            direction = "OVER" if diff > 0 else "UNDER"

            # Find best odds for this direction
            best_odds = -110
            best_book = ""
            odds_col = "OverOdds" if direction == "OVER" else "UnderOdds"
            if odds_col in game_rows.columns:
                valid = game_rows.dropna(subset=[odds_col])
                if not valid.empty:
                    best_idx = valid[odds_col].idxmax()
                    best_odds = int(valid.loc[best_idx, odds_col])
                    best_book = valid.loc[best_idx, "Sportsbook"]

            # Convert run-edge to win probability using normal distribution.
            # MLB game total std dev ≈ 2.8 runs (empirical).
            from scipy.stats import norm as _norm
            _STD = 2.8
            if direction == "OVER":
                model_prob = float(1 - _norm.cdf((total_line - pred_total) / _STD))
            else:
                model_prob = float(_norm.cdf((total_line - pred_total) / _STD))
            # Apply trained MLB total calibrator so picks.json reflects the
            # post-calibration probability that the edge was computed from.
            try:
                from src.analytics.calibration import apply_calibration
                model_prob = apply_calibration(model_prob, "mlb", "total")
            except Exception:
                pass
            implied_prob = 0.5  # default; overridden below with real vig-adjusted odds
            # Umpire info for display
            try:
                from src.data.umpires import get_game_ump_adjustment
                _ump_adj, _ump_name = get_game_ump_adjustment(home)
            except Exception:
                _ump_adj, _ump_name = 0.0, None

            edges.append({
                "home_team": home,
                "away_team": away,
                "predicted_total": round(pred_total, 1),
                "market_line": total_line,
                "edge_runs": round(abs(diff), 1),
                "direction": direction,
                "best_odds": best_odds,
                "sportsbook": best_book,
                "game_id": game_id,
                "commence_time": game_rows["CommenceTime"].iloc[0] if "CommenceTime" in game_rows.columns else "",
                "model_prob": round(model_prob, 4),
                "ump_name": _ump_name,
                "ump_adj": round(_ump_adj, 2) if _ump_adj else 0.0,
            })

    edges.sort(key=lambda e: e["edge_runs"], reverse=True)
    return edges
