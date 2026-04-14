"""Line shopping endpoint — find best odds across all sportsbooks."""
from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(tags=["line_shop"])

SPORT_MAP = {
    "mlb": "baseball_mlb",
    "nba": "basketball_nba",
    "ncaab": "basketball_ncaab",
    "nfl": "americanfootball_nfl",
}


@router.get("/line-shop/{sport}")
async def get_line_shop(
    sport: str,
    min_edge: float = Query(0.02, ge=0, le=1),
):
    sport_key = SPORT_MAP.get(sport, sport)

    if sport_key == "baseball_mlb":
        return _mlb_line_shop(sport_key, min_edge)
    return _generic_line_shop(sport_key, min_edge)


def _mlb_line_shop(sport_key: str, min_edge: float) -> dict:
    from src.data.mlb_stats import get_todays_matchups
    from src.models.mlb_model import predict_all_games, predictions_to_dict
    from src.data.odds_api import fetch_odds
    from src.betting.line_shop import shop_lines, line_shop_to_dicts

    matchups = get_todays_matchups()
    if not matchups:
        return {"sport": sport_key, "picks": [], "message": "No games today"}

    preds = predict_all_games(matchups)
    predictions = predictions_to_dict(preds)

    raw_odds = fetch_odds(sport=sport_key)
    if raw_odds.empty:
        return {"sport": sport_key, "picks": [], "message": "No odds available"}

    results = shop_lines(predictions, raw_odds, min_combined_edge=min_edge)
    picks = line_shop_to_dicts(results)

    return {
        "sport": sport_key,
        "total_games": len(matchups),
        "value_picks": len(picks),
        "picks": picks,
    }


def _generic_line_shop(sport_key: str, min_edge: float) -> dict:
    import numpy as np
    from src.data.odds_api import fetch_odds
    from src.betting.line_shop import shop_lines, line_shop_to_dicts

    raw_odds = fetch_odds(sport=sport_key)
    if raw_odds.empty:
        return {"sport": sport_key, "picks": [], "message": "No odds available"}

    predictions = {}
    for game_id in raw_odds["GameID"].dropna().unique():
        game = raw_odds[raw_odds["GameID"] == game_id]
        if "HomeImpliedProb" not in game.columns:
            continue
        probs = game[["HomeImpliedProb", "AwayImpliedProb"]].dropna()
        if probs.empty:
            continue
        sums = probs["HomeImpliedProb"] + probs["AwayImpliedProb"]
        fair_home = (probs["HomeImpliedProb"] / sums.replace(0, np.nan)).dropna()
        if fair_home.empty:
            continue
        home = game["HomeTeamCanonical"].iloc[0] or game["HomeTeam"].iloc[0]
        away = game["AwayTeamCanonical"].iloc[0] or game["AwayTeam"].iloc[0]
        predictions[(home, away)] = float(fair_home.median())

    results = shop_lines(predictions, raw_odds, min_combined_edge=min_edge)
    picks = line_shop_to_dicts(results)

    return {"sport": sport_key, "picks": picks}
