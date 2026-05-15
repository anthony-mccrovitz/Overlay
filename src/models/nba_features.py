"""
Feature engineering for the NBA XGBoost model.
Converts raw game logs + team ratings into an ML-ready feature matrix.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

FEATURE_NAMES = [
    # Rolling efficiency (20-game windows)
    "home_ortg_20g", "home_drtg_20g", "home_pace_20g",
    "away_ortg_20g", "away_drtg_20g", "away_pace_20g",
    # Net rating differential (most predictive single feature)
    "net_rtg_diff",
    # Rest
    "home_rest_days", "away_rest_days", "rest_diff",
    "home_b2b", "away_b2b",
    # Recent form
    "home_form_5g",   # avg point differential last 5 games
    "home_form_10g",
    "away_form_5g",
    "away_form_10g",
    # Game context
    "is_playoff",
    "season_progress",   # 0.0 (game 1) → 1.0 (game 82)
    # H2H this season
    "h2h_margin",   # avg margin in H2H matchups so far this season (0 if no prior meetings)
]


def _parse_date(ds: str) -> Optional[date]:
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%Y%m%d"):
        try:
            return datetime.strptime(ds, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def build_feature_matrix(games: list[dict]) -> tuple[list[dict], list[float], list[float]]:
    """
    Build feature matrix from historical game records.
    Returns (features_list, y_spread, y_total).
    Features are dicts (one per game); targets are the actual outcomes.
    """
    # Sort by date for rolling calculations
    games_sorted = sorted(
        [g for g in games if g.get("game_date") and g.get("home_pts") and g.get("away_pts")],
        key=lambda g: g["game_date"]
    )

    # Rolling stats tracker per team
    team_games: dict[str, list[dict]] = defaultdict(list)
    h2h_history: dict[tuple, list[float]] = defaultdict(list)

    features: list[dict] = []
    y_spread: list[float] = []
    y_total:  list[float] = []

    for i, game in enumerate(games_sorted):
        home = game["home_team"]
        away = game["away_team"]
        gdate = _parse_date(game["game_date"])
        if not gdate:
            continue

        home_hist = team_games[home]
        away_hist = team_games[away]

        if len(home_hist) < 5 or len(away_hist) < 5:
            # Not enough history for rolling features — skip early-season games
            _update_history(team_games, h2h_history, game, home, away)
            continue

        def rolling_avg(hist, key, n):
            vals = [g[key] for g in hist[-n:] if g.get(key) is not None]
            return sum(vals) / len(vals) if vals else 0.0

        home_ortg = rolling_avg(home_hist, "ortg", 20)
        home_drtg = rolling_avg(home_hist, "drtg", 20)
        home_pace = rolling_avg(home_hist, "pace", 20)
        away_ortg = rolling_avg(away_hist, "ortg", 20)
        away_drtg = rolling_avg(away_hist, "drtg", 20)
        away_pace = rolling_avg(away_hist, "pace", 20)

        net_rtg_diff = (home_ortg - home_drtg) - (away_ortg - away_drtg)

        # Rest (days since last game)
        home_rest = _days_since_last(home_hist, gdate)
        away_rest = _days_since_last(away_hist, gdate)

        # Recent form (avg point differential)
        home_form_5  = rolling_avg(home_hist, "margin", 5)
        home_form_10 = rolling_avg(home_hist, "margin", 10)
        away_form_5  = rolling_avg(away_hist, "margin", 5)
        away_form_10 = rolling_avg(away_hist, "margin", 10)

        is_playoff    = 1 if game.get("season_type") == "Playoffs" else 0
        season_games  = [g for g in games_sorted if g.get("season") == game.get("season")]
        season_prog   = i / max(len(season_games), 1)

        h2h_key = tuple(sorted([home, away]))
        h2h_margin = sum(h2h_history[h2h_key]) / len(h2h_history[h2h_key]) if h2h_history[h2h_key] else 0.0

        row = {
            "home_ortg_20g": home_ortg, "home_drtg_20g": home_drtg, "home_pace_20g": home_pace,
            "away_ortg_20g": away_ortg, "away_drtg_20g": away_drtg, "away_pace_20g": away_pace,
            "net_rtg_diff":  net_rtg_diff,
            "home_rest_days": min(home_rest, 5), "away_rest_days": min(away_rest, 5),
            "rest_diff":     home_rest - away_rest,
            "home_b2b":      1 if home_rest == 0 else 0,
            "away_b2b":      1 if away_rest == 0 else 0,
            "home_form_5g":  home_form_5,  "home_form_10g": home_form_10,
            "away_form_5g":  away_form_5,  "away_form_10g": away_form_10,
            "is_playoff":    is_playoff,
            "season_progress": season_prog,
            "h2h_margin":    h2h_margin,
            # Metadata — not a feature, used for walk-forward CV season splits
            "season":        game.get("season", ""),
        }

        features.append(row)
        y_spread.append(float(game["spread_actual"]))
        y_total.append(float(game["total_actual"]))

        _update_history(team_games, h2h_history, game, home, away)

    return features, y_spread, y_total


def _days_since_last(hist: list[dict], current_date: date) -> int:
    if not hist:
        return 2
    last_ds = hist[-1].get("game_date", "")
    last_d  = _parse_date(last_ds)
    if not last_d:
        return 2
    return min((current_date - last_d).days - 1, 5)


def _update_history(team_games, h2h_history, game, home, away):
    home_pts = game.get("home_pts", 0) or 0
    away_pts = game.get("away_pts", 0) or 0
    margin   = home_pts - away_pts
    # Use real per-100-possession ratings when available; fall back to raw pts
    home_ortg = game.get("home_ortg") or home_pts
    home_drtg = game.get("home_drtg") or away_pts
    away_ortg = game.get("away_ortg") or away_pts
    away_drtg = game.get("away_drtg") or home_pts
    game_pace = game.get("pace") or 98.0

    team_games[home].append({
        "game_date": game.get("game_date"),
        "ortg": home_ortg,
        "drtg": home_drtg,
        "pace": game_pace,
        "margin": margin,
    })
    team_games[away].append({
        "game_date": game.get("game_date"),
        "ortg": away_ortg,
        "drtg": away_drtg,
        "pace": game_pace,
        "margin": -margin,
    })

    h2h_key = tuple(sorted([home, away]))
    h2h_history[h2h_key].append(margin)


def features_to_array(features: list[dict]) -> list[list[float]]:
    """Convert list of feature dicts to 2D array (rows=games, cols=features)."""
    return [[row.get(f, 0.0) for f in FEATURE_NAMES] for row in features]
