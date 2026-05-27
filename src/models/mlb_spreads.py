"""
MLB spread (run line) edge detection.

Converts moneyline win probability to an expected margin using a
calibrated logistic mapping, then compares against the market spread.
No separate model is needed — we derive spread edges from the existing
win probability model.

The MLB standard run line is -1.5 / +1.5. Historically, the relationship
between win probability and expected margin follows a logistic-style curve:
  - 50% win prob ≈ 0 margin
  - 60% win prob ≈ +0.5 margin
  - 70% win prob ≈ +1.3 margin
  - 80% win prob ≈ +2.5 margin

We calibrate this from historical data in build_training_data.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.odds_api import SPREAD_LINE_ABS_MAX

MODEL_PATH = Path("models/mlb_spread_calibration.pkl")

# Fallback calibration from historical MLB data:
# Expected margin as a function of win probability, fit to a logistic curve.
# margin = A * log(p / (1-p)) where A is calibrated from data
DEFAULT_MARGIN_SCALE = 3.8  # ~3.8 runs per log-odds unit


def win_prob_to_margin(prob: float, scale: float | None = None) -> float:
    """
    Convert win probability to expected run margin.

    Uses log-odds linear mapping: margin = scale * ln(p / (1-p))
    """
    if scale is None:
        loaded = _load_calibration()
        scale = loaded if loaded else DEFAULT_MARGIN_SCALE

    prob = np.clip(prob, 0.01, 0.99)
    return scale * np.log(prob / (1 - prob))


def calibrate_spread_model(verbose: bool = True) -> float:
    """
    Calibrate the win_prob → margin conversion from historical data.

    Fits scale parameter on the relationship between actual game margins
    and pre-game win probabilities from the ensemble model.
    """
    from src.models.mlb_xgboost import build_training_data, FEATURE_COLS

    if verbose:
        print("\n  Calibrating spread conversion from historical data...")

    df = build_training_data(verbose=verbose)
    if df.empty:
        return DEFAULT_MARGIN_SCALE

    df["margin"] = df["home_score"] - df["away_score"]
    df["pyth_clip"] = df["home_pyth"].clip(0.01, 0.99)
    df["log_odds"] = np.log(df["pyth_clip"] / (1 - df["pyth_clip"]))

    valid = df.dropna(subset=["log_odds", "margin"])
    valid = valid[np.isfinite(valid["log_odds"])]

    if len(valid) < 100:
        return DEFAULT_MARGIN_SCALE

    # OLS fit: margin = scale * log_odds
    x = valid["log_odds"].values
    y = valid["margin"].values
    scale = float(np.dot(x, y) / np.dot(x, x))

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"scale": scale}, f)

    if verbose:
        pred_margins = scale * x
        mae = np.mean(np.abs(pred_margins - y))
        rmse = np.sqrt(np.mean((pred_margins - y) ** 2))
        print(f"  Calibrated scale: {scale:.3f} (default: {DEFAULT_MARGIN_SCALE})")
        print(f"  MAE: {mae:.2f} runs | RMSE: {rmse:.2f}")

    return scale


def _load_calibration() -> float | None:
    if not MODEL_PATH.exists():
        return None
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)
    return data.get("scale")


def find_spread_edges(
    predictions: dict[tuple[str, str], float],
    odds_df: pd.DataFrame,
    min_edge_runs: float = 0.4,
) -> list[dict]:
    """
    Find run line edges by comparing model-implied margin vs. market spread.

    predictions: dict of (home, away) → P(home wins) from the model.
    odds_df: raw odds DataFrame with HomeSpread, AwaySpread, etc.
    """
    if odds_df.empty or not predictions:
        return []

    loaded = _load_calibration()
    scale = loaded if loaded else DEFAULT_MARGIN_SCALE

    edges = []
    for game_id in odds_df["GameID"].unique():
        game_rows = odds_df[odds_df["GameID"] == game_id]
        if "HomeSpread" not in game_rows.columns:
            continue

        hs = game_rows["HomeSpread"].dropna()
        hs = hs[(hs >= -SPREAD_LINE_ABS_MAX) & (hs <= SPREAD_LINE_ABS_MAX)]
        if hs.empty:
            continue
        market_spread = float(hs.median())

        home = game_rows["HomeTeamCanonical"].iloc[0] or game_rows["HomeTeam"].iloc[0]
        away = game_rows["AwayTeamCanonical"].iloc[0] or game_rows["AwayTeam"].iloc[0]
        commence = game_rows["CommenceTime"].iloc[0] if "CommenceTime" in game_rows.columns else ""

        model_prob_home = None
        if (home, away) in predictions:
            model_prob_home = predictions[(home, away)]
        elif (away, home) in predictions:
            model_prob_home = 1 - predictions[(away, home)]
        else:
            continue

        # Calibrate the underlying win prob before deriving the margin so the
        # spread edge and the model_prob written to picks.json agree.
        try:
            from src.analytics.calibration import apply_calibration
            model_prob_home = apply_calibration(model_prob_home, "mlb", "spread")
        except Exception:
            pass

        model_margin = win_prob_to_margin(model_prob_home, scale)

        # Positive market_spread means home is underdog (+1.5).
        # Negative means home is favored (-1.5).
        # Model margin is home_score - away_score expectation.
        #
        # Home covers when: model_margin > -market_spread (cover threshold).
        # Edge = model_margin - cover_threshold = model_margin - (-market_spread)
        #      = model_margin + market_spread
        #
        # Example: home at -1.5 (market_spread = -1.5), model_margin = 2.0
        #   edge = 2.0 + (-1.5) = +0.5 → home covers ✓ (wins by 2 > 1.5)
        # Example: home at -1.5, model_margin = 1.0
        #   edge = 1.0 + (-1.5) = -0.5 → away covers ✓ (wins by only 1 < 1.5)
        edge = model_margin + market_spread

        if abs(edge) >= min_edge_runs:
            if edge > 0:
                # Model says home covers (or the favorite covers more than market expects)
                team, opponent = home, away
                direction = f"{home} {market_spread:+.1f}"
                best_col = "HomeSpreadOdds"
            else:
                team, opponent = away, home
                direction = f"{away} {-market_spread:+.1f}"
                best_col = "AwaySpreadOdds"

            best_odds = -110
            best_book = ""
            if best_col in game_rows.columns:
                valid = game_rows.dropna(subset=[best_col])
                if not valid.empty:
                    best_idx = valid[best_col].idxmax()
                    best_odds = int(valid.loc[best_idx, best_col])
                    best_book = valid.loc[best_idx, "Sportsbook"]

            # Skip picks at -105 or better (42% WR historically — vig eats the profit)
            # and at -136 or worse (team is too heavy a favorite on the run line)
            if best_odds > -106 or best_odds < -135:
                continue

            edges.append({
                "home_team": home,
                "away_team": away,
                "team": team,
                "opponent": opponent,
                "model_margin": round(model_margin, 2),
                "market_spread": market_spread,
                "edge_runs": round(abs(edge), 2),
                "direction": direction,
                "best_odds": best_odds,
                "sportsbook": best_book,
                "game_id": game_id,
                "model_prob": round(model_prob_home if team == home else 1 - model_prob_home, 3),
                "commence_time": commence,
            })

    edges.sort(key=lambda e: e["edge_runs"], reverse=True)
    return edges
